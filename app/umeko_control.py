"""The Agent's allowlisted desktop API. All mutations use live UI controllers."""
from __future__ import annotations

import copy
import json
import math
import re
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl


def redacted(value):
    if isinstance(value, list):
        return [redacted(item) for item in value]
    if isinstance(value, dict):
        def sensitive(key, item):
            name = re.sub(r'[^a-z]', '', key.lower())
            return isinstance(item, (str, dict, list)) and bool(item) and not name.startswith('has') and (
                name in ('key', 'token', 'credentials', 'authorization') or name.endswith(('password', 'secret', 'apikey', 'accesstoken', 'refreshtoken', 'bearertoken')))
        output = {}
        for key, item in value.items():
            if key == 'fields' and isinstance(item, list):
                output[key] = [{name: ('[redacted]' if field.get('secret') and name == 'value' and datum else
                                      copy.deepcopy(datum) if name in ('key', 'type', 'secret') else redacted(datum))
                                for name, datum in field.items()} if isinstance(field, dict) else redacted(field)
                               for field in item]
            else:
                output[key] = '[redacted]' if sensitive(key, item) else redacted(item)
        return output
    return value


class UmekoControl(QObject):
    def __init__(self, backend):
        super().__init__(backend)
        self.b = backend
        self.operations = json.loads((backend.root/'runtime/umeko-operations.json').read_text(encoding='utf-8'))['operations']
        self.operations = {name: spec for name, spec in self.operations.items() if 'python' in spec.get('editions', ['python'])}
        self.jobs = {}
        self._dispatching = None
        self._workers = {}
        self._native = {}
        self._plugins = {}
        backend.jobStarted.connect(self._job_started)
        backend.jobDone.connect(self._job_finished)
        backend.piCommandStarted.connect(self._native_started)
        backend._pool.event.connect(self._native_event)
        backend.providerPlugins.finished.connect(self._plugin_finished)
        backend.piManagement.operationFinished.connect(self._management_finished)
        backend.appAbout.updater.changed.connect(self._installation_changed)
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self._drain)

    def _sessions(self):
        rows = []
        for source in self.b._sessions:
            row = {key: source.get(key, '') for key in ('id', 'title', 'file', 'workspace', 'model', 'provider')}
            row.update(self.b.store.data.get('sessionMeta', {}).get(row['id'], {}))
            record = self.b._pool.find(row['id'])
            row['running'] = bool(record and record.busy)
            rows.append(row)
        return rows

    def _caller(self, key):
        return self.b._pool.records.get(key)

    def _blocked(self, spec, args, caller):
        records = list(self.b._pool.records.values())
        mode = spec.get('idle')
        if spec.get('target') == 'management' and (self.b.piManagement.busy or self.b.kernelBusy): return True
        if spec.get('method') == 'checkKernel' and (self.b._view.busy or self.b.kernelBusy): return True
        if mode == 'all' and (any(r.busy for r in records) or self.b.piManagement.busy or self.b.kernelBusy): return True
        if mode == 'view' and (self.b._view.busy or caller and caller.busy): return True
        if mode == 'provider' and args.get('id'):
            return self.b._models_busy(args['id']) or args['id'] in self.b.providerPlugins.busy
        if mode == 'session':
            record = self.b._pool.find(args['id'])
            return bool(record and record.busy or args['id'] in self.b._management_jobs)
        return False

    def _new_job(self, operation, status):
        while len(self.jobs) >= 128:
            completed = next((key for key, job in self.jobs.items() if job['status'] in ('done', 'failed')), None)
            if completed is None: break
            del self.jobs[completed]
        identifier = uuid.uuid4().hex
        self.jobs[identifier] = {'operation': operation, 'created': time.monotonic(), 'status': status, 'pending': set()}
        return identifier

    def _queue(self, operation, args, caller):
        if sum(job['status'] == 'queued' for job in self.jobs.values()) >= 32:
            raise ValueError('Too many pending Umeko changes; wait for existing jobs')
        identifier = self._new_job(operation, 'queued')
        self.jobs[identifier].update(arguments=copy.deepcopy(args), caller=caller.key if caller else '')
        self.timer.start()
        return {'ok': True, 'status': 'queued', 'jobId': identifier,
                'message': '等待相关任务结束后应用；使用 jobs.get 查看结果。'}

    def _drain(self):
        if self.b._closing:
            self.timer.stop(); return
        for identifier, job in list(self.jobs.items()):
            if job['status'] != 'queued': continue
            caller = self._caller(job['caller'])
            if time.monotonic() - job['created'] > 600:
                self._finish(identifier, {'ok': False, 'error': 'Timed out waiting for an idle desktop task'})
                continue
            spec = self.operations.get(job['operation'], {'idle': 'all'})
            if self._blocked(spec, job['arguments'], caller): break
            job['status'] = 'running'
            result = self.execute({'operation': job['operation'], 'arguments': job['arguments']}, caller, queue=False, _job_id=identifier)
            job.pop('arguments', None)
            if not result['ok'] or result.get('status') != 'accepted': self._finish(identifier, result)
            self.b.toast.emit(('Umeko 配置任务已开始' if job['status'] == 'running' else 'Umeko 配置任务已应用') if result['ok'] else 'Umeko 配置任务失败：' + result.get('error', ''))
        if not any(job['status'] == 'queued' for job in self.jobs.values()): self.timer.stop()

    def _finish(self, identifier, result):
        job = self.jobs[identifier]
        job.update(status='done' if result.get('ok') else 'failed', result=redacted(result))
        job.pop('arguments', None)
        job['pending'].clear()

    def _observe(self, identifier, token):
        self.jobs[identifier]['pending'].add(token)

    def _completed(self, identifier, token, result):
        job = self.jobs.get(identifier)
        if not job or job['status'] != 'running': return
        job['pending'].discard(token)
        if not result.get('ok') or not job['pending']: self._finish(identifier, result)

    def _job_started(self, name):
        if self._dispatching is None: return
        identifier = self._dispatching
        self._workers.setdefault(name, []).append(identifier)
        self._observe(identifier, ('worker', name))

    def _job_finished(self, name, result):
        if name.startswith('pi-admin:'): return  # Wait for management's apply result.
        self._worker_finished(name, result)

    def _worker_finished(self, name, result):
        identifiers = self._workers.get(name, [])
        if not identifiers: return
        identifier = identifiers.pop(0)
        if not identifiers: self._workers.pop(name, None)
        value = result.get('value')
        ok = bool(result.get('ok')) and not (isinstance(value, dict) and value.get('state') == 'error')
        final = {'ok': ok, 'value': value} if ok else {'ok': False, 'error': str(value.get('message', value) if isinstance(value, dict) else value)}
        self._completed(identifier, ('worker', name), final)

    def _management_finished(self, name, result):
        self._worker_finished(name, result)

    def _native_started(self, record, action):
        if self._dispatching is None: return
        identifier = self._dispatching
        self._native[record.key] = (identifier, action)
        self._observe(identifier, ('native', record.key))

    def _native_event(self, record, event):
        pending = self._native.get(record.key)
        if pending is None: return
        identifier, action = pending
        job = self.jobs[identifier]
        kind = event.get('type')
        if kind in ('resources', 'state') and 'resources' in event:
            job['resources'] = redacted(event['resources'])
        if kind not in ('done', 'exit', 'error'): return
        self._native.pop(record.key, None)
        ok = kind == 'done' and not record.failed and not record.cancelled
        result = {'ok': ok, 'action': action}
        if 'resources' in job: result['resources'] = job.pop('resources')
        if not ok: result['error'] = event.get('message') or ('Pi operation was cancelled' if record.cancelled else 'Pi operation failed or exited before completion')
        self._completed(identifier, ('native', record.key), result)

    def _plugin_finished(self, provider_id, payload):
        identifier = self._plugins.pop(provider_id, None)
        if identifier is None: return
        result = {'ok': False, 'error': payload['error']} if 'error' in payload else {'ok': True, 'value': payload.get('result')}
        self._completed(identifier, ('plugin', provider_id), result)

    def _installation_changed(self, value):
        identifier = self._dispatching
        if identifier is None:
            identifier = next((key for key, job in self.jobs.items() if job['status'] == 'running' and job['operation'] == 'updates.install'), None)
        if identifier is None or self.jobs[identifier]['operation'] != 'updates.install': return
        self._observe(identifier, ('installation', 'update'))
        if value.get('state') == 'error' or value.get('busy') is False:
            self._completed(identifier, ('installation', 'update'), {'ok': value.get('state') != 'error', 'value': value, **({'error': value.get('message', 'Update installation failed')} if value.get('state') == 'error' else {})})

    def execute(self, request, caller=None, queue=True, _job_id=None):
        try:
            if not isinstance(request, dict) or set(request) - {'operation', 'arguments'}: raise ValueError('Expected operation and arguments')
            operation = request.get('operation')
            args = request.get('arguments', {})
            if not isinstance(operation, str) or not isinstance(args, dict): raise ValueError('Invalid desktop request')
            if len(json.dumps(args)) > 2 * 1024 * 1024: raise ValueError('Desktop arguments exceed 2 MiB')
            result = self._execute(operation, args, caller, queue, _job_id)
            return {'ok': True, 'operation': operation, **result}
        except Exception as error:
            result = {'ok': False, 'status': 'failed', 'operation': request.get('operation', '') if isinstance(request, dict) else '', 'error': str(error)}
            if _job_id is not None:
                self._finish(_job_id, result)
                result['jobId'] = _job_id
            return result

    def _execute(self, operation, args, caller, queue, job_id=None):
        b = self.b
        if operation == 'help':
            docs = b.store.directory/'agent-docs'
            if not (docs/'README.md').is_file(): docs = b._release/'umeko-docs'
            return {'docsRoot': str(docs), 'entry': str(docs/'README.md')}
        if operation == 'operations.list':
            prefix = args.get('prefix', '')
            return {'operations': {name: spec for name, spec in self.operations.items() if name.startswith(prefix)},
                    'reads': ['settings.get', 'providers.list', 'models.list', 'characters.list', 'characters.get', 'characters.config', 'plugins.list', 'plugins.getConfig', 'themes.list', 'projects.list', 'sessions.list', 'sessions.get', 'mcp.get', 'status.get', 'jobs.get']}
        if operation == 'batch':
            operations = args.get('operations')
            if not isinstance(operations, list) or not 1 <= len(operations) <= 32: raise ValueError('batch needs 1-32 operations')
            if any(item.get('operation') == 'batch' for item in operations if isinstance(item, dict)): raise ValueError('Nested batches are not supported')
            results = [self.execute(item, caller, queue) for item in operations]
            return {'ok': all(item['ok'] for item in results), 'results': results}
        if operation == 'settings.get':
            settings = b.config
            settings.pop('sessionMeta', None)
            return {'config': redacted(settings), 'activeSession': b.activeSession, 'callerSession': caller.id if caller else ''}
        if operation == 'providers.list': return {'providers': redacted(b.config['providers']), 'presets': b.commonProviders}
        if operation == 'models.list':
            return {'models': [dict(model='umeko/'+row['id'], id=row['id'], provider='umeko', displayProvider=row.get('owned_by', 'Umeko'), contextWindow=row['contextWindow'], vision='image' in row['input'])
                               for row in b.gateway.models()]}
        if operation == 'characters.list': return {'selected': b.characterStyle['id'], 'characters': b.characterPacks}
        if operation == 'characters.get': return {'character': b.characterStyle}
        if operation == 'characters.config': return {'path':str(b.store.directory/'character-config.json'), 'config':copy.deepcopy(b._character_config), 'overrides':copy.deepcopy(b._character_options)}
        if operation == 'plugins.list': return {'accounts': redacted(b.providerPlugins.rows), 'packages': b.providerPlugins.packages}
        if operation == 'plugins.resource':
            kind = args.get('kind')
            if kind not in ('sdk', 'develop'): raise ValueError('kind must be sdk or develop')
            name = 'umeko-provider-sdk-0.2.1.zip' if kind == 'sdk' else 'develop-umeko-provider.zip'
            path = next((folder/name for folder in (b.root/'provider-resources', b.root/'build/provider-resources') if (folder/name).is_file()), None)
            if path is None: raise ValueError('Bundled provider development resource is missing')
            return {'path': str(path.resolve())}
        if operation == 'plugins.getConfig':
            b.providerPlugins._record(args.get('id'))
            return {'config': redacted(json.loads(b.providerPlugins.configJson(args['id'])))}
        if operation == 'themes.list': return {'selected': b.config['theme'], 'themes': b.customThemes, 'builtins': ['light', 'dark', 'yanami']}
        if operation == 'themes.prompt': return {'prompt': (b.root/'app/theme-prompt.txt').read_text(encoding='utf-8')}
        if operation == 'appearance.fonts': return {'fonts': b.availableFonts}
        if operation == 'projects.list': return {'projects': copy.deepcopy(b.store.data['projects'])}
        if operation == 'sessions.list':
            offset, limit = int(args.get('offset', 0)), int(args.get('limit', 100))
            if offset < 0 or not 1 <= limit <= 200: raise ValueError('offset >= 0; limit 1-200')
            rows = self._sessions()
            if args.get('workspace'): rows = [r for r in rows if r['workspace'] == args['workspace']]
            return {'sessions': rows[offset:offset+limit], 'total': len(rows)}
        if operation == 'sessions.get':
            identifier = args.get('id') or (caller.id if caller else b.activeSession)
            row = next((row for row in self._sessions() if row['id'] == identifier), None)
            if row is None: raise ValueError('Session ID does not exist')
            return {'session': row}
        if operation == 'mcp.get': return {'path': b.mcpConfigPath(args.get('scope', 'global')), 'config': redacted(json.loads(b.readMcp(args.get('scope', 'global'))))}
        if operation == 'status.get':
            return {'lastSendError': b.lastSendError,
                    'kernel': {'busy': b.kernelBusy, 'status': b.kernelStatus, 'version': b.kernelVersion},
                    'management': {'busy': b.piManagement.busy, 'status': b.piManagement.status, 'extensions': b.piManagement.extensions,
                    'npm': redacted(b.piManagement.npmConfig), 'npmStatus': b.piManagement.npmStatus},
                    'plugins': redacted(b.providerPlugins.rows), 'updates': {'busy': b.appAbout.busy, 'release': b.appAbout.release,
                    'download': b.appAbout.download, 'installation': b.appAbout.installation}, 'serverRunning': b.serverRunning, 'keys': b.proxyKeys}
        if operation == 'jobs.get':
            if args.get('id') and args['id'] not in self.jobs: raise ValueError('Job ID does not exist')
            return {'jobs': redacted([{'id': key, **{k: v for k, v in job.items() if k in ('operation', 'status', 'result')}}
                                     for key, job in self.jobs.items() if not args.get('id') or key == args['id']])}
        if operation in ('models.select', 'sessions.reasoning'):
            target = b._pool.find(args.get('sessionId', '')) if args.get('sessionId') else caller or b._view
            if not target: raise ValueError('Session is no longer loaded')
            if operation == 'models.select':
                if target.busy and queue: return self._queue(operation, {**args, 'sessionId': target.id}, caller)
                if target.busy: raise ValueError('Session is still busy')
                b.gateway.resolve(args['model'], args['provider'])
                target.provider, target.model = args['provider'], args['model']
                target.context_usage = {}
                if target is b._view:
                    b.store.data.update(selectedProvider=target.provider, selectedModel=target.model)
            else:
                if args.get('value') not in ('off', 'low', 'high', 'max'): raise ValueError('Reasoning must be off, low, high or max')
                target.reasoning_effort = args['value']
                if target.id: b.store.data['sessionMeta'].setdefault(target.id, {})['reasoningEffort'] = args['value']
                if target is b._view: b.store.data['ui']['reasoningEffort'] = args['value']
                b._write_pi({'type': 'reasoning_effort', 'value': args['value']}, target)
            b.store.save(); b.changed.emit(); b.reasoningChanged.emit(); b.contextUsageChanged.emit()
            return {'status': 'applied', 'sessionId': target.id}
        spec = self.operations.get(operation)
        if spec is None: raise ValueError('Unknown Umeko operation; read the documentation or use operations.list')
        fields = spec['args']
        if set(args) - {field[0] for field in fields}: raise ValueError('Unknown argument for ' + operation)
        values = []
        for field in fields:
            name, kind = field[:2]
            if name not in args and len(field) < 3: raise ValueError('Missing argument: ' + name)
            value = args.get(name, field[2] if len(field) > 2 else None)
            valid = {'string': isinstance(value, str), 'number': type(value) in (int, float) and math.isfinite(value),
                     'integer': type(value) is int, 'boolean': type(value) is bool,
                     'json': isinstance(value, dict if name in ('config', 'fields') else list)}[kind]
            if not valid: raise ValueError(name + ' must be ' + kind)
            values.append(value)
        exists = spec.get('exists')
        if spec['target'] == 'plugins' and exists == 'provider': b.providerPlugins._record(args.get('id'))
        if operation in ('plugins.addAccount', 'plugins.uninstall'):
            b.providerPlugins.require_package(args['plugin'], args['version'])
        source = {'provider': b.config['providers'], 'project': b.store.data['projects'], 'session': self._sessions()}.get(exists)
        if source is not None and not any(item['id'] == args.get('id') for item in source): raise ValueError(exists + ' ID does not exist')
        if operation == 'appearance.language' and args['language'] not in ('zh', 'en'): raise ValueError('language must be zh or en')
        if operation == 'appearance.fontScale' and not .5 <= args['scale'] <= 2: raise ValueError('scale must be 0.5-2')
        if operation == 'themes.select' and args['id'] not in ['light', 'dark', 'yanami', *[t['id'] for t in b.customThemes]]: raise ValueError('Theme ID does not exist')
        if operation == 'themes.remove' and args['id'] not in [t['id'] for t in b.customThemes]: raise ValueError('Custom theme ID does not exist')
        if operation == 'items.pin':
            items = b.store.data['projects'] if args['kind'] == 'project' else self._sessions() if args['kind'] == 'session' else []
            if not any(item['id'] == args['id'] for item in items): raise ValueError('Pin target does not exist')
        if operation == 'projects.add' and (not values[0] or any(not isinstance(path, str) or not Path(path).expanduser().is_dir() for path in values[0])): raise ValueError('paths must contain existing directories')
        if operation == 'workspace.set' and not Path(args['path']).expanduser().is_dir(): raise ValueError('Workspace directory does not exist')
        if operation == 'agent.save':
            patch = values[0]
            allowed = {'maxTokens', 'instructions', 'autoCompaction', 'agentDir', 'skillPaths', 'extensionPaths'}
            if set(patch) - allowed: raise ValueError('Unknown Agent setting')
            if 'maxTokens' in patch and (type(patch['maxTokens']) is not int or not 256 <= patch['maxTokens'] <= 32768): raise ValueError('maxTokens must be an integer from 256 to 32768')
            if 'autoCompaction' in patch and type(patch['autoCompaction']) is not bool: raise ValueError('autoCompaction must be boolean')
            for key in ('instructions', 'agentDir'):
                if key in patch and not isinstance(patch[key], str): raise ValueError(key + ' must be a string')
            if len(patch.get('instructions', '')) > 16000: raise ValueError('instructions exceeds 16000 characters')
            for key in ('skillPaths', 'extensionPaths'):
                if key in patch and (not isinstance(patch[key], list) or any(not isinstance(path, str) for path in patch[key])): raise ValueError(key + ' must be an array of paths')
        if operation == 'network.npm':
            if set(values[0]) - {'npmRegistry', 'npmUserconfig', 'npmCafile'}: raise ValueError('Unknown npm setting')
            values[0] = {**b.piManagement.npmConfig, **values[0]}
        if queue and self._blocked(spec, args, caller): return self._queue(operation, args, caller)
        if self._blocked(spec, args, caller): raise ValueError('The relevant task is still busy')
        if operation == 'agent.save': values[0] = {**b.store.data['agent'], **values[0]}
        if operation == 'projects.add':
            values[0] = [QUrl.fromLocalFile(str(Path(path).expanduser().resolve())).toString() for path in values[0]]
        for index, field in enumerate(fields):
            if field[0] == 'path': values[index] = QUrl.fromLocalFile(str(Path(values[index]).expanduser().resolve())).toString()
            if field[1] == 'json': values[index] = json.dumps(values[index], ensure_ascii=False)
        target = {'backend': b, 'plugins': b.providerPlugins, 'management': b.piManagement, 'about': b.appAbout}[spec['target']]
        messages = []
        capture = lambda message: messages.append(message)
        before = {p['id'] for p in b.config['providers']}
        if spec.get('async') and job_id is None: job_id = self._new_job(operation, 'running')
        previous_dispatch = self._dispatching
        self._dispatching = job_id
        b.toast.connect(capture)
        try:
            result = getattr(target, spec['method'])(*values)
        except Exception as error:
            if job_id is not None: self._finish(job_id, {'ok': False, 'error': str(error)})
            raise
        finally:
            self._dispatching = previous_dispatch
            b.toast.disconnect(capture)
        if spec.get('async') and spec['target'] == 'plugins' and args['id'] in b.providerPlugins.busy:
            self._plugins[args['id']] = job_id
            self._observe(job_id, ('plugin', args['id']))
        if operation in ('extensions.install', 'mcp.add') and b.piManagement.installState == 'failed':
            if job_id is not None: self._finish(job_id, {'ok': False, 'error': b.piManagement.installMessage})
            raise ValueError(b.piManagement.installMessage)
        if result is False or any(re.search(r'无效|失败|请先|请等待|不能|不存在|请选择|无法|不支持|错误|不能为空', message) for message in messages):
            if job_id is not None: self._finish(job_id, {'ok': False, 'error': messages[-1] if messages else 'Umeko rejected the operation'})
            raise ValueError(messages[-1] if messages else 'Umeko rejected the operation')
        created = [p['id'] for p in b.config['providers'] if p['id'] not in before]
        output = {'status': 'accepted' if spec.get('async') else 'applied'}
        if result is not None: output['result'] = redacted(result)
        if created: output['createdProviderIds'] = created
        if messages: output['messages'] = messages
        if job_id is not None:
            output['jobId'] = job_id
            if self.jobs[job_id]['status'] == 'failed':
                return {'status': 'failed', **self.jobs[job_id]['result'], 'jobId': job_id}
            if not self.jobs[job_id]['pending'] and self.jobs[job_id]['status'] == 'running':
                if result is None and not messages: output['message'] = 'Operation finished without starting background work'
                self._finish(job_id, {'ok': True, **output})
        return output
