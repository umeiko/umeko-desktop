"""Run scheduled prompts using only the host's plugin-owned Pi sessions."""
from contextlib import suppress
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
REQUEST_TIMEOUT_SECONDS = 30
TERMINAL = frozenset({'completed', 'failed', 'cancelled'})


class ScheduledTasksPlugin(Plugin):
    def __init__(self, context):
        super().__init__(context)
        self.lock = QLockFile(str(context.state_dir / 'scheduler.lock'))
        self.lock.setStaleLockTime(0)
        if not self.lock.tryLock(0):
            raise PluginError('此配置的定时任务已在另一 Umeko 实例运行 / Scheduled Tasks is running in another instance')
        self.store = ScheduledTasks(context.state_dir / 'schedules.sqlite3')
        self.commands = Queue()
        self.active = {}  # Native run ID -> (persistent run ID, lease)
        self.started_at = self.last_scan = self.now()
        self.store.recover(self.started_at)
        self.thread = Thread(target=self._run, name='scheduled-tasks', daemon=True)
        self.thread.start()

    @staticmethod
    def now():
        return int(time())

    def handle(self, method, args):
        try:
            return self._handle(method, args)
        except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError) as error:
            raise PluginError(str(error)) from error

    def _handle(self, method, args):
        if method == 'list':
            tasks = self.store.tasks()
            for task in tasks:
                zone = task['schedule']['zone']
                due = task['next_at']
                task['next_label'] = (datetime.fromtimestamp(due, ZoneInfo(zone)).strftime('%Y-%m-%d %H:%M')
                                      + ' ' + zone) if due is not None else ''
            return {'tasks': tasks}
        task_id = args.get('task_id')
        if method == 'history':
            return {'runs': self.store.history(task_id, limit=20)}
        if method == 'save':
            message = args['message']
            profile = args['profile']
            name = args['name']
            if not all(isinstance(value, str) for value in (name, message, profile)):
                raise ValueError('Name, message and profile must be text')
            if len(name) > 120 or len(profile) > 512 or len(json.dumps(message)) > 12000:
                raise ValueError('Name, message or profile is too long')
            schedule = Schedule.from_dict(args['schedule'])
            if type(args['enabled']) is not bool:
                raise ValueError('Enabled must be true or false')
            return {'task_id': self.store.save(task_id=task_id, name=name, message=message,
                    profile=profile, schedule=schedule, enabled=args['enabled'], now=self.now())}
        if method == 'set_enabled':
            if type(args['enabled']) is not bool:
                raise ValueError('Enabled must be true or false')
            self.store.set_enabled(task_id, args['enabled'], self.now())
            return {'task_id': task_id}
        if method == 'run':
            run = self.store.claim_manual(task_id, self.now())
            self.commands.put(('start', run))
            return {'run_id': run['id']}
        if method == 'cancel':
            self.commands.put(('cancel', args['run_id']))
            return {}
        raise ValueError('Unknown scheduled tasks operation')

    def on_event(self, name, data):
        if name == 'sessions.event' and data.get('type') == 'turn_end':
            self.commands.put(('finish', data))

    def _run(self):
        while not self.context.cancelled.is_set():
            try:
                self._poll()
                command, value = self.commands.get(timeout=POLL_SECONDS)
                if self.context.cancelled.is_set():
                    break
                if command == 'start':
                    self._start(value)
                elif command == 'finish':
                    self._finish(value)
                elif command == 'cancel':
                    self._cancel(value)
            except Empty:
                pass
            except (OSError, sqlite3.Error, PluginError) as error:
                # Retry a temporarily unavailable store on the next tick.
                if not self.context.cancelled.is_set():
                    print(f'Scheduled tasks: {error}', flush=True)
                    self.context.cancelled.wait(POLL_SECONDS)

    def _poll(self):
        now = self.now()
        if now == self.last_scan:
            return
        previous = self.last_scan
        earliest = max(self.started_at, previous) if 0 < now - previous <= MAX_POLL_GAP_SECONDS else now
        runs = self.store.claim_due(now, eligible_since=earliest)
        self.last_scan = now
        for run in runs:
            self.commands.put(('start', run))

    def _start(self, run):
        sessions = self.context.sessions
        handle = None
        run_id = run['id']
        try:
            acquired = sessions.acquire(run_id, profile=run['snapshot']['profile'],
                                        namespace='scheduled-tasks', timeout=REQUEST_TIMEOUT_SECONDS)
            handle = acquired['handle']
            self.store.set_session(run_id, acquired['sessionId'])
            sessions.subscribe(handle, timeout=REQUEST_TIMEOUT_SECONDS)
            result = sessions.submit(handle, run_id, run['snapshot']['message'],
                                     timeout=REQUEST_TIMEOUT_SECONDS)
            self.active[result['runId']] = (run_id, handle)
        except (PluginError, OSError, sqlite3.Error) as error:
            if self.context.cancelled.is_set():
                return
            if handle is not None:
                # Submit may have succeeded even if its reply timed out.
                with suppress(PluginError):
                    sessions.cancel(handle, timeout=REQUEST_TIMEOUT_SECONDS)
                self._release(handle)
            self.store.finish(run_id, 'failed', self.now(), detail=str(error)[:1000])

    def _finish(self, event):
        native_id = event.get('runId')
        current = self.active.get(native_id)
        if current is None or current[1] != event.get('handle') or event.get('status') not in TERMINAL:
            return
        run_id, handle = current
        self.store.finish(run_id, event['status'], self.now(), detail=str(event.get('error', ''))[:1000])
        del self.active[native_id]
        self._release(handle)

    def _cancel(self, run_id):
        for native_id, (stored_id, handle) in self.active.items():
            if run_id == stored_id:
                self.context.sessions.cancel(handle, native_id, timeout=REQUEST_TIMEOUT_SECONDS)
                return

    def _release(self, handle):
        with suppress(PluginError):
            self.context.sessions.release(handle, timeout=REQUEST_TIMEOUT_SECONDS)

    def close(self):
        super().close()
        self.commands.put(('stop', None))
        self.thread.join(timeout=2)
        if not self.thread.is_alive():
            self.lock.unlock()


def create_plugin(context):
    return ScheduledTasksPlugin(context)
