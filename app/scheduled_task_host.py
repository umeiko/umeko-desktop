"""Route built-in timer messages through existing native Widget / Agent Bus paths."""
from collections import OrderedDict
import re
import time
import weakref


class ScheduledTaskHost:
    def __init__(self, host):
        self.host, self.m, self.b = host, host.m, host.b
        self.jobs = OrderedDict()
        self.b._pool.event.connect(self.observe)

    def record(self, source):
        if not isinstance(source, dict):raise ValueError('A captured conversation is required')
        token, identifier = source.get('token'), source.get('id')
        if not isinstance(token, str) or not token or not isinstance(identifier, str):
            raise ValueError('Invalid captured conversation')
        record = self.b._pool.records.get(token)
        if record is None and identifier:
            record = self.b._pool.find(identifier)
            if record is None:
                record = self.m.global_agents.record('session:' + identifier)
        if record is None or record.global_agent or record.workspace != source.get('workspace'):
            raise ValueError('原会话已不存在或工作目录已改变 / Original conversation is unavailable or changed')
        if identifier and record.id != identifier:raise ValueError('Conversation identity changed')
        return record

    def targets(self, record):
        rows = [{'id': 'main', 'name': '主 Agent / Main Agent'}]
        bus = self.m.global_agents
        if bus.active:
            rows += [{'id': 'agent:' + key, 'name': value['name']}
                     for key, value in bus.agents.items() if bus.allowed(record, 'agent:' + key)]
        return rows

    def capture(self, source):
        record = self.record(source)
        return {**source, 'id': record.id, 'token': record.key, 'timerTargets': self.targets(record)}

    @staticmethod
    def identity(record):
        return 'session:' + record.id if record.id else 'draft:' + record.key

    def request(self, request):
        if request['widget'] != 'scheduled-tasks' or not self.m.entries[request['widget']].get('builtin'):
            raise ValueError('Available only to built-in Scheduled Tasks')
        caller = self.record(request['session'])
        operation, args = request['operation'], request['arguments']
        if operation == 'scheduledTasks.targets' and not args:
            return {'targets': self.targets(caller)}
        if operation == 'scheduledTasks.status' and set(args) == {'run_ids'}:
            ids = args['run_ids']
            if not isinstance(ids, list) or len(ids) > 32 or any(not isinstance(key, str) for key in ids):
                raise ValueError('At most 32 run IDs are allowed')
            result = []
            for key in ids:
                job = self.jobs.get(key)
                if not job or job['record']() is not caller and job['owner'] != self.identity(caller):
                    raise ValueError('Timer run does not belong to this conversation')
                job['owner'] = self.identity(caller)
                if job['state'] == 'queued':
                    bus = self.m.global_agents
                    if job.get('bus'):
                        row = bus.requests.get(job['bus'])
                        if not row:job.update(state='failed', detail='Agent Bus request is no longer available')
                        elif row['status'] in ('running', 'completed'):job.update(state='delivered', detail='')
                        elif row['status'] in ('failed', 'cancelled', 'interrupted'):job.update(state='failed', detail=row.get('result', row['status']))
                    if job['state'] == 'queued' and time.monotonic() - job['created'] > 60:
                        job.update(state='failed', detail='投递回执超时；未自动重发 / Delivery receipt timed out; not resent')
                target_record = job['target_record']()
                if target_record:job['session_id'] = target_record.id
                result.append({'id': key, 'state': job['state'], 'detail': job.get('detail', ''),
                               'session_id': job.get('session_id', '')})
            return {'runs': result}
        if operation == 'scheduledTasks.trigger' and set(args) == {'run_id', 'target', 'text'}:
            key, target, text = args['run_id'], args['target'], args['text']
            if not isinstance(key, str) or not re.fullmatch('[a-f0-9]{32}', key):raise ValueError('Invalid timer run ID')
            if not isinstance(text, str) or not text.strip() or len(text) > 8000:raise ValueError('Message must contain 1–8000 characters')
            if target not in {row['id'] for row in self.targets(caller)}:
                raise ValueError('目标未与本会话建立 Agent Bus / Target is not connected to this conversation')
            previous = self.jobs.get(key)
            if previous:
                if previous['record']() is not caller or previous['target'] != target or previous['text'] != text:
                    raise ValueError('Timer run ID is already bound to another request')
                return {'state': previous['state']}
            while len(self.jobs) >= 128:
                old = next((k for k, row in self.jobs.items() if row['state'] != 'queued'), None)
                if old is None:raise ValueError('Timer delivery queue is full')
                self.jobs.pop(old)
            job = {'record': weakref.ref(caller), 'target_record': weakref.ref(caller), 'owner': self.identity(caller), 'target': target, 'text': text,
                   'state': 'queued', 'created': time.monotonic()}
            if target == 'main':
                from .dsh_backend import is_dsh
                if is_dsh(caller):raise ValueError('定时触发暂仅支持 Pi 会话 / Timer delivery currently requires Pi')
                if not caller.busy and sum(record.busy and not record.global_agent for record in self.b._pool.records.values()) >= 8:
                    raise ValueError('原生会话并发已满 / Native session capacity is full')
                notification = {'id': key, 'requestId': '', 'widgetId': 'scheduled-tasks', 'name': '定时任务 / Scheduled Tasks',
                                'message': text, 'wake': True, 'data': {'timerRunId': key}}
                if caller.busy and caller.process and caller.ready:
                    self.b._pool.write(caller, {'type': 'widget-notify', 'notification': notification})
                elif not self.b._command_pi('widget-notify', caller, notification=notification):
                    raise ValueError('目标内核暂不可用 / Target kernel is unavailable')
            else:
                accepted = self.m.global_agents.execute('agent_bus.dispatch', {'targetId': target, 'text': text}, caller)
                job['bus'] = accepted['requestId']
                target_record = self.m.global_agents.records.get(target.removeprefix('agent:'))
                if target_record:job['target_record'] = weakref.ref(target_record)
            self.jobs[key] = job
            return {'state': 'queued', 'source': {key: getattr(caller, field) for key, field in
                    (('token', 'key'), ('id', 'id'), ('workspace', 'workspace'))}}
        if operation == 'scheduledTasks.openTarget' and set(args) == {'target'}:
            if not request['page'] or self.m._page != 'scheduled-tasks':raise ValueError('Open targets from the timer page')
            target = args['target']
            if target not in {row['id'] for row in self.targets(caller)}:raise ValueError('Target is no longer connected')
            if target == 'main':
                if caller.id:self.b.openSession(caller.id)
                else:self.m.closePage()
            else:
                self.m.openPage('global-agents')
                self.m.global_agents.select_conversation(target.removeprefix('agent:'))
            return {}
        raise ValueError('Invalid Scheduled Tasks host arguments')

    def observe(self, record, event):
        if event.get('type') != 'widget_delivery':return
        job = self.jobs.get(event.get('id'))
        if not job or job['record']() is not record or job['state'] != 'queued':return
        if event.get('status') in ('delivered', 'failed'):
            job.update(state=event['status'], detail=str(event.get('error', ''))[:1000])
