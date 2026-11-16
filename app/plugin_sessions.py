"""Application Widget sessions: durable identities, targeted runs and approvals.

Pi owns native transcripts and execution; PiSessionPool retains its usual idle
policy. This service never activates a desktop view. Profiles are desktop-owned
settings, not plugin configuration or message parameters.
"""
from __future__ import annotations

import copy
import json
import threading
import time
import uuid
from collections import deque
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from .pi_sessions import SessionState


OPERATIONS = frozenset(('sessions.acquire', 'sessions.submit', 'sessions.subscribe',
    'sessions.wait', 'sessions.cancel', 'sessions.history', 'sessions.release',
    'approvals.registerHandler', 'approvals.respond'))
APPROVAL_GRACE_MS = 5000
APPROVAL_TIMEOUT_MS = 120000


def session_policy(backend, record):
    """Resolve only desktop-approved values, including on cold process restart."""
    owner = backend.store.data.get('sessionMeta', {}).get(record.id, {}).get('pluginSession')
    if not owner:
        return None
    profile = backend.store.data.get('pluginSessionProfiles', {}).get(owner['plugin'], {}).get(owner['profile'])
    if not isinstance(profile, dict):
        raise ValueError('The desktop session profile is no longer available')
    workspace = profile.get('workspace')
    if not isinstance(workspace, str) or not Path(workspace).is_absolute() or not Path(workspace).is_dir():
        raise ValueError('The profile workspace must be an existing absolute directory')
    workspace = str(Path(workspace).resolve())
    if record.file and Path(record.workspace).resolve() != Path(workspace):
        raise ValueError('The profile workspace changed; acquire a new external key')
    model = profile.get('model')
    if not isinstance(model, str) or not model or not any(row.get('id') == model for row in backend.gateway.models()):
        raise ValueError('The profile must name an existing desktop model')
    provider = profile.get('provider') or ''
    if not isinstance(provider, str):
        raise ValueError('The profile provider must be a configured Provider ID')
    resolved, _ = backend.gateway.resolve(model, provider or None)
    routed, _ = backend.gateway.resolve(model)
    if resolved['id'] != routed['id']:
        raise ValueError('Use a unique desktop model alias for this profile provider')
    tools = profile.get('tools', [])
    if not isinstance(tools, list) or any(not isinstance(name, str) or not name or len(name) > 256 for name in tools):
        raise ValueError('The profile tools must be exact tool names')
    if set(tools) & {'umeko_desktop', 'pi', 'pi_commands'}:
        raise ValueError('Desktop administration tools cannot be enabled in plugin session profiles')
    mode = profile.get('permissionMode', 'ask')
    if mode not in ('ask', 'auto'):
        raise ValueError('The profile permissionMode must be ask or auto')
    # Neither a plugin nor a later queued turn may weaken the desktop mode.
    if backend.store.data['agent'].get('toolPermissionMode') == 'ask':
        mode = 'ask'
    return {'workspace': workspace, 'model': model, 'provider': resolved['id'],
        'allowedTools': list(dict.fromkeys(tools)), 'mode': mode,
        'allowApprovals': profile.get('allowApprovals') is True}


def profile_rows(backend):
    """Existing plugin session profiles with the model route each one uses."""
    profiles = backend.store.data.get('pluginSessionProfiles', {})
    entries = getattr(getattr(backend, '_desktop_plugins', None), 'entries', {})
    rows = []
    for plugin, named in sorted(profiles.items() if isinstance(profiles, dict) else []):
        for profile, value in sorted(named.items() if isinstance(named, dict) else []):
            if isinstance(value, dict):
                rows.append({'plugin': plugin, 'profile': profile,
                    'pluginName': str(entries.get(plugin, {}).get('name') or plugin),
                    'model': value.get('model') if isinstance(value.get('model'), str) else '',
                    'provider': value.get('provider') if isinstance(value.get('provider'), str) else ''})
    return rows


def set_profile_model(backend, plugin, profile, model, provider=''):
    """Change the model route of an existing profile and nothing else.

    Workspace, tools, permission mode and approvals stay as the user approved
    them. Sessions pick up the new route at their next input boundary.
    """
    backend.store.save()  # Read in pending external edits before changing the profile.
    profiles = backend.store.data.get('pluginSessionProfiles', {})
    named = profiles.get(plugin) if isinstance(profiles, dict) and isinstance(plugin, str) else None
    target = named.get(profile) if isinstance(named, dict) and isinstance(profile, str) else None
    if not isinstance(target, dict):
        raise ValueError('插件会话配置不存在，请先在 settings.json 中添加')
    if not isinstance(model, str) or not model or not any(row.get('id') == model for row in backend.gateway.models()):
        raise ValueError('请选择已配置的桌面模型别名')
    if not isinstance(provider, str) or provider and backend.gateway.provider(provider) is None:
        raise ValueError('供应商 ID 不存在')
    resolved, _ = backend.gateway.resolve(model, provider or None)
    routed, _ = backend.gateway.resolve(model)
    if resolved['id'] != routed['id']:
        raise ValueError('该模型别名在多个供应商中重复，请使用唯一的模型别名')
    previous = {key: target[key] for key in ('model', 'provider') if key in target}
    target.update(model=model, provider=resolved['id'])
    try:
        backend.store.save()
    except (OSError, RuntimeError):
        for key in ('model', 'provider'):
            target.pop(key, None)
        target.update(previous)
        raise
    return {'plugin': plugin, 'profile': profile, 'model': model, 'provider': resolved['id']}


def apply_session_policy(backend, record):
    policy = session_policy(backend, record)
    if policy:
        previous = getattr(record, '_plugin_policy', None)
        if record.busy:
            return policy  # Apply a changed ceiling at the next input boundary.
        if record.process and previous != policy and not record.busy and not record.subagents_active:
            backend._pool.retire(record)
        record.workspace, record.model, record.provider = policy['workspace'], policy['model'], policy['provider']
        record._plugin_policy = policy
    return policy


class PluginSessions(QObject):
    historyReady = Signal(object, object)

    def __init__(self, host):
        super().__init__(host)
        self.host, self.m, self.b = host, host.m, host.b
        self.handles = {}
        self.pending_acquires = {}
        self.acquiring = {}
        self.queues = {}
        self.active = {}
        self.runs = {}
        self.approvals = {}
        self.historyReady.connect(lambda request, result: self.host._reply(request, result))
        self.b._pool.event.connect(self.observe)

    def _reply(self, request, result=None, error=None):
        self.host._reply(request, {'ok': error is None, **({'error': str(error)} if error is not None else {'result': result})})

    def _owner(self, request, handle):
        if not isinstance(handle, str):
            raise ValueError('A session handle is required')
        lease = self.handles.get(handle)
        if not lease or lease['plugin'] != request['widget'] or lease['worker'] is not request['worker']:
            raise ValueError('Session handle does not belong to this plugin instance')
        record = lease['record']
        meta = self.b.store.data['sessionMeta'].get(record.id, {})
        if meta.get('archived') or not meta.get('pluginSession'):
            raise ValueError('The acquired session is no longer available')
        return lease

    def _event(self, record, kind, run_id='', **values):
        for handle, lease in list(self.handles.items()):
            if lease['record'] is record and (lease['subscribed'] or kind == 'approval_request' and lease['handler']):
                if self.m.workers.get(lease['plugin']) is not lease['worker']:
                    continue
                data = {'handle': handle, 'sessionId': record.id, 'runId': run_id, 'type': kind, **values}
                self.m.send(lease['plugin'], {'id': uuid.uuid4().hex, 'operation': 'event',
                    'arguments': {'name': 'sessions.event', 'data': data}})

    def _lease(self, request, record, created):
        if self.m.workers.get(request['widget']) is not request['worker']:
            return
        handle = uuid.uuid4().hex
        self.handles[handle] = {'plugin': request['widget'], 'worker': request['worker'],
            'record': record, 'subscribed': False, 'handler': False}
        self._reply(request, {'handle': handle, 'sessionId': record.id, 'created': created})

    def request(self, request):
        operation, args = request['operation'], request['arguments']
        fields = {
            'sessions.acquire': {'namespace', 'externalKey', 'createIfMissing', 'profile'},
            'sessions.submit': {'handle', 'requestId', 'content'}, 'sessions.subscribe': {'handle'},
            'sessions.wait': {'handle', 'runId'}, 'sessions.cancel': {'handle', 'runId'},
            'sessions.history': {'handle', 'limit'}, 'sessions.release': {'handle'},
            'approvals.registerHandler': {'handle'}, 'approvals.respond': {'handle', 'requestId', 'decision'}}[operation]
        if set(args) - fields:
            raise ValueError('Unknown session service arguments')
        if operation == 'sessions.acquire':
            self.acquire(request)
            return
        lease = self._owner(request, args.get('handle'))
        record = lease['record']
        if operation == 'sessions.submit':
            content, request_id = args.get('content'), args.get('requestId')
            if not isinstance(content, str) or not content.strip() or not isinstance(request_id, str) or not 0 < len(request_id) <= 256:
                raise ValueError('A requestId and nonempty text content are required')
            existing = next((run for run in self.runs.values() if run['record'] is record and run['requestId'] == request_id), None)
            if existing:
                self._reply(request, {'runId': existing['runId'], 'disposition': existing['disposition']})
                return
            apply_session_policy(self.b, record)
            queued = record.busy or record.key in self.active or bool(self.queues.get(record.key))
            run_id = uuid.uuid4().hex
            run = {'runId': run_id, 'requestId': request_id, 'record': record, 'content': content,
                'disposition': 'queued' if queued else 'started', 'status': 'queued',
                'assistantMessages': [], 'waiters': [], 'error': ''}
            self.runs[run_id] = run
            self.queues.setdefault(record.key, deque()).append(run_id)
            self._reply(request, {'runId': run_id, 'disposition': run['disposition']})
            self._next(record)
        elif operation == 'sessions.subscribe':
            lease['subscribed'] = True
            self._reply(request, {'subscribed': True})
        elif operation == 'sessions.wait':
            run = self.runs.get(args.get('runId'))
            if not run or run['record'] is not record:
                raise ValueError('The run does not belong to this session')
            if run['status'] in ('completed', 'failed', 'cancelled'):
                self._reply(request, self._result(run))
            else:
                run['waiters'].append(request)
        elif operation == 'sessions.cancel':
            identifier = args.get('runId')
            if identifier and (identifier not in self.runs or self.runs[identifier]['record'] is not record):
                raise ValueError('The run does not belong to this session')
            self.cancel(record, identifier)
            self._reply(request, {'cancelled': True})
        elif operation == 'sessions.history':
            limit = args.get('limit', 50)
            if type(limit) is not int or not 1 <= limit <= 200:
                raise ValueError('limit must be from 1 to 200')
            file, fallback = record.file, copy.deepcopy(record.messages)
            def read():
                from .transcripts import preview
                messages = preview(file)[0] if file and Path(file).is_file() else fallback
                rows = messages[-limit:]
                truncated = len(messages) > limit
                # Retain valid bounded responses even for a single huge message.
                while rows and len(json.dumps(rows, ensure_ascii=False).encode()) > 240000:
                    rows = rows[1:]; truncated = True
                return {'sessionId': record.id, 'messages': rows, 'truncated': truncated}
            def work():
                try: result = {'ok': True, 'result': read()}
                except (OSError, ValueError) as error: result = {'ok': False, 'error': str(error)}
                self.historyReady.emit(request, result)
            threading.Thread(target=work, daemon=True).start()
        elif operation == 'sessions.release':
            self.handles.pop(args['handle'])
            self._reply(request, {'released': True})
            self.b._pool.trim()
        elif operation == 'approvals.registerHandler':
            if not session_policy(self.b, record)['allowApprovals']:
                raise ValueError('The desktop profile does not allow plugin approval handling')
            lease['handler'] = True
            self._reply(request, {'registered': True})
        elif operation == 'approvals.respond':
            approval = self.approvals.get(args.get('requestId'))
            decision = args.get('decision')
            if decision not in ('allow', 'deny', 'unhandled'):
                raise ValueError('decision must be allow, deny or unhandled')
            if approval and time.monotonic() >= approval['expires']:
                self._answer(args['requestId'], False)
                approval = None
            elif approval and time.monotonic() >= approval['handlerExpires']:
                self._fallback(args['requestId'])
            accepted = bool(approval and approval['record'] is record and lease['handler'] and
                args['handle'] in approval['handlers'] and not approval['desktop'] and
                session_policy(self.b, record)['allowApprovals'])
            if accepted:
                if decision == 'unhandled':
                    approval['handlers'].discard(args['handle'])
                    if not approval['handlers']: self._fallback(args['requestId'])
                else:
                    self._answer(args['requestId'], decision == 'allow')
            self._reply(request, {'accepted': accepted})

    def acquire(self, request):
        args, plugin = request['arguments'], request['widget']
        namespace, key, profile = args.get('namespace', 'default'), args.get('externalKey'), args.get('profile')
        if any(not isinstance(v, str) or not 0 < len(v) <= 512 for v in (namespace, key, profile)):
            raise ValueError('namespace, externalKey and a desktop profile name are required')
        if type(args.get('createIfMissing', True)) is not bool:
            raise ValueError('createIfMissing must be boolean')
        identity = json.dumps([plugin, namespace, key], ensure_ascii=False)
        bindings = self.b.store.data.setdefault('pluginSessions', {})
        binding = bindings.get(identity)
        if binding:
            if binding['profile'] != profile:
                raise ValueError('This external key is bound to another profile')
            session_id = binding['sessionId']
            meta = self.b.store.data['sessionMeta'].get(session_id, {})
            if meta.get('archived') or not meta.get('pluginSession') or not Path(binding['file']).is_file():
                raise ValueError('The mapped native session was removed or archived')
            record = self.b._pool.find(session_id)
            if record is None:
                record = SessionState(id=session_id, file=binding['file'], workspace=binding['workspace'],
                    model=binding['model'], provider=binding.get('provider', ''), title=binding.get('title', 'Plugin session'), loaded=False)
            apply_session_policy(self.b, record)
            self.b._pool.touch(record)
            self._lease(request, record, False)
            return
        if not args.get('createIfMissing', True):
            raise ValueError('No session is mapped to this external key')
        if identity in self.acquiring:
            self.pending_acquires[self.acquiring[identity]].append(request)
            return
        record = SessionState(title='Plugin session')
        record.id = 'plugin-pending-' + record.key
        owner = {'plugin': plugin, 'namespace': namespace, 'externalKey': key, 'profile': profile}
        self.b.store.data['sessionMeta'][record.id] = {'pluginSession': owner}
        try:
            apply_session_policy(self.b, record)
        except (ValueError, OSError):
            self.b.store.data['sessionMeta'].pop(record.id, None)
            raise
        self.pending_acquires[record.key] = [request]
        self.acquiring[identity] = record.key
        record._plugin_identity = identity
        self.b._pool.touch(record)
        if not self.b._command_pi('plugin-session-acquire', record):
            self._acquire_done(record, 'The native session could not be created')

    def _acquire_done(self, record, error=None):
        requests = self.pending_acquires.pop(record.key, [])
        identity = getattr(record, '_plugin_identity', '')
        self.acquiring.pop(identity, None)
        if not error and (not record.id or record.id.startswith('plugin-pending-') or not record.file or not Path(record.file).is_file()):
            error = 'Pi did not persist a native session'
        if error:
            for request in requests: self._reply(request, error=error)
            return
        owner = self.b.store.data['sessionMeta'][record.id]['pluginSession']
        self.b.store.data['pluginSessions'][identity] = {**owner, 'sessionId': record.id,
            'file': record.file, 'workspace': record.workspace, 'model': record.model,
            'provider': record.provider, 'title': record.title}
        try:
            self.b._index_record(record)
            self.b._save_session()
            self.b.store.save()
        except OSError as error:
            for request in requests: self._reply(request, error=error)
            return
        for index, request in enumerate(requests): self._lease(request, record, index == 0)

    @staticmethod
    def _result(run):
        return {key: copy.deepcopy(run[key]) for key in ('runId', 'status', 'assistantMessages', 'error')}

    def _next(self, record):
        queue = self.queues.get(record.key)
        if not queue or record.busy or record.key in self.active:
            return
        run = self.runs[queue.popleft()]
        self.active[record.key] = run['runId']
        run['status'] = 'running'
        try:
            apply_session_policy(self.b, record)
            if not self.b._command_pi('prompt', record, text=run['content'], images=[]):
                raise ValueError('The session could not start this input')
        except (OSError, ValueError) as error:
            self._finish(run, 'failed', str(error))

    def _finish(self, run, status, error=''):
        if run['status'] in ('completed', 'failed', 'cancelled'): return
        record = run['record']
        if self.active.get(record.key) == run['runId']: self.active.pop(record.key)
        run['status'], run['error'] = status, error or run['error']
        result = self._result(run)
        self._event(record, 'turn_end', run['runId'], **{k: v for k, v in result.items() if k != 'runId'})
        for request in run['waiters']: self._reply(request, result)
        run['waiters'].clear()
        QTimer.singleShot(0, self, lambda: self._next(record))

    def cancel(self, record, run_id=None):
        queue = self.queues.get(record.key, deque())
        for identifier in list(queue):
            if run_id is None or identifier == run_id:
                queue.remove(identifier)
                self._finish(self.runs[identifier], 'cancelled')
        active = self.runs.get(self.active.get(record.key))
        stopping = active and (run_id is None or active['runId'] == run_id)
        if stopping:
            active['cancelling'] = True
            record.cancelled = True
            self.b._pool.write(record, {'type': 'abort'})
        for identifier, pending in list(self.approvals.items()):
            if pending['record'] is record and (stopping or run_id is None): self._answer(identifier, False)

    def approval(self, record, event):
        """Called before the ordinary controller publishes its desktop dialog."""
        if not self.b.store.data['sessionMeta'].get(record.id, {}).get('pluginSession'):
            return False
        identifier = event['id']
        handlers = {handle for handle, lease in self.handles.items() if lease['record'] is record and lease['handler']
            and self.m.workers.get(lease['plugin']) is lease['worker']}
        # Non-confirm dialogs remain desktop-only, with the same deny timeout.
        if event.get('method') != 'confirm' or not session_policy(self.b, record)['allowApprovals']:
            handlers.clear()
        grace, deadline = QTimer(self), QTimer(self)
        for timer in (grace, deadline): timer.setSingleShot(True)
        pending = {'record': record, 'event': copy.deepcopy(event), 'handlers': handlers,
            'desktop': not bool(handlers), 'grace': grace, 'deadline': deadline,
            'expires': time.monotonic() + APPROVAL_TIMEOUT_MS / 1000,
            'handlerExpires': time.monotonic() + APPROVAL_GRACE_MS / 1000}
        self.approvals[identifier] = pending
        grace.timeout.connect(lambda: self._fallback(identifier))
        deadline.timeout.connect(lambda: self._answer(identifier, False))
        deadline.start(APPROVAL_TIMEOUT_MS)
        if handlers:
            grace.start(APPROVAL_GRACE_MS)
            self._event(record, 'approval_request', self.active.get(record.key, ''), requestId=identifier,
                approval=copy.deepcopy(event), timeoutMs=APPROVAL_TIMEOUT_MS)
        return bool(handlers)

    def _fallback(self, identifier):
        pending = self.approvals.get(identifier)
        if not pending or pending['desktop']: return
        pending['desktop'] = True
        pending['grace'].stop()
        record = pending['record']
        record.approval = pending['event']
        self.b.approvalChanged.emit()
        self.b.chatChanged.emit()

    def _answer(self, identifier, allowed):
        pending = self.approvals.pop(identifier, None)
        if not pending: return False
        for name in ('grace', 'deadline'):
            pending[name].stop(); pending[name].deleteLater()
        record = pending['record']
        if record.approval.get('id') == identifier: record.approval = {}
        self.b._pool.write(record, {'type': 'ui_response', 'id': identifier,
            'value': allowed is True and time.monotonic() < pending['expires']})
        self.b.approvalChanged.emit()
        return True

    def desktop_answer(self, record, identifier, value):
        pending = self.approvals.get(identifier)
        if pending and pending['record'] is record and pending['desktop']:
            return self._answer(identifier, value is True)
        return False

    def observe(self, record, event):
        kind = event.get('type')
        if kind in ('done', 'exit') and record.key in self.pending_acquires:
            self._acquire_done(record, event.get('message', 'Native session initialization failed') if kind == 'exit' or record.failed else None)
        run = self.runs.get(self.active.get(record.key))
        if run:
            if kind == 'delta': self._event(record, 'stream_delta', run['runId'], text=event.get('text', ''))
            elif kind == 'message' and event.get('role') == 'assistant':
                run['assistantMessages'].append(event.get('text', ''))
                if event.get('error'): run['error'] = event['error']
                self._event(record, 'assistant_text', run['runId'], text=event.get('text', ''), stopReason=event.get('stopReason', ''))
            elif kind == 'tool':
                self._event(record, 'tool_result' if event.get('state') in ('done', 'error') else 'tool_call', run['runId'], tool=copy.deepcopy(event))
            elif kind == 'error':
                run['error'] = event.get('message', 'Native session failed')
                self._event(record, 'error', run['runId'], message=run['error'])
            elif kind in ('done', 'exit'):
                status = 'cancelled' if run.get('cancelling') or record.cancelled else 'failed' if kind == 'exit' or record.failed or run['error'] else 'completed'
                self._finish(run, status, event.get('message', '') if kind == 'exit' else '')
        if kind in ('done', 'exit'):
            for identifier, pending in list(self.approvals.items()):
                if pending['record'] is record: self._answer(identifier, False)
            QTimer.singleShot(0, self, lambda: self._next(record))

    def stop(self, plugin):
        records = set()
        for handle, lease in list(self.handles.items()):
            if lease['plugin'] == plugin:
                records.add(lease['record']); self.handles.pop(handle)
        awaiting = set()
        for identifier, pending in list(self.approvals.items()):
            if pending['record'] in records:
                awaiting.add(pending['record'])
                self._fallback(identifier)
        for record in records:
            if record in awaiting:
                # Losing the plugin responder must preserve desktop fallback,
                # rather than aborting the very request the user can answer.
                for run_id in list(self.queues.get(record.key, ())):
                    self.cancel(record, run_id)
            else:
                self.cancel(record)
