"""Explicit user intake and durable task routing over the existing Agent Bus."""
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

from .task_records import current_session_state, timestamp

TERMINAL = {'completed', 'failed', 'cancelled', 'interrupted'}


class TaskRouting:
    def __init__(self, agents):
        self.g = agents
        self.stopped = set()  # Only retains cancellation barriers that could not reach storage.

    def store(self):
        ledger = getattr(self.g.b, '_task_records', None)
        store = ledger._storage() if ledger else None
        if store is None:
            raise ValueError('共享任务记录不可用，未派发任务')
        return store

    def changed(self):
        self.g.changed(persist=False)
        self.g.b._task_records.changed.emit()

    @staticmethod
    def directory(value):
        if not value or not Path(value).is_absolute():
            raise ValueError('实际目录不明；请选择已有会话的绝对目录')
        try:
            path = Path(value).resolve(strict=True)
            if not path.is_dir():
                raise ValueError('执行目录不可用')
            return str(path)
        except (OSError, RuntimeError) as error:
            raise ValueError('执行目录不可用') from error

    def target(self, row, identifier):
        if not identifier.startswith('session:'):
            raise ValueError('只能路由到已有普通执行会话')
        key = identifier.removeprefix('session:')
        info = next((item for item in self.g.b._sessions if item['id'] == key), {})
        if info.get('backend', 'pi') != 'pi':
            raise ValueError('任务入口仅支持已有 Pi 执行会话；未创建替代会话')
        target = self.g.record(identifier)
        if getattr(target, 'backend', 'pi') != 'pi':
            raise ValueError('任务入口仅支持已有 Pi 执行会话；未创建替代会话')
        if target.id and current_session_state(target.id, target.file) != 'available':
            raise ValueError('执行会话历史不可用；未创建替代会话')
        if not self.g.connected(self.g.ensure(row['coordinator']), target):
            raise ValueError('执行会话与协调者没有用户授权的总线连接')
        if self.directory(target.workspace) != self.directory(row['cwd']):
            raise ValueError('执行会话的实际目录与用户选定目录不一致')
        if target.model not in {model['id'] for model in self.g.b.gateway.models()}:
            raise ValueError('执行会话的模型不可用；未创建替代会话')
        return target

    def snapshot(self, args):
        offset = args.get('offset', 0)
        if type(offset) is not int or not 0 <= offset <= 1000000:
            raise ValueError('无效路由页码')
        if args.get('revision') == self.g._revision and args.get('revisionOffset', 0) == offset:
            return {'unchanged': True}
        store = self.store()
        rows = store.routes(offset=offset, limit=21)
        return {'routes': rows[:20], 'hasMore': len(rows) > 20,
                'tasks': store.tasks(limit=100), 'revision': self.g._revision, 'offset':offset}

    def submit(self, args):
        g, store = self.g, self.store()
        key = g.text(args, 'requestKey', 128)
        row = {name:g.text(args, name, maximum, required) for name,maximum,required in (
            ('objective',1000,True), ('scope',4000,True), ('cwd',4096,True),
            ('coordinator',40,True), ('requestedTask',40,False))}
        fingerprint = hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        old = store.route(request_key=key)
        if old:
            if old['fingerprint'] != fingerprint:
                raise ValueError('同一请求身份已用于不同内容；请明确发起新请求')
            return old
        if row['coordinator'] not in g.agents:
            raise ValueError('请选择已有全局子智能体作为协调者')
        source = g.ensure(row['coordinator'])
        if source.busy:
            raise ValueError('协调者正在工作，请稍后提交；本次未创建任务')
        row.update(id=uuid.uuid4().hex, requestKey=key, fingerprint=fingerprint, created=timestamp(),
                   taskId=row['requestedTask'] if row['requestedTask'] != 'new' else '',
                   targetId='', status='routing', execution='not_started', reason='', result='')
        try:
            cwd = self.directory(row['cwd'])
            choices = []
            for candidate in g.overview(source)['targets']:
                if candidate['kind'] == 'session' and candidate.get('canDispatch'):
                    try:
                        target = self.target(row, candidate['id'])
                        choices.append({'id':candidate['id'], 'title':target.title, 'cwd':target.workspace})
                    except ValueError:
                        continue
            if not choices:
                raise ValueError('该目录没有可用且获授权连接的执行会话')
            requested = row['requestedTask']
            if requested and requested != 'new':
                task = store.task(requested)
                if not task or self.directory(task['project']) != cwd:
                    raise ValueError('所选任务不存在或属于其他目录')
                if task['scope'] != row['scope']:
                    self.revise(requested, row['scope'])
            # Persist the restricted role before giving the coordinator any task context.
            g.agents[row['coordinator']]['taskRouter'] = True
            if not g.save():
                raise ValueError('协调模式保存失败，未启动路由')
            store.save_route(row)
            context = {**{key:row[key] for key in ('objective','scope','cwd','requestedTask')},
                       'routeId':row['id'], 'targets':choices,
                       'tasks':[{'taskId':task['id'], 'objective':task['objective'], 'scope':task['scope']}
                                for task in store.tasks(limit=100) if task['project'] == row['cwd']]}
            prompt = ('用户在任务入口明确提交了以下目标与范围。只协调路由，不操作文件或终端。'
                      '调用 agent_bus.route，routeId 必须相同。decision 为 new/continue/clarify/reject；'
                      'new/continue 必须从 targets 选择 targetId，continue 需 taskId。'
                      'requestedTask 为 new 时必须新建，为其他非空值时必须续接该任务。'
                      '关联、目录或目标不明确时必须 clarify，在 reason 中提问。'
                      '不能通过 dispatch 或修改连接绕过任务入口，执行者保留自己的权限与审批。\n' +
                      json.dumps(context, ensure_ascii=False))
            g.handle('send', {'id':row['coordinator'], 'text':prompt})
        except (ValueError, OSError) as error:
            row.update(status='rejected', reason=str(error))
            store.save_route(row)
        self.changed()
        return row

    def decide(self, args, caller):
        g, store = self.g, self.store()
        row = store.route(g.text(args, 'routeId', 40))
        if not row or not caller.global_agent or row['coordinator'] != caller.global_agent:
            raise ValueError('只能处理交给当前真实协调者的入口请求')
        if row['id'] in self.stopped:
            return {**row, 'status':'cancelled', 'reason':'用户已停止此路由'}
        if row['status'] != 'routing':
            return row
        decision = args.get('decision')
        if decision not in ('new','continue','clarify','reject'):
            raise ValueError('decision 必须为 new/continue/clarify/reject')
        reason = g.text(args, 'reason', 2000)
        if decision in ('clarify','reject'):
            row.update(status='clarify' if decision == 'clarify' else 'rejected', reason=reason)
            store.save_route(row)
        else:
            try:
                target_id = g.text(args, 'targetId', 80)
                target = self.target(row, target_id)
                task_id = g.text(args, 'taskId', 40, False)
                requested = row['requestedTask']
                if requested == 'new' and decision != 'new':
                    raise ValueError('用户已明确选择新建任务')
                if requested and requested != 'new' and (decision != 'continue' or task_id != requested):
                    raise ValueError('用户已明确选择续接的 taskId，不可更换关联')
                if decision == 'new' and task_id:
                    raise ValueError('新任务不能携带其他 taskId')
                if decision == 'continue':
                    task = store.task(task_id)
                    if not task or self.directory(task['project']) != self.directory(row['cwd']):
                        raise ValueError('续接任务不存在或属于其他目录')
                    if task['scope'] != row['scope']:
                        row.update(status='clarify', reason='现有任务范围不同；请在入口明确选择该任务并确认新范围')
                        store.save_route(row)
                        self.changed()
                        return row
                    if store.chat_running(task_id):
                        raise ValueError('任务已有正在执行的聊天工作，请先结束该工作')
                g.check_dispatch(caller, target)
                row.update(targetId=target_id, targetTitle=target.title, reason=reason)
                store.accept_route(row, task_id)
                g.dispatch(caller, target, row['objective'], route=row)
                g.save()
            except (ValueError, OSError) as error:
                if row['status'] == 'accepted':
                    row.update(execution='failed', result=str(error), failurePhase='delivery')
                else:
                    row.update(status='rejected', reason=str(error))
                store.save_route(row)
        self.changed()
        return row

    def validate(self, request):
        row = self.store().route(request['id'])
        if not row or row['id'] in self.stopped or row['status'] != 'accepted' or row['execution'] in TERMINAL:
            raise ValueError('任务路由已停止或失效')
        task = self.store().task(row['taskId'])
        if not task or task['scope'] != row['scope']:
            raise ValueError('任务已删除或范围已变化；旧请求不再投递')
        self.target(row, request['target'])

    def execution(self, request, status, result='', phase='execution'):
        if not request.get('taskRoute'):
            return
        store = self.store()
        row = store.route(request['id'])
        if not row or row['execution'] in TERMINAL:
            return
        row.update(execution=status, result=result[:8000], targetId=request['target'])
        if status == 'failed':
            row['failurePhase'] = phase
        store.save_route(row)
        self.changed()

    def cancel(self, identifier):
        store = self.store()
        row = store.route(identifier)
        if not row:
            raise ValueError('任务路由不存在')
        if row['status'] == 'routing':
            row.update(status='cancelled', reason='用户停止了此路由')
        elif row['status'] == 'accepted' and row['execution'] not in TERMINAL:
            row.update(execution='cancelled', result='用户停止了此请求；已执行的操作无法撤销')
        else:
            return row
        self.stopped.add(identifier)
        try:
            store.save_route(row)
            self.stopped.discard(identifier)
        finally:
            request = self.g.requests.get(identifier)
            if request and request['status'] not in TERMINAL:
                self.g.finish(request, 'cancelled', '用户停止了此请求；已执行的操作无法撤销')
            self.g.save()
            self.changed()
        return row

    def revise(self, task_id, scope):
        store = self.store()
        if store.chat_running(task_id):
            raise ValueError('任务有正在执行的聊天工作，请先停止该工作再修改范围')
        rows = store.routes(task_id=task_id, active=True, limit=-1)
        self.stopped.update(row['id'] for row in rows)
        error = None
        for row in rows:
            try:
                self.cancel(row['id'])
            except sqlite3.Error as failure:
                error = failure
        if error:
            raise error
        store.revise_scope(task_id, scope)

    def coordinator_stopped(self, identifier):
        try:
            for row in self.store().routes(coordinator=identifier, active=True, limit=-1):
                self.cancel(row['id'])
        except (ValueError, sqlite3.Error):
            self.g.error = '任务停止状态未能保存；请检查任务记录和执行会话'

    def coordinator_finished(self, record):
        try:
            store = self.store()
            for row in store.routes(coordinator=record.global_agent, active=True, limit=-1):
                if row['status'] == 'routing':
                    row.update(status='rejected' if record.failed else 'clarify',
                               reason='协调者未返回结构化路由；请明确选择任务关联和目录后重试')
                    store.save_route(row)
            self.changed()
        except (ValueError, sqlite3.Error):
            self.g.error = '无法保存协调结果，未重新派发'

    def execute(self, operation, args, caller):
        try:
            if operation == 'agent_bus.routes':
                if args:
                    raise ValueError('未知任务路由参数')
                return {'routes':self.store().routes(coordinator=caller.global_agent)} if caller.global_agent else {'routes':[]}
            if set(args) - {'routeId','decision','taskId','targetId','reason'}:
                raise ValueError('未知任务路由参数')
            return self.decide(args, caller)
        except sqlite3.Error as error:
            raise ValueError('共享任务记录保存失败，未重发请求') from error
