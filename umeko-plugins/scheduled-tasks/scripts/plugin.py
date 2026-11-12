"""Session-owned timers, delivered through the existing Widget and Agent Bus APIs."""
from collections import defaultdict, deque
from datetime import datetime
import json
from queue import Empty, Queue
import sqlite3
from threading import Thread
from time import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PySide6.QtCore import QLockFile
from umeko_plugin_sdk import Plugin, PluginError
from .scheduled_tasks import Schedule, ScheduledTasks

POLL_SECONDS = 1
MAX_POLL_GAP_SECONDS = 10


class ScheduledTasksPlugin(Plugin):
    def __init__(self, context):
        super().__init__(context)
        self.lock = QLockFile(str(context.state_dir / 'scheduler.lock'))
        self.lock.setStaleLockTime(0)
        if not self.lock.tryLock(0):
            raise PluginError('此配置的定时任务已在另一 Umeko 实例运行 / Scheduled Tasks is running in another instance')
        self.store = ScheduledTasks(context.state_dir / 'schedules.sqlite3')
        self.commands, self.waiting = Queue(), deque()
        self.active, self.pending = {}, {}
        self.started_at = self.last_scan = self.now()
        self.store.recover(self.started_at)
        self.thread = Thread(target=self._run, name='scheduled-tasks', daemon=True)
        self.thread.start()

    @staticmethod
    def now():return int(time())

    def handle(self, method, args):
        try:return self._handle(method, args)
        except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError) as error:
            raise PluginError(str(error)) from error

    def _handle(self, method, args):
        session = self.context.request_session or self.context.session
        owner, source = self.store.bind_session(session)
        targets = session.get('timerTargets', [])
        allowed = {row['id'] for row in targets}
        if method == 'targets':return {'targets': targets}
        if method == 'list':
            tasks = self.store.tasks(owner=owner)
            for task in tasks:
                zone, due = task['schedule'].get('zone', 'UTC'), task['next_at']
                task['next_label'] = (datetime.fromtimestamp(due, ZoneInfo(zone)).strftime('%Y-%m-%d %H:%M:%S')
                                      + ' ' + zone) if due is not None else ''
                task['target_name'] = next((row['name'] for row in targets if row['id'] == task['target']),
                                           '目标已断开 / Target disconnected')
            return {'tasks': tasks, 'limit': 5}
        task_id = args.get('task_id')
        if method == 'history':return {'runs': self.store.history(task_id, limit=20, owner=owner)}
        if method in ('create', 'save'):
            if set(args) - {'task_id', 'name', 'message', 'schedule', 'enabled', 'target'}:
                raise ValueError('Unknown timer fields')
            if method == 'create' and task_id is not None:raise ValueError('Create cannot overwrite a timer')
            name, message, target = args['name'], args['message'], args.get('target', 'main')
            if not all(isinstance(value, str) for value in (name, message, target)):
                raise ValueError('Name, message and target must be text')
            if len(name) > 120 or len(message) > 8000 or len(json.dumps(message)) > 12000:
                raise ValueError('Name or message is too long')
            if target not in allowed:raise ValueError('目标未与本会话建立 Agent Bus / Target is not connected')
            if args['schedule'].get('frequency') not in ('once', 'interval'):
                raise ValueError('Only once and interval timers can be created')
            now = self.now()
            schedule = Schedule.from_dict(args['schedule'], now=now)
            enabled = args.get('enabled', True)
            if type(enabled) is not bool:raise ValueError('Enabled must be true or false')
            return {'task_id': self.store.save(task_id=task_id, name=name, message=message,
                schedule=schedule, enabled=enabled, now=now, owner=owner, source=source, target=target,
                model_oneshot=method == 'create' and schedule.frequency == 'once' and enabled)}
        if method in ('enable', 'disable', 'set_enabled'):
            enabled = args.get('enabled') if method == 'set_enabled' else method == 'enable'
            if type(enabled) is not bool:raise ValueError('Enabled must be true or false')
            if enabled:
                task = next((row for row in self.store.tasks(owner=owner) if row['id'] == task_id), None)
                if not task:raise ValueError('Timer does not belong to this conversation')
                if task['target'] not in allowed:raise ValueError('Target is no longer connected')
            self.store.set_enabled(task_id, enabled, self.now(), owner=owner)
            return {'task_id': task_id, 'enabled': enabled}
        if method == 'delete':
            self.store.delete(task_id, owner=owner)
            return {'task_id': task_id, 'deleted': True}
        if method == 'run':
            run = self.store.claim_manual(task_id, self.now(), owner=owner)
            self.commands.put(('start', run))
            return {'run_id': run['id']}
        raise ValueError('Unknown scheduled tasks operation')

    def on_event(self, name, data):
        if name == 'host.response':self.commands.put(('host', data))
        elif name == 'session.changed' and data.get('token'):
            self.store.bind_session(data)

    def _run(self):
        while not self.context.cancelled.is_set():
            try:
                self._poll()
                self._pump()
                kind, value = self.commands.get(timeout=POLL_SECONDS)
                if kind == 'start':self._enqueue(value)
                elif kind == 'host':self._host_response(value)
            except Empty:pass
            except (OSError, sqlite3.Error, PluginError, ValueError) as error:
                if not self.context.cancelled.is_set():
                    print(f'Scheduled tasks: {error}', flush=True)
                    self.context.cancelled.wait(POLL_SECONDS)

    def _enqueue(self, run):
        if len(self.active) + len(self.waiting) >= 32:
            self.store.finish(run['id'], 'failed', self.now(), detail='Timer delivery queue is full')
        else:self.waiting.append(run)

    def _poll(self):
        now = self.now()
        if now == self.last_scan:return
        previous = self.last_scan
        earliest = max(self.started_at, previous) if 0 < now - previous <= MAX_POLL_GAP_SECONDS else now
        for run in self.store.claim_due(now, eligible_since=earliest):self._enqueue(run)
        self.last_scan = now
        # The host returns delivery receipts, never fabricated model results.
        polling = {key for kind, keys in self.pending.values() if kind == 'status' for key in keys}
        groups = defaultdict(list)
        for key, source in self.active.items():
            if key not in polling:groups[json.dumps(source, sort_keys=True)].append(key)
        for source, ids in groups.items():
            if len(self.pending) >= 4:break
            request = self.context.request_host('scheduledTasks.status', {'run_ids': ids}, session=json.loads(source))
            self.pending[request] = ('status', ids)

    def _pump(self):
        while self.waiting and len(self.pending) < 4:
            run = self.waiting.popleft()
            snapshot = run['snapshot']
            try:
                request = self.context.request_host('scheduledTasks.trigger', {'run_id': run['id'],
                    'target': snapshot['target'], 'text': snapshot['message']}, session=snapshot['source'])
            except (PluginError, ValueError) as error:
                self.store.finish(run['id'], 'failed', self.now(), detail=str(error)[:1000])
                continue
            self.active[run['id']] = snapshot['source']
            self.pending[request] = ('trigger', [run['id']])

    def _host_response(self, data):
        request = self.pending.pop(data.get('requestId'), None)
        if not request:return
        kind, ids = request
        if not data.get('ok'):
            for key in ids:
                self.store.finish(key, 'failed', self.now(), detail=str(data.get('error', 'Host request failed'))[:1000])
                self.active.pop(key, None)
        elif kind == 'trigger':
            source = data.get('result', {}).get('source')
            if source:
                self.store.bind_session(source)
                self.active[ids[0]] = source
        else:
            for row in data.get('result', {}).get('runs', []):
                if row['id'] not in ids:continue
                if row.get('session_id'):self.store.set_session(row['id'], row['session_id'])
                if row['state'] in ('delivered', 'failed', 'cancelled'):
                    self.store.finish(row['id'], row['state'], self.now(), detail=row.get('detail', ''))
                    self.active.pop(row['id'], None)

    def close(self):
        super().close()
        self.commands.put(('stop', None))
        self.thread.join(timeout=2)
        if not self.thread.is_alive():self.lock.unlock()


def create_plugin(context):return ScheduledTasksPlugin(context)
