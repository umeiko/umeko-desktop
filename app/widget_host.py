"""Small asynchronous, allow-listed host API for portable Widget pages/workers.

Native Pi administration owns the work. A Widget never receives the application
backend, provider settings, credentials, or permission-setting operations.
"""
from __future__ import annotations

import copy
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .tool_visibility import catalog, NATIVE_ID
from collections import OrderedDict

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot


OPERATIONS = {
    'pi.status': ('pi.read', None),
    'pi.network': ('pi.read', None),
    'pi.preset': ('pi.manage',None),
    'pi.tool': ('pi.manage',None),
    'pi.plugin': ('pi.manage',None),
    'pi.tools': ('pi.read',None),
    'pi.inventory': ('pi.read', None),
    'pi.toolVisibility': ('pi.manage', None),
    'pi.scan': ('pi.read', 'extensions.scan'),
    'pi.checkUpdate': ('pi.read', 'extensions.checkUpdate'),
    'pi.details': ('pi.read', 'extensions.details'),
    'pi.activation': ('pi.manage', 'extensions.activation'),
    'pi.refresh': ('pi.manage', 'extensions.refresh'),
    'pi.enable': ('pi.manage', 'extensions.enable'),
    'pi.install': ('pi.manage', 'extensions.install'),
    'pi.remove': ('pi.manage', 'extensions.remove'),
    'pi.job': ('pi.read', None),
    'pi.cancel': ('pi.manage', None),
    'skills.list': ('skills.read', None),
    'skills.details': ('skills.read', None),
    'skills.job': ('skills.read', None),
    'skills.attach': ('skills.manage', None),
    'skills.default': ('skills.manage', None),
    'skills.reveal': ('skills.manage', None),
    'skills.remove': ('skills.manage', None),
    'skills.importPreview': ('skills.read', None),
    'skills.import': ('skills.manage', None),
    'skills.browse': ('skills.read', None),
    'skills.preview': ('skills.read', None),
    'skills.open': ('skills.read', None),
    'skills.copy': ('skills.read', None),
    'skills.paste': ('skills.manage', None),
    'skills.importLocal': ('skills.manage', None),
    'skills.insert': ('session.write', None),
    'skills.rename': ('skills.manage', None),
    'skills.delete': ('skills.manage', None),
    'checkpoints.acquire': ('workspace.write', None),
    'checkpoints.release': ('workspace.write', None),
}

# User-initiated paste/drop adds new folders only. Replacement still goes
# through the preview/confirmation path; these operations cannot overwrite.
DIRECT_SKILL_IMPORTS = frozenset(('skills.paste', 'skills.importLocal'))


def requires_confirmation(name):
    return OPERATIONS[name][0] in ('pi.manage', 'skills.manage') and name != 'pi.cancel' and name not in DIRECT_SKILL_IMPORTS


class WidgetHost(QObject):
    changed = Signal()

    def __init__(self, manager):
        super().__init__(manager)
        self.m, self.b = manager, manager.b
        self._approval = {}
        self._pending = None
        self.jobs = OrderedDict()
        self.requests = {}
        self.activity = {}
        self.checkpoint_locks = {}
        self._panel_approval = {}
        self._skills = None
        self.activity_timer = QTimer(self)
        self.activity_timer.setSingleShot(True)
        self.activity_timer.setInterval(200)
        self.activity_timer.timeout.connect(self._flush_activity)
        pool = getattr(self.b, '_pool', None)
        if pool: pool.event.connect(self.observe)

    @Property('QVariantMap', constant=True)
    def capabilities(self):
        operations = dict(OPERATIONS)
        if not callable(getattr(getattr(self.b, 'piManagement', None), 'uninstallPackage', None)):
            operations.pop('pi.remove')
        return {'version': 1, 'operations': {name: {'permission': spec[0],
                'confirmation': requires_confirmation(name)} for name, spec in operations.items()},
                'requestBytes': 16384, 'responseBytes': 262144,
                'mutationsRequireIdle': True, 'runtimes': ['node'], 'events': {'pi.activity': {'permission':'pi.observe','maxBytes':65536,'intervalMs':200}}}

    def runtimes(self):
        from .pi_runtime import node_executable
        return {'node': {'executable': node_executable()}}

    @Property('QVariantMap', notify=changed)
    def pendingApproval(self):
        return self._approval

    @Property('QVariantMap', notify=changed)
    def panelApproval(self):
        # Kept out of pendingApproval so the main-window dialog never opens.
        return self._panel_approval

    def _skill_service(self):
        if self._skills is None:
            from .skill_management import SkillJobs
            self._skills = SkillJobs(self)
        return self._skills

    def workspace_locked(self, workspace):
        target = self.m.bridge.workspace(workspace)
        return bool(target and any(lock['workspace'] == target for lock in self.checkpoint_locks.values()))

    def release_checkpoint(self, identifier, token, worker=None):
        lock = self.checkpoint_locks.get(token)
        if not lock or lock['widget'] != identifier or worker is not None and lock['worker'] is not worker:
            return False
        self.checkpoint_locks.pop(token, None)
        self._sync_checkpoint_locks()
        return True

    def _sync_checkpoint_locks(self):
        pool = getattr(self.b, '_pool', None)
        for record in getattr(pool, 'records', {}).values():
            pool.write(record, {'type': 'checkpoint_lock', 'locked': self.workspace_locked(record.workspace)})

    def stop(self, identifier):
        for token in [token for token, lock in self.checkpoint_locks.items() if lock['widget'] == identifier]:
            self.release_checkpoint(identifier, token)
        if self._skills: self._skills.stop(identifier)
        self.activity.pop(identifier, None)
        if any(owner['widget']==identifier and owner.get('operation')=='pi.install' and getattr(self.b._umeko_control,'jobs',{}).get(key,{}).get('status')=='running' for key,owner in self.jobs.items()):
            cancel=getattr(self.b.piManagement,'cancelInstall',None)
            if callable(cancel):cancel()
        if self._pending and self._pending['widget'] == identifier:
            self.respondApproval(False)
        for key in [key for key, value in self.jobs.items() if value['widget'] == identifier]:
            self.jobs.pop(key)
        for key in [key for key in self.requests if key[0] == identifier]:
            self.requests.pop(key)

    def observe(self, record, event):
        if event.get('type') != 'tool' or event.get('state') not in ('done', 'error', 'interrupted'): return
        if not any(worker.get('ready') and 'pi.observe' in self.m.entries[identifier].get('permissions',[]) for identifier,worker in self.m.workers.items()): return
        source = next((row.get('source','') for row in getattr(record,'resources',{}).get('allTools',[]) if row.get('name') == event.get('name')), '')
        item = {'kind':'toolFinished','id':str(event.get('id',''))[:160],
                'name':str(event.get('name',''))[:160], 'state':event['state'], 'source':str(source)[:2048],
                'time':datetime.now(timezone.utc).isoformat(),
                'session':{'token':record.key,'id':record.id,'workspace':record.workspace}}
        for identifier, worker in self.m.workers.items():
            if not worker.get('ready') or 'pi.observe' not in self.m.entries[identifier].get('permissions',[]): continue
            if not self.m.application(identifier) and worker['token'] != record.key: continue
            queue = self.activity.setdefault(identifier, {'worker':worker,'events':[],'dropped':0})
            if queue['worker'] is not worker:
                queue = {'worker':worker,'events':[],'dropped':0}; self.activity[identifier] = queue
            queue['events'].append(item)
            while len(queue['events']) > 64 or len(json.dumps(queue['events'],ensure_ascii=False).encode()) > 64000:
                queue['events'].pop(0); queue['dropped'] += 1
        if self.activity and not self.activity_timer.isActive(): self.activity_timer.start()

    def _flush_activity(self):
        queues, self.activity = self.activity, {}
        for identifier, queue in queues.items():
            if self.m.workers.get(identifier) is not queue['worker'] or not self.m.enabled(identifier): continue
            self.m.send(identifier, {'id':uuid.uuid4().hex,'operation':'event',
                'arguments':{'name':'pi.activity','data':{'version':1,'events':queue['events'],'dropped':queue['dropped']}}})

    def _owner(self, request):
        identifier = request['widget']
        if self.m.closed or self.m.workers.get(identifier) is not request['worker']:
            raise ValueError('Widget instance has stopped')
        if not self.m.enabled(identifier) or not self.m.session_enabled(identifier):
            raise ValueError('Widget is not enabled')
        session = request['session']
        current = self.m._session
        if not isinstance(session, dict) or not session.get('token') or session.get('token') != current.get('token') or session.get('workspace') != current.get('workspace'):
            raise ValueError('The target chat or workspace changed; retry from its page')
        return identifier

    def _reply(self, request, value):
        self.requests.pop((request['widget'], request['id']), None)
        if self.m.workers.get(request['widget']) is not request['worker']:
            return
        try:
            raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
            if len(raw) > 262144:
                value = {'ok': False, 'error': 'Host response exceeds 256 KiB; narrow the query'}
        except (TypeError, ValueError):
            value = {'ok': False, 'error': 'Host returned invalid JSON'}
        value = {'requestId': request['id'], 'operation': request['operation'], **value}
        self.m.hostResponse.emit(request['widget'], request['id'], value)
        self.m.send(request['widget'], {'id': uuid.uuid4().hex, 'operation': 'event',
                    'arguments': {'name': 'host.response', 'data': value}})

    def request_for(self, identifier, value):
        # QML and Python both enter here; neither can select arbitrary host methods.
        worker = self.m.workers.get(identifier)
        if not worker:
            return ''
        identifier_request = value.get('id', uuid.uuid4().hex)
        if not isinstance(identifier_request, str) or not re.fullmatch('[a-f0-9]{32}', identifier_request):
            return ''
        key = (identifier, identifier_request)
        if key in self.requests or sum(k[0] == identifier for k in self.requests) >= 8:
            return ''
        request = {'widget': identifier, 'worker': worker, 'id': identifier_request,
                   'operation': value.get('operation'), 'arguments': value.get('arguments', {}),
                   'session': copy.deepcopy(value.get('session', {}))}
        self.requests[key] = request
        QTimer.singleShot(0, self, lambda: self._begin(request))
        return identifier_request

    def _begin(self, request):
        if self.requests.get((request['widget'], request['id'])) is not request:
            return
        try:
            identifier = self._owner(request)
            operation, args = request['operation'], request['arguments']
            if operation not in self.capabilities['operations']:
                raise ValueError('Host operation is not available; inspect hostCapabilities')
            if not isinstance(args, dict) or len(json.dumps(args, allow_nan=False).encode()) > 16384:
                raise ValueError('Host arguments must be a JSON object of at most 16 KiB')
            permission, _ = OPERATIONS[operation]
            if permission not in self.m.entries[identifier].get('permissions', []):
                raise ValueError('Widget permission is required: ' + permission)
            fields = {'pi.status': {'offset', 'limit', 'query', 'details', 'toolOffset'}, 'pi.inventory': set(), 'pi.toolVisibility': {'id','name','visible'}, 'pi.network': set(), 'pi.scan': set(), 'pi.refresh': set(),
                      'pi.enable': {'id', 'enabled'}, 'pi.install': {'source', 'project'},
                      'pi.remove': {'id'}, 'pi.job': {'id'}, 'pi.cancel': {'id'}, 'pi.checkUpdate': {'id'}, 'pi.details': {'id'}, 'pi.activation': {'id','mode'},
                      'pi.preset': {'preset'},'pi.tool': {'name','enabled'},'pi.plugin': {'id','enabled'},'pi.tools': {'id','query','offset','limit'},
                      'skills.list': set(), 'skills.details': {'id'}, 'skills.job': {'id', 'offset', 'limit', 'wait'},
                      'skills.attach': {'id', 'enabled'}, 'skills.default': {'id', 'enabled'},
                      'skills.reveal': {'id'}, 'skills.remove': {'id'},
                      'skills.importPreview': {'source', 'project'}, 'skills.import': {'id', 'decisions'},
                      'skills.browse': set(), 'skills.preview': {'id'}, 'skills.open': {'id', 'mode'}, 'skills.copy': {'id', 'kind'},
                      'skills.paste': {'project'}, 'skills.importLocal': {'source', 'project'},
                      'skills.insert': {'id'}, 'skills.rename': {'id', 'name'}, 'skills.delete': {'id'},
                      'checkpoints.acquire': {'id'}, 'checkpoints.release': {'token'}}[operation]
            if set(args) - fields:
                raise ValueError('Unknown host arguments')
            if operation == 'checkpoints.acquire' and not re.fullmatch('[a-f0-9]{32}', args.get('id', '')):
                raise ValueError('A valid checkpoint id is required')
            if operation == 'checkpoints.release' and not re.fullmatch('[a-f0-9]{32}', args.get('token', '')):
                raise ValueError('A valid checkpoint lock token is required')
            if operation == 'skills.job' and 'wait' in args and type(args['wait']) is not bool:
                raise ValueError('wait must be boolean')
            if operation in ('pi.enable', 'pi.remove', 'pi.job', 'pi.cancel', 'pi.checkUpdate', 'pi.details', 'pi.activation', 'pi.plugin','pi.tools') or operation.startswith('skills.') and operation not in ('skills.list', 'skills.browse', 'skills.paste', 'skills.importLocal', 'skills.importPreview'):
                if not isinstance(args.get('id'), str) or not args['id'] or len(args['id']) > 4096:
                    raise ValueError('A valid id is required')
            if operation in ('pi.enable','pi.plugin','pi.tool', 'skills.attach', 'skills.default') and type(args.get('enabled')) is not bool:
                raise ValueError('enabled must be boolean')
            if operation == 'pi.activation' and args.get('mode') not in ('global','session','disabled'):
                raise ValueError('Invalid activation mode')
            if operation == 'skills.open' and args.get('mode') not in ('preview', 'edit', 'reveal'):
                raise ValueError('Invalid Skill open mode')
            if operation == 'skills.copy' and args.get('kind') not in ('folder', 'path'):
                raise ValueError('Invalid Skill copy kind')
            if operation == 'skills.rename':
                from .skill_folders import validate_folder_name
                validate_folder_name(args.get('name'))
            if operation in ('skills.rename', 'skills.delete'):
                self._skill_service().folder_for(request, args['id'])
            if operation == 'pi.toolVisibility':
                if not isinstance(args.get('id'),str) or not isinstance(args.get('name'),str) or not 0<len(args['name'])<=256 or type(args.get('visible')) is not bool:
                    raise ValueError('Invalid tool visibility arguments')
                self._tool_target(args)
            if operation in ('pi.install', 'skills.importPreview', 'skills.importLocal'):
                if not isinstance(args.get('source'), str) or not args['source'].strip() or len(args['source']) > 4096:
                    raise ValueError('A valid package source is required')
                if type(args.get('project', False)) is not bool:
                    raise ValueError('project must be boolean')
            if operation in DIRECT_SKILL_IMPORTS and type(args.get('project')) is not bool:
                raise ValueError('An explicit destination scope is required')
            if operation == 'skills.import':
                if not isinstance(args.get('decisions', {}), dict) or any(not isinstance(key, str) or value not in ('skip', 'replace') for key, value in args.get('decisions', {}).items()):
                    raise ValueError('Each conflict needs a skip or replace decision')
                self._skill_service().preview_for(request, args['id'])
            if operation in ('pi.status','pi.tools', 'skills.job'):
                if any(key in args and (not isinstance(args[key],str) or len(args[key]) > 256) for key in ('query','details')):
                    raise ValueError('Invalid local catalog query')
                if type(args.get('toolOffset', 0)) is not int or not 0 <= args.get('toolOffset', 0) <= 1000000:
                    raise ValueError('Invalid tool offset')
                if type(args.get('offset', 0)) is not int or not 0 <= args.get('offset', 0) <= 1000000:
                    raise ValueError('offset must be an integer from 0 to 1000000')
                if type(args.get('limit', 100)) is not int or not 1 <= args.get('limit', 100) <= 200:
                    raise ValueError('limit must be an integer from 1 to 200')
            if operation.startswith('skills.') and operation not in ('skills.job', 'skills.browse', 'skills.preview', 'skills.open', 'skills.copy', 'skills.insert'):
                self._skill_service().idle()
            if operation in ('pi.preset','pi.tool','pi.plugin') and identifier=='pi-manager' and self.m.entries[identifier].get('builtin'):
                self._execute(request);return
            if operation=='skills.attach' and identifier=='skill-manager' and self.m.entries[identifier].get('builtin'):
                self._execute(request);return
            if requires_confirmation(operation):
                if self.b.busy or self.b.piManagement.busy or self.b.kernelBusy:
                    raise ValueError('Pi is busy; Agent installs must use run_pi_command and its native queued reload')
                if self._pending or self.b.pendingApproval:
                    raise ValueError('Another confirmation is pending')
                self._pending = request
                approval = {'id': request['id'], 'method': 'confirm',
                    'title': 'Widget · ' + self.m.entries[identifier]['name'],
                    'detail': operation + '\n' + json.dumps(args, ensure_ascii=False, indent=2)}
                if permission == 'skills.manage' or identifier == 'skill-manager':
                    # Only the host surface receives these controls. The SDK has
                    # no operation, method or event capable of approving them.
                    self._panel_approval = {**approval, 'widget': identifier, 'operation': operation,
                        'enabled': args.get('enabled', False), 'name': args.get('source', '')}
                    if self._skills and args.get('id'):
                        rows = self._skills.catalog.get((request['session']['token'], request['session']['workspace']), [])
                        self._panel_approval['name'] = next((r['name'] for r in rows if r['id'] == args['id']), '')
                        if operation == 'skills.rename':
                            self._panel_approval['name'] += ' → ' + args['name']
                    if operation == 'skills.import':
                        preview = self._skills.preview_for(request, args['id'])
                        self._panel_approval.update(name=', '.join(row['name'] for row in preview['value']['skills'])[:600], project=preview['project'])
                else:
                    self._approval = approval
                self.changed.emit()
                QTimer.singleShot(120000, self, lambda: self.respondApproval(False)
                                  if self._pending is request else None)
                return
            self._execute(request)
        except (ValueError, TypeError, KeyError) as error:
            self._reply(request, {'ok': False, 'error': str(error)})

    @Slot(bool)
    def respondApproval(self, allowed):
        request = self._pending
        self._pending, self._approval, self._panel_approval = None, {}, {}
        self.changed.emit()
        if not request:
            return
        if not allowed:
            self._reply(request, {'ok': False, 'status': 'declined', 'error': 'User declined the Widget operation'})
            return
        try:
            self._execute(request)
        except (ValueError, TypeError, KeyError) as error:
            self._reply(request, {'ok': False, 'error': str(error)})

    def _tool_target(self, args):
        if not self.b.piManagement.extensionsCurrent:
            raise ValueError('Refresh the current local inventory first')
        row = next((row for row in catalog(self.b._view, self.b.piManagement.extensions) if row['id'] == args['id']), {})
        if not any(tool['name']==args['name'] and tool['editable'] for tool in row.get('tools',[])):
            raise ValueError('Tool does not belong to this loaded package')

    def _execute(self, request):
        identifier = self._owner(request)  # Revalidate after the user spends time in confirmation.
        operation, args = request['operation'], request['arguments']
        if operation.startswith('checkpoints.'):
            if identifier != 'change-review':
                raise ValueError('Checkpoint locks are owned by the change review Widget')
            if operation == 'checkpoints.release':
                if not self.release_checkpoint(identifier, args['token'], request['worker']):
                    raise ValueError('Checkpoint lock is invalid or expired')
                self._reply(request, {'ok': True})
                return
            workspace = self.m.bridge.workspace(request['session'].get('workspace'))
            if not workspace:
                raise ValueError('A workspace is required')
            if self.workspace_locked(workspace):
                raise ValueError('Another checkpoint restore owns this workspace')
            pool = getattr(self.b, '_pool', None)
            records = list(getattr(pool, 'records', {}).values())
            running = [record.title for record in records if record.busy and self.m.bridge.workspace(record.workspace) == workspace]
            if running:
                raise ValueError('同工作目录仍有运行中的任务：' + '、'.join(running[:4]))
            live = [record for record in records if self.m.bridge.workspace(record.workspace) == workspace and
                    record.process and record.ready and not record.stale and not record.global_agent]
            pending = {id(record) for record in live}
            failed = False
            def finish():
                self._owner(request)
                if self.workspace_locked(workspace):
                    raise ValueError('Another checkpoint restore owns this workspace')
                current = [record.title for record in getattr(pool, 'records', {}).values()
                           if record.busy and self.m.bridge.workspace(record.workspace) == workspace]
                if current:
                    raise ValueError('同工作目录仍有运行中的任务：' + '、'.join(current[:4]))
                token = uuid.uuid4().hex
                self.checkpoint_locks[token] = {'widget': identifier, 'worker': request['worker'], 'workspace': workspace}
                self._sync_checkpoint_locks()
                QTimer.singleShot(60000, self, lambda: self.release_checkpoint(identifier, token, request['worker']))
                self._reply(request, {'ok': True, 'result': {'token': token, 'expiresMs': 60000}})
            def checked(record, response):
                nonlocal failed
                if failed:
                    return
                try:
                    self._owner(request)
                    pending.discard(id(record))
                    if not response.get('ok'):
                        raise ValueError(str(response.get('value') or '无法读取后台任务状态'))
                    jobs = response['value'].get('jobs')
                    if not isinstance(jobs, list):
                        raise ValueError('后台任务状态无效')
                    if any(job.get('status') == 'running' and job.get('cwd') and Path(job['cwd']).resolve().is_relative_to(Path(workspace)) for job in jobs):
                        raise ValueError('同工作目录仍有运行中的后台任务；请等待结束后再恢复')
                    if not pending:
                        finish()
                except (ValueError, TypeError, OSError) as error:
                    failed = True
                    self._reply(request, {'ok': False, 'error': str(error)})
            if not live:
                finish()
                return
            for record in live:
                if not pool.query_catalog(record, 'background-jobs', lambda response, record=record: checked(record, response)):
                    checked(record, {'ok': False, 'value': 'Pi 实例已变化，请重新检查后台任务'})
            return
        if operation.startswith('skills.'):
            service = self._skill_service()
            result = service.get(request, args['id'], args.get('offset', 0), args.get('limit', 100), args.get('wait', False)) if operation == 'skills.job' else service.start(request)
            if result is not None:
                self._reply(request, result)
            return
        if operation in ('pi.preset','pi.tool','pi.plugin'):
            self._reply(request,{'ok':True,'result':self.b.piManagement.configure_capabilities(operation,args)});return
        if operation=='pi.tools':
            self._reply(request,{'ok':True,'result':self.b.piManagement.capability_tools(args['id'],args.get('query',''),args.get('offset',0),args.get('limit',100))});return
        if operation == 'pi.toolVisibility':
            self._tool_target(args)
            self.b.piManagement.set_tool_visible(args['name'], args['visible'])
            self._reply(request, {'ok': True})
            return
        if operation == 'pi.inventory':
            record=self.b._view
            if not record.resources.get('allTools') or record.stale or (not record.process and record.model):
                if self.b.busy or record.subagents_active or self.b.kernelBusy:
                    raise ValueError('请等待当前任务结束后刷新工具列表')
                if not getattr(record,'model',''):
                    raise ValueError('请先选择模型，再刷新工具列表')
                if not self.b._command_pi('load', record):
                    raise ValueError('Pi 工具列表加载失败')
            self._reply(request, {'ok':True})
            return
        if operation == 'pi.details' and args['id'] == NATIVE_ID:
            self._reply(request, {'ok':True})
            return
        if operation in ('pi.activation','pi.details'):
            if not self.b.piManagement.extensionsCurrent or not any(row.get('id')==args['id'] for row in self.b.piManagement.extensions):
                raise ValueError('Refresh the current local inventory first')
        if operation == 'pi.remove':
            management = self.b.piManagement
            if not management.extensionsCurrent:
                raise ValueError('Refresh the current workspace before removing a package')
            row = next((item for item in management.extensions if item.get('id') == args['id']), {})
            if row.get('source') in ('', 'builtin', 'local', None):
                raise ValueError('Only a registered third-party package can be removed')
        if operation == 'pi.network':
            settings = self.b.piManagement.npmConfig
            self._reply(request, {'ok': True, 'result': {k: settings.get(k, '') for k in ('npmRegistry', 'npmUserconfig', 'npmCafile')}})
            return
        if operation == 'pi.status':
            management = self.b.piManagement
            current = management.extensionsCurrent
            all_rows = management.capability_extensions() if current else []
            query=args.get('query','').casefold()
            detail_id=args.get('details','')
            rows=[row for row in all_rows if row['id']==detail_id] if detail_id else [row for row in all_rows if not query or query in (str(row.get('name',''))+' '+str(row.get('path',''))+' '+str(row.get('info',{}).get('description',''))).casefold() or management.capability_tools(row['id'],query,0,1)['total']>0]
            offset, limit = args.get('offset', 0), args.get('limit', 100)
            page=[{**row,'tools':[{key:tool[key] for key in ('name','visible')} for tool in row.get('tools',[])[:12]]} for row in rows[offset:offset+limit]]
            paths={row['path'] for row in page}
            modes={path:mode for path,mode in self.b._view.extension_modes.items() if path in paths}
            result={'profile':management.capability_profile(),'sessionBusy':self.b.busy,'busy':management.busy or self.b.kernelBusy or (self.b._view.busy and self.b._view.action=='inspect'), 'status':management.status if current else '',
                'extensions':page,'total':len(rows),'catalogTotal':len(all_rows), 'hasMore':offset+limit<len(rows),
                'contextCurrent':current, 'inventoryReady':bool(self.b._view.resources.get('allTools')),
                'inventoryFailed':getattr(self.b._view,'action','')=='load' and not self.b.busy and (getattr(self.b._view,'failed',False) or getattr(self.b._view,'cancelled',False)),
                'agentBusy':self.b.busy or bool(getattr(self.b._view,'subagents_active',False)), 'workspace':request['session'].get('workspace',''),
                'activationModes':modes,'extensionUpdate':management.extensionUpdate if current else {}}
            if detail_id:
                doc=management.extensionDetails
                result['details']=doc if doc.get('id')==detail_id and current else {}
                if detail_id == NATIVE_ID: result['details']={'id':NATIVE_ID,'markdown':'Pi 内置工具，可按当前会话分别设置对 Agent 的可见性。'}
                tools=rows[0]['tools'] if rows else []
                start=args.get('toolOffset',0)
                result['tools']=tools[start:start+40]
                result['toolTotal']=len(tools)
                result['toolsHasMore']=start+40<len(tools)
            self._reply(request,{'ok':True,'result':result})
            return
        control = self.b._umeko_control
        if operation in ('pi.job','pi.cancel'):
            owner = self.jobs.get(args['id'])
            if not owner or owner['widget'] != request['widget'] or owner['worker'] is not request['worker'] or any(owner['session'].get(k) != request['session'].get(k) for k in ('token', 'workspace')):
                raise ValueError('Host job does not belong to this Widget instance and chat')
            result = control.execute({'operation': 'jobs.get', 'arguments': args}, self.b._view, queue=False)
            if operation=='pi.cancel':
                rows=result.get('jobs',[])
                if not rows or rows[0].get('operation')!='extensions.install' or rows[0].get('status')!='running':
                    raise ValueError('This Widget has no running install to cancel')
                self.b.piManagement.cancelInstall()
                self._reply(request,{'ok':True,'status':'cancelling'});return
            if result.get('ok') and any(item.get('operation')=='extensions.install' and item.get('status')=='running' for item in result.get('jobs',[])):
                management=self.b.piManagement
                result['progress']={'message':management.installMessage[:800],'state':management.installState,'cancellable':management.installCancellable}
            if result.get('ok'):
                result['jobs'] = [{**{k: item[k] for k in ('id', 'operation', 'status')},
                    'result': {k: v for k, v in item.get('result', {}).items() if k in ('ok', 'error')}}
                    for item in result.get('jobs', [])]
            self._reply(request, result)
            return
        if self.b.piManagement.busy or self.b.kernelBusy:
            raise ValueError('Pi management is busy; retry when it finishes')
        if OPERATIONS[operation][0] == 'pi.manage' and self.b.busy:
            raise ValueError('The task became busy; no Widget change was applied')
        result = control._confirmed_widget_install(args, self.b._view) if operation == 'pi.install' else control.execute(
            {'operation': OPERATIONS[operation][1], 'arguments': args}, self.b._view, queue=False)
        job = result.get('jobId')
        if job:
            self.jobs[job] = {'widget': request['widget'], 'worker': request['worker'], 'session': request['session'], 'operation':operation}
            while len(self.jobs) > 128:
                self.jobs.popitem(last=False)
        self._reply(request, result)
