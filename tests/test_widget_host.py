"""Real asynchronous host boundary; no provider, package install or network."""
import json
import os
from unittest.mock import patch
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication, QObject, Signal
from app.widget_host import WidgetHost

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin-runtime'))
from umeko_plugin_sdk import Context, PluginError


class Manager(QObject):
    hostResponse = Signal(str, str, 'QVariantMap')
    inputRequested = Signal()

    def __init__(self):
        super().__init__()
        management = SimpleNamespace(busy=False, status='idle', extensionUpdate={}, extensionDetails={}, extensionsCurrent=True, npmConfig={'npmRegistry':'https://registry.example/','npmUserconfig':'/fixture/npmrc','npmCafile':'/fixture/ca.pem','privateKey':'must-not-leak'},
            extensions=[{'id': str(n), 'path':'builtin:fixture'+str(n), 'name': 'fixture', 'info':{'description':'Local example'}} for n in range(250)],
            uninstallPackage=lambda identifier: None)
        self.calls, self.frames, self.replies = [], [], {}
        self.b = SimpleNamespace(piManagement=management, busy=False, kernelBusy=False,
            pendingApproval={}, _view=SimpleNamespace(extension_modes={}, resources={},busy=False,action='idle'), _umeko_control=SimpleNamespace(execute=self.execute))
        from app.tool_visibility import catalog
        management.capability_extensions=lambda:catalog(self.b._view,management.extensions)
        management.capability_profile=lambda:{'preset':'full','custom':{'base':'full','tools':{},'plugins':{}}}
        def capability_tools(identifier,query='',offset=0,limit=100):
            source=next((r['path'] for r in management.extensions if r['id']==identifier),'')
            tools=[{'name':t['name'],'description':t.get('description','')[:1024],'enabled':True,'owner':source} for t in self.b._view.resources.get('allTools',[]) if t.get('source')==source and (not query or query in (t['name']+' '+t.get('description','')).casefold())]
            return {'tools':tools[offset:offset+limit],'total':len(tools),'hasMore':offset+limit<len(tools),'profile':management.capability_profile(),'loading':False}
        management.capability_tools=capability_tools
        self.closed = False
        self._session = {'token': 'chat-one', 'id': 'one', 'workspace': '/fixture'}
        self.entries = {key: {'name': key, 'permissions': ['pi.read', 'pi.manage']}
                        for key in ('a', 'b')}
        self.workers = {'a': {'ready': True}, 'b': {'ready': True}}
        self.hostResponse.connect(lambda widget, request, value: self.replies.__setitem__(request, value))

    def enabled(self, identifier): return True
    def session_enabled(self, identifier): return True
    def application(self, identifier): return True
    def send(self, identifier, value): self.frames.append((identifier, value))

    def execute(self, request, *args, **kwargs):
        self.calls.append(request)
        if request['operation'] == 'jobs.get':
            return {'ok': True, 'jobs': [{'id': 'job-one', 'operation': 'extensions.scan',
                'status': 'done', 'result': {'ok': True, 'value': ['large payload'] * 1000}}]}
        return {'ok': True, 'status': 'accepted', 'jobId': 'job-one'}


class WidgetHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.manager = Manager()
        self.host = WidgetHost(self.manager)

    def request(self, operation, args=None, widget='a', session=None):
        identifier = self.host.request_for(widget, {'operation': operation,
            'arguments': args or {}, 'session': session or dict(self.manager._session)})
        self.app.processEvents()
        return identifier

    def test_task_records_require_the_active_builtin_qml_page(self):
        from app.task_records import TaskStore

        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / 'tasks.sqlite3')
            for i in range(13):
                store.create(f'Objective {i}', 'Scope stays out of the list', '/fixture')
            manager = self.manager
            manager.b._task_records = SimpleNamespace(_storage=lambda: store)
            manager.b._view.key = manager._session['token']
            manager.b._view.prepared_task = ''
            manager._page = 'task-records'
            manager.entries['task-records'] = {'name': 'Tasks', 'builtin': True, 'permissions': ['tasks.read']}
            manager.workers['task-records'] = {'ready': True}
            manager.entries['a']['permissions'].append('tasks.read')

            def request(widget, page=False, offset=0):
                identifier = self.host.request_for(widget, {'operation': 'tasks.list',
                    'arguments': {'offset': offset}, 'session': dict(manager._session), 'page': True}, page=page)
                self.app.processEvents()
                return manager.replies[identifier]

            self.assertFalse(request('task-records')['ok'])
            self.assertFalse(request('a', page=True)['ok'])
            first = request('task-records', page=True)
            self.assertTrue(first['ok'], first)
            self.assertEqual(len(first['result']['tasks']), 12)
            self.assertTrue(first['result']['hasMore'])
            self.assertNotIn('scope', first['result']['tasks'][0])
            last = request('task-records', page=True, offset=12)
            self.assertEqual(len(last['result']['tasks']), 1)
            manager.b._view.key = 'chat-two'
            self.assertFalse(request('task-records', page=True)['ok'])

    def test_task_verification_does_not_save_after_the_page_changes(self):
        from app.task_records import TaskStore, versions_of

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = TaskStore(root / 'tasks.sqlite3')
            task_id = store.create('Deliver', 'Local output only', str(root))
            attempt_id = store.begin(task_id, str(root), '', '', [])
            artifact = root / 'report.txt'
            artifact.write_text('report')
            store.files(attempt_id, 'submitted', 'delivery', versions_of([{'path': str(artifact)}]))
            store.finish(attempt_id, 'finished', '')
            manager = self.manager
            manager.b._task_records = SimpleNamespace(_storage=lambda: store, store=store)
            manager.b._view.key = manager._session['token']
            manager._page = 'task-records'
            manager.entries['task-records'] = {'name': 'Tasks', 'builtin': True, 'permissions': ['tasks.manage']}
            manager.workers['task-records'] = {'ready': True}
            pending = {}
            manager.b._job = lambda name, run: pending.update({name: run})
            identifier = self.host.request_for('task-records', {'operation': 'tasks.verify',
                'arguments': {'taskId': task_id, 'attemptId': attempt_id}, 'session': dict(manager._session)}, page=True)
            self.app.processEvents()
            result = pending['task-details:' + identifier]()
            manager._page = 'a'
            self.host.task_result(identifier, {'ok': True, 'value': result})
            self.assertFalse(manager.replies[identifier]['ok'])
            self.assertIsNone(store.details(task_id, attempt_id)['files'][0]['check_result'])

    def test_pagination_and_allow_list_never_expose_other_desktop_settings(self):
        identifier = self.request('pi.status', {'offset': 200, 'limit': 100})
        result = self.manager.replies[identifier]['result']
        self.assertEqual(len(result['extensions']), 50)
        self.assertEqual(result['total'], 250)
        self.assertFalse(result['hasMore'])
        for operation in ('providers.list', 'settings.get', 'agent.save', 'installPermission'):
            identifier = self.request(operation)
            self.assertFalse(self.manager.replies[identifier]['ok'])
        self.assertEqual(self.manager.calls, [])

    def test_local_search_and_detail_payload_stay_scoped_and_bounded(self):
        management=self.manager.b.piManagement
        management.extensions[17]['name']='Needle package'
        management.extensionDetails={'id':'17','markdown':'# Local README'}
        self.manager.b._view.extension_modes={'builtin:fixture17':'disabled','other-chat-path':'session'}
        self.manager.b._view.resources={'allTools':[{'name':'local_tool','description':'x'*9000,'source':'builtin:fixture17'},{'name':'other_tool','source':'other-chat-path'}]}
        identifier=self.request('pi.status',{'query':'NEEDLE','limit':12})
        result=self.manager.replies[identifier]['result']
        self.assertEqual(result['total'],1)
        self.assertEqual(result['extensions'][0]['id'],'17')
        identifier=self.request('pi.status',{'details':'17','limit':1})
        result=self.manager.replies[identifier]['result']
        self.assertEqual(result['details']['markdown'],'# Local README')
        self.assertEqual(result['activationModes'],{'builtin:fixture17':'disabled'})
        self.assertEqual([tool['name'] for tool in result['tools']],['local_tool'])
        self.assertLessEqual(len(result['tools'][0]['description']),4096)
        identifier=self.request('pi.details',{'id':'missing'})
        self.assertFalse(self.manager.replies[identifier]['ok'])

    def test_idle_does_not_mean_inventory_ready_and_async_failure_is_reported(self):
        view = self.manager.b._view
        view.action = 'load'
        view.failed = view.cancelled = False
        result = self.manager.replies[self.request('pi.status')]['result']
        self.assertFalse(result['inventoryReady'])
        self.assertFalse(result['inventoryFailed'])
        view.failed = True
        self.manager.b.busy = True
        self.assertFalse(self.manager.replies[self.request('pi.status')]['result']['inventoryFailed'])
        self.manager.b.busy = False
        self.assertTrue(self.manager.replies[self.request('pi.status')]['result']['inventoryFailed'])
        view.failed, view.cancelled = False, True
        self.assertTrue(self.manager.replies[self.request('pi.status')]['result']['inventoryFailed'])

    def test_inventory_start_failure_is_returned_to_the_widget(self):
        view = self.manager.b._view
        view.model, view.process, view.stale, view.subagents_active = 'fixture', None, False, False
        self.manager.b._command_pi = lambda *args: False
        reply = self.manager.replies[self.request('pi.inventory')]
        self.assertFalse(reply['ok'])
        self.assertIn('加载失败', reply['error'])

    def test_chat_activation_validates_mode_and_requires_native_confirmation(self):
        identifier=self.request('pi.activation',{'id':'17','mode':'invalid'})
        self.assertFalse(self.manager.replies[identifier]['ok'])
        self.assertFalse(self.host.pendingApproval)
        identifier=self.request('pi.activation',{'id':'17','mode':'session'})
        self.assertEqual(self.host.pendingApproval['id'],identifier)
        self.assertEqual(self.manager.calls,[])
        self.host.respondApproval(True)
        self.assertTrue(self.manager.replies[identifier]['ok'])
        self.assertEqual(self.manager.calls[-1],{'operation':'extensions.activation','arguments':{'id':'17','mode':'session'}})

    def test_only_trusted_builtin_manager_applies_current_chat_switches_directly(self):
        changes=[]
        self.manager.b.piManagement.configure_capabilities=lambda op,args: changes.append((op,args)) or {'profile':{'preset':'minimal'}}
        self.manager.entries['pi-manager']={'name':'Pi','builtin':True,'permissions':['pi.read','pi.manage']}
        self.manager.workers['pi-manager']={'ready':True}
        for op,args in [('pi.preset',{'preset':'minimal'}),('pi.tool',{'name':'read','enabled':False}),('pi.plugin',{'id':'native','enabled':False})]:
            identifier=self.request(op,args,widget='pi-manager')
            self.assertTrue(self.manager.replies[identifier]['ok'])
            self.assertFalse(self.host.pendingApproval)
        self.assertEqual(len(changes),3)
        identifier=self.request('pi.tool',{'name':'read','enabled':False})
        self.assertEqual(self.host.pendingApproval['id'],identifier)
        self.assertEqual(len(changes),3)
        self.manager._session={'token':'other','id':'other','workspace':'/other'}
        self.host.respondApproval(True)
        self.assertFalse(self.manager.replies[identifier]['ok'])
        self.assertEqual(len(changes),3)

    def test_desktop_builtins_use_the_normal_confirmation_flow(self):
        self.manager.b.piManagement.extensions[17]['info']['required']=True
        for operation,args in [('pi.activation',{'id':'17','mode':'disabled'}),('pi.enable',{'id':'17','enabled':False})]:
            identifier=self.request(operation,args)
            self.assertEqual(self.host.pendingApproval['id'],identifier)
            self.host.respondApproval(True)
            self.assertTrue(self.manager.replies[identifier]['ok'])
        self.assertEqual(len(self.manager.calls),2)

    def test_install_progress_and_cancellation_are_owned_by_widget_and_chat(self):
        cancelled=[];management=self.manager.b.piManagement
        management.installMessage='正在安装 · 直连 · 系统证书'
        management.installState='installing';management.installCancellable=True
        management.cancelInstall=lambda:cancelled.append(True)
        control=self.manager.b._umeko_control
        control.jobs={'install-job':{'operation':'extensions.install','status':'running'}}
        control.execute=lambda request,*args,**kwargs: {'ok':True,'jobs':[{'id':'install-job','operation':'extensions.install','status':'running','result':{}}]}
        self.host.jobs['install-job']={'widget':'a','worker':self.manager.workers['a'],'session':dict(self.manager._session),'operation':'pi.install'}
        identifier=self.request('pi.job',{'id':'install-job'})
        self.assertEqual(self.manager.replies[identifier]['progress']['message'],management.installMessage)
        identifier=self.request('pi.cancel',{'id':'install-job'},widget='b')
        self.assertFalse(self.manager.replies[identifier]['ok']);self.assertEqual(cancelled,[])
        identifier=self.request('pi.cancel',{'id':'install-job'})
        self.assertTrue(self.manager.replies[identifier]['ok']);self.assertEqual(cancelled,[True])
        self.assertFalse(self.host.pendingApproval)
        self.host.stop('a');self.assertEqual(cancelled,[True,True])

    def test_tool_visibility_is_owner_checked_confirmed_and_includes_banned_tools(self):
        view=self.manager.b._view
        view.blocked_tools=['local_tool']
        view.resources={'allTools':[{'name':'local_tool','description':'Local tool','source':'builtin:fixture17','exposure':'deferred'}]}
        self.manager.b.piManagement.extensions[17]['enabled']=True
        changed=[]
        self.manager.b.piManagement.set_tool_visible=lambda name,visible:changed.append((name,visible))
        identifier=self.request('pi.status',{'details':'17'})
        tool=self.manager.replies[identifier]['result']['tools'][0]
        self.assertFalse(tool['visible']);self.assertTrue(tool['editable'])
        identifier=self.request('pi.toolVisibility',{'id':'18','name':'local_tool','visible':True})
        self.assertFalse(self.manager.replies[identifier]['ok'])
        self.assertFalse(self.host.pendingApproval)
        identifier=self.request('pi.toolVisibility',{'id':'17','name':'local_tool','visible':True})
        self.assertEqual(changed,[])
        self.assertTrue(self.host.pendingApproval)
        self.manager._session={'token':'another-chat','workspace':'/fixture'}
        self.host.respondApproval(True)
        self.assertFalse(self.manager.replies[identifier]['ok']);self.assertEqual(changed,[])
        self.manager._session={'token':'chat-one','workspace':'/fixture'}
        identifier=self.request('pi.toolVisibility',{'id':'17','name':'local_tool','visible':True})
        self.host.respondApproval(True)
        self.assertTrue(self.manager.replies[identifier]['ok'])
        self.assertEqual(changed,[('local_tool',True)])

    def test_tool_details_are_paginated_and_tags_bounded(self):
        self.manager.b._view.resources={'allTools':[{'name':'tool_'+str(n),'description':'x'*8000,'source':'builtin:fixture17'} for n in range(95)]}
        self.manager.b.piManagement.extensions[17]['enabled']=True
        identifier=self.request('pi.status',{'details':'17','toolOffset':40})
        result=self.manager.replies[identifier]['result']
        self.assertEqual(len(result['tools']),40);self.assertEqual(result['toolTotal'],95)
        self.assertEqual(result['tools'][0]['name'],'tool_40');self.assertTrue(result['toolsHasMore'])
        self.assertEqual(len(result['extensions'][0]['tools']),12)

    def test_real_visibility_persists_only_in_target_session_and_retires_its_runtime(self):
        from app.controller import Controller
        from app.pi_sessions import SessionState, clean_blocked_tools
        from app.storage import Store
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ,{'UMEKO_DATA_DIR':temp}):
            controller=Controller(root)
            try:
                owner=controller._view;owner.id='visibility-owner'
                owner.resources={'allTools':[{'name':'write','source':'builtin:write','exposure':'direct'}]}
                with patch.object(controller._pool,'retire') as retire:
                    controller.piManagement.set_tool_visible('write',False)
                    retire.assert_called_once_with(owner)
                self.assertEqual(owner.blocked_tools,['write'])
                self.assertEqual(Store().data['sessionMeta'][owner.id]['blockedTools'],['write'])
                self.assertNotIn('blockedTools',controller.store.data['agent'])
                self.assertFalse(owner.resources['allTools'][0]['visible'])
                control=controller._umeko_control
                control._native[owner.key]=('visibility-list','reload');control.jobs['visibility-list']={}
                control._native_event(owner,{'type':'resources','resources':owner.resources})
                self.assertEqual(control.jobs['visibility-list']['resources']['allTools'],[])
                control._native.pop(owner.key)
                other=SessionState()
                self.assertEqual(other.blocked_tools,[])
                owner.subagents_active=True
                with self.assertRaises(ValueError): controller.piManagement.set_tool_visible('write',True)
                owner.subagents_active=False
                with patch.object(controller.store,'save',side_effect=OSError('disk full')):
                    with self.assertRaises(ValueError):controller.piManagement.set_tool_visible('write',True)
                self.assertEqual(owner.blocked_tools,['write'])
                controller.piManagement.set_tool_visible('write',True)
                self.assertEqual(Store().data['sessionMeta'][owner.id]['blockedTools'],[])
                self.assertEqual(clean_blocked_tools(['write','*','write',{},'bad name']),['write'])
            finally:controller.close()

    def test_previous_workspace_inventory_is_not_returned_as_current(self):
        self.manager.b.piManagement.extensionsCurrent = False
        identifier = self.request('pi.status')
        result = self.manager.replies[identifier]['result']
        self.assertFalse(result['contextCurrent'])
        self.assertEqual(result['extensions'], [])

    def test_types_permissions_and_stale_targets_fail_before_dispatch(self):
        for args in ({'limit': True}, {'offset': -1}, {'limit': 201}, {'secret': 'x'}):
            identifier = self.request('pi.status', args)
            self.assertFalse(self.manager.replies[identifier]['ok'])
        self.manager.entries['a']['permissions'] = []
        identifier = self.request('pi.scan')
        self.assertFalse(self.manager.replies[identifier]['ok'])
        self.manager.entries['a']['permissions'] = ['pi.read', 'pi.manage']
        identifier = self.request('pi.scan', session={'token': 'old', 'workspace': '/fixture'})
        self.assertFalse(self.manager.replies[identifier]['ok'])
        identifier = self.request('pi.enable', {'id': 'x', 'enabled': 'true'})
        self.assertFalse(self.manager.replies[identifier]['ok'])
        self.assertEqual(self.manager.calls, [])

    def test_native_confirmation_decline_and_workspace_recheck(self):
        identifier = self.request('pi.install', {'source': 'npm:fixture@1.0.0'})
        self.assertEqual(self.host.pendingApproval['id'], identifier)
        self.assertEqual(self.manager.calls, [])
        self.host.respondApproval(False)
        self.assertEqual(self.manager.replies[identifier]['status'], 'declined')
        identifier = self.request('pi.enable', {'id': 'fixture', 'enabled': False})
        self.manager._session['workspace'] = '/changed'
        self.host.respondApproval(True)
        self.assertFalse(self.manager.replies[identifier]['ok'])
        self.assertEqual(self.manager.calls, [])

    def test_jobs_are_owned_by_widget_instance_and_chat_and_results_are_small(self):
        self.request('pi.scan')
        identifier = self.request('pi.job', {'id': 'job-one'}, widget='b')
        self.assertFalse(self.manager.replies[identifier]['ok'])
        identifier = self.request('pi.job', {'id': 'job-one'})
        job = self.manager.replies[identifier]['jobs'][0]
        self.assertEqual(job['status'], 'done')
        self.assertEqual(job['result'], {'ok': True})
        self.manager.workers['a'] = {'ready': True}
        identifier = self.request('pi.job', {'id': 'job-one'})
        self.assertFalse(self.manager.replies[identifier]['ok'])

    def test_confirmed_write_reuses_existing_control_job_without_queueing(self):
        identifier = self.request('pi.enable', {'id': 'fixture', 'enabled': False})
        self.host.respondApproval(True)
        self.assertEqual(self.manager.replies[identifier]['status'], 'accepted')
        self.assertEqual(self.manager.calls, [{'operation': 'extensions.enable',
                                             'arguments': {'id': 'fixture', 'enabled': False}}])
        self.assertIn('job-one', self.host.jobs)
        self.host.stop('a')
        self.assertFalse(self.host.jobs)

    def test_bounded_pending_requests_and_stop_revoke_unconfirmed_work(self):
        value = {'operation': 'pi.status', 'session': self.manager._session}
        identifiers = [self.host.request_for('a', value) for _ in range(9)]
        self.assertTrue(all(identifiers[:8]))
        self.assertEqual(identifiers[8], '')
        self.host.stop('a')
        self.app.processEvents()
        self.assertFalse(self.manager.replies)
        identifier = self.request('pi.install', {'source': 'npm:fixture@1.0.0'})
        self.host.stop('a')
        self.assertEqual(self.manager.replies[identifier]['status'], 'declined')
        self.assertEqual(self.manager.calls, [])

    def test_busy_agent_cannot_turn_widget_admin_into_an_install_bypass(self):
        self.manager.b.busy = True
        identifier = self.request('pi.install', {'source': 'npm:fixture@1.0.0'})
        self.assertIn('run_pi_command', self.manager.replies[identifier]['error'])
        self.assertFalse(self.host.pendingApproval)
        self.assertEqual(self.manager.calls, [])

    def test_real_control_rejects_agent_install_but_accepts_confirmed_host_install(self):
        from app.controller import Controller
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'UMEKO_DATA_DIR':temp}):
            controller = Controller(root)
            controller.store.data['agent']['agentDir'] = str(Path(temp)/'agent')
            package = Path(temp)/'confirmed package'
            (package/'extensions').mkdir(parents=True)
            file = package/'extensions/example.ts'
            file.write_text("throw new Error('do not execute during discovery'); export default () => {};", encoding='utf-8')
            try:
                control = controller._umeko_control
                args = {'source':str(package), 'project':False}
                for request in ({'operation':'extensions.install','arguments':args},
                    {'operation':'extensions.install','arguments':args,'origin':'widget'},
                    {'operation':'extensions.install','arguments':{**args,'origin':'widget'}}):
                    self.assertFalse(control.execute(request,controller._view)['ok'])
                self.manager.b = self.host.b = controller
                self.manager._session = {'token':controller._view.key,'id':controller._view.id,'workspace':controller._view.workspace}
                with patch.object(controller,'_job') as job:
                    identifier = self.request('pi.install',args)
                    self.assertFalse(job.called)
                    self.host.respondApproval(True)
                    self.assertTrue(self.manager.replies[identifier]['ok'],self.manager.replies[identifier])
                    self.assertEqual(job.call_args.args[0],'pi-admin:install')
                    controller.piManagement._finished('pi-admin:install',{'ok':True,'value':job.call_args.args[1]()})
                self.assertEqual(controller.piManagement.installState,'succeeded')
                self.assertTrue(any(row['path']==str(file) for row in controller.piManagement.extensions))
            finally:
                controller.close()

    def test_activity_is_opt_in_bounded_metadata_without_arguments_or_transcripts(self):
        class NoTranscript:
            def __iter__(self): raise AssertionError('A Widget observer scanned chat history')
        record = SimpleNamespace(key='origin',id='original',workspace='/original',messages=NoTranscript(),
            resources={'allTools':[{'name':'fixture','source':'/plugin/fixture.mjs'}]})
        event={'type':'tool','id':'call','name':'fixture','state':'done','args':{'key':'private-secret'},'result':'private-output'}
        self.host.observe(record,event)
        self.assertFalse(self.host.activity)
        self.manager.entries['a']['permissions'].append('pi.observe')
        for n in range(100): self.host.observe(record,{**event,'id':str(n)})
        self.host._flush_activity()
        frame=self.manager.frames[-1]
        self.assertEqual(frame[0],'a')
        data=frame[1]['arguments']['data']
        self.assertGreater(data['dropped'],0)
        self.assertLessEqual(len(data['events']),64)
        self.assertLess(len(json.dumps(data).encode()),65536)
        self.assertEqual(data['events'][0]['session']['token'],'origin')
        self.assertNotIn('private-secret',json.dumps(data))
        self.assertNotIn('private-output',json.dumps(data))
        self.assertEqual(data['events'][0]['source'],'/plugin/fixture.mjs')

    def test_network_overrides_expose_only_the_public_npm_fields(self):
        identifier = self.request('pi.network')
        result = self.manager.replies[identifier]['result']
        self.assertEqual(set(result), {'npmRegistry','npmUserconfig','npmCafile'})
        self.assertNotIn('must-not-leak', str(result))

    def test_host_node_runtime_does_not_require_node_on_path_or_inherit_injection(self):
        from app.pi_runtime import node_executable
        with tempfile.TemporaryDirectory() as directory:
            context = Context(Path(directory), Path(directory), {}, self.manager._session,
                ['process.execute'], executables={'node':{'runtime':'node'}},
                lifecycle='application', runtimes={'node':{'executable':node_executable()}})
            with patch.dict(os.environ, {'NODE_OPTIONS':'--require /forbidden', 'NODE_PATH':'/forbidden', 'FIXTURE_API_KEY':'private'}):
                result=context.run_executable('node',['-e','console.log(JSON.stringify({cwd:process.cwd(), injected:process.env.NODE_OPTIONS,secret:process.env.FIXTURE_API_KEY}))'],timeout=3)
            self.assertEqual(result['code'],0)
            payload=json.loads(result['text'])
            self.assertEqual(set(payload), {'cwd'})
            self.assertEqual(Path(payload['cwd']).resolve(), Path(directory).resolve())

    def test_sdk_request_is_nonblocking_and_requires_explicit_application_target(self):
        with tempfile.TemporaryDirectory() as directory:
            events = []
            context = Context(Path(directory), Path(directory), {}, self.manager._session,
                ['pi.read'], emit=events.append, lifecycle='application',
                host_capabilities=self.host.capabilities)
            with self.assertRaises(PluginError): context.request_host('pi.status')
            target = context.capture_session()
            identifier = context.request_host('pi.status', session=target)
            self.assertEqual(events[0]['arguments']['id'], identifier)
            self.assertEqual(events[0]['arguments']['session'], target)
            with self.assertRaises(PluginError):
                context.request_host('pi.install', {'source': 'x'}, session=target)
            with self.assertRaises(PluginError):
                context.request_host('pi.status', {'large': 'x' * 20000}, session=target)

    def test_checkpoint_lock_is_workspace_scoped_and_rejects_running_tasks(self):
        self.manager.bridge = SimpleNamespace(workspace=lambda value: os.path.normcase(os.path.abspath(value)) if value else '')
        self.manager.entries['change-review'] = {'name': 'Review', 'permissions': ['workspace.write']}
        self.manager.workers['change-review'] = {'ready': True}
        self.manager.b._pool = SimpleNamespace(records={})
        identifier = self.request('checkpoints.acquire', {'id': 'a' * 32}, widget='change-review')
        reply = self.manager.replies[identifier]
        self.assertTrue(reply['ok'], reply)
        token = reply['result']['token']
        self.assertTrue(self.host.workspace_locked('/fixture'))
        second = self.request('checkpoints.acquire', {'id': 'b' * 32}, widget='change-review')
        self.assertFalse(self.manager.replies[second]['ok'])
        wrong = self.request('checkpoints.release', {'token': 'c' * 32}, widget='change-review')
        self.assertFalse(self.manager.replies[wrong]['ok'])
        released = self.request('checkpoints.release', {'token': token}, widget='change-review')
        self.assertTrue(self.manager.replies[released]['ok'])
        self.assertFalse(self.host.workspace_locked('/fixture'))
        self.manager.b._pool.records['busy'] = SimpleNamespace(busy=True, workspace='/fixture', title='running')
        busy = self.request('checkpoints.acquire', {'id': 'b' * 32}, widget='change-review')
        self.assertFalse(self.manager.replies[busy]['ok'])
        self.manager.b._pool.records.clear()
        acquired = self.request('checkpoints.acquire', {'id': 'b' * 32}, widget='change-review')
        self.assertTrue(self.manager.replies[acquired]['ok'])
        self.host.stop('change-review')
        self.assertFalse(self.host.workspace_locked('/fixture'))

    def test_checkpoint_lock_rejects_background_writers_and_notifies_runtime(self):
        self.manager.bridge = SimpleNamespace(workspace=lambda value: os.path.normcase(os.path.abspath(value)) if value else '')
        self.manager.entries['change-review'] = {'name': 'Review', 'permissions': ['workspace.write']}
        self.manager.workers['change-review'] = {'ready': True}
        record = SimpleNamespace(busy=False, workspace='/fixture', title='idle', process=object(), ready=True, stale=False, global_agent='')
        notifications = []
        jobs = [{'cwd': '/fixture/nested', 'status': 'running'}]
        pool = SimpleNamespace(records={'idle': record})
        pool.query_catalog = lambda record, kind, callback: (callback({'ok': True, 'value': {'jobs': jobs}}), True)[1]
        pool.write = lambda record, payload: notifications.append(payload)
        self.manager.b._pool = pool
        blocked = self.request('checkpoints.acquire', {'id': 'a' * 32}, widget='change-review')
        self.assertIn('后台任务', self.manager.replies[blocked]['error'])
        self.assertFalse(self.host.workspace_locked('/fixture'))
        jobs.clear()
        acquired = self.request('checkpoints.acquire', {'id': 'b' * 32}, widget='change-review')
        reply = self.manager.replies[acquired]
        self.assertTrue(reply['ok'], reply)
        self.assertEqual(notifications[-1], {'type': 'checkpoint_lock', 'locked': True})
        released = self.request('checkpoints.release', {'token': reply['result']['token']}, widget='change-review')
        self.assertTrue(self.manager.replies[released]['ok'])
        self.assertEqual(notifications[-1], {'type': 'checkpoint_lock', 'locked': False})

    def test_task_check_returns_counts_time_and_scoped_file_preview(self):
        from app.task_records import TaskStore, versions_of
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            store=TaskStore(root/'tasks.sqlite3')
            task=store.create('Report','Local only',str(root))
            attempt=store.begin(task,str(root),'','',[])
            first=root/'report.md'; first.write_text('# Report')
            second=root/'changed.md'; second.write_text('original')
            store.files(attempt,'submitted','delivery',versions_of([{'path':str(first)},{'path':str(second)}]))
            second.write_text('revised')
            manager=self.manager
            manager.b._task_records=SimpleNamespace(_storage=lambda:store,store=store)
            manager.b._view.key=manager._session['token']
            manager._page='task-records'
            manager.entries['task-records']={'builtin':True,'permissions':['tasks.manage']}
            manager.workers['task-records']={'ready':True}
            manager.b.widgetDocumentRequested=Mock()
            pending={}
            manager.b._job=lambda name,run:pending.update({name:run})
            def request(operation,args):
                key=self.host.request_for('task-records',{'operation':operation,'arguments':args,'session':dict(manager._session)},page=True)
                self.app.processEvents()
                return key
            key=request('tasks.verify',{'taskId':task,'attemptId':attempt})
            self.host.task_result(key,{'ok':True,'value':pending['task-details:'+key]()})
            result=manager.replies[key]['result']
            self.assertEqual(result['counts'],{'available':1,'changed':1})
            self.assertEqual(result['total'],2)
            self.assertTrue(result['checked'])
            self.assertIsNone(store.details(task,attempt)['accepted'])
            file_id=store.details(task,attempt)['files'][0]['id']
            key=request('tasks.preview',{'taskId':task,'attemptId':attempt,'fileId':file_id})
            self.assertTrue(manager.replies[key]['ok'])
            manager.b.widgetDocumentRequested.emit.assert_called_once_with(str(first),'report.md','file','task-records')
            key=request('tasks.preview',{'taskId':'f'*32,'attemptId':attempt,'fileId':file_id})
            self.assertFalse(manager.replies[key]['ok'])
            self.assertEqual(manager.b.widgetDocumentRequested.emit.call_count,1)

    def test_returning_to_task_chat_requires_preparation_and_does_not_send(self):
        from app.task_records import TaskStore
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            store=TaskStore(Path(directory)/'tasks.sqlite3')
            task=store.create('Report','Local only',directory)
            manager=self.manager
            manager.b._task_records=SimpleNamespace(_storage=lambda:store)
            manager.b._view.key=manager._session['token']
            manager.b._view.prepared_task=''
            manager._page='task-records'
            manager.entries['task-records']={'builtin':True,'permissions':['tasks.manage']}
            manager.workers['task-records']={'ready':True}
            manager.closePage=Mock()
            manager.b.send=Mock()
            def request():
                key=self.host.request_for('task-records',{'operation':'tasks.chat','arguments':{'taskId':task},'session':dict(manager._session)},page=True)
                self.app.processEvents();return key
            self.assertFalse(manager.replies[request()]['ok'])
            manager.b._view.prepared_task=task
            key=request();self.app.processEvents()
            self.assertTrue(manager.replies[key]['ok'])
            manager.closePage.assert_called_once()
            manager.b.send.assert_not_called()


class WidgetHostWorkerTests(unittest.TestCase):
    def test_real_worker_returns_before_host_reply_and_keeps_original_chat(self):
        import queue
        import subprocess
        import threading
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.Popen([sys.executable, '-B', str(root/'plugin-runtime/worker.py')],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8')
            frames = queue.Queue()
            reader = threading.Thread(target=lambda: [frames.put(json.loads(line)) for line in process.stdout], daemon=True)
            reader.start()
            def send(identifier, operation, arguments):
                process.stdin.write(json.dumps({'id':identifier,'operation':operation,'arguments':arguments})+'\n')
                process.stdin.flush()
            def receive():
                return frames.get(timeout=5)
            try:
                target={'token':'original','id':'original-id','workspace':directory}
                send('init','initialize',{'path':str(root/'plugin-runtime/examples/pi-management'),
                    'stateDir':directory,'session':target,'hostCapabilities':{'version':1,
                    'operations':{'pi.status':{'permission':'pi.read'}}}})
                self.assertTrue(receive()['ok'])
                send('widget-rpc','agentCall',{'method':'inventory','arguments':{},'session':target})
                event, response = receive(), receive()
                self.assertEqual(event['event'],'host.request')
                self.assertEqual(response['id'],'widget-rpc')
                self.assertEqual(response['result']['status'],'accepted')
                identifier=event['arguments']['id']
                send('switch','session',{'session':{'token':'other','id':'other-id','workspace':'/other'}})
                self.assertTrue(receive()['ok'])
                send('delivery','event',{'name':'host.response','data':{'requestId':identifier,
                    'operation':'pi.status','ok':True,'result':{'total':1,'contextCurrent':True,
                    'extensions':[{'id':'fixture','name':'example','scope':'global','enabled':True}]}}})
                notification, receipt=receive(),receive()
                self.assertEqual(notification['event'],'agent.notify')
                self.assertEqual(notification['arguments']['session'],target)
                self.assertEqual(notification['arguments']['requestId'],'widget-rpc')
                self.assertFalse(notification['arguments']['wake'])
                self.assertTrue(receipt['ok'])
            finally:
                process.stdin.close()
                try: process.wait(timeout=3)
                except subprocess.TimeoutExpired: process.kill();process.wait(timeout=3)
                reader.join(timeout=1)
                process.stdout.close();process.stderr.close()


if __name__ == '__main__': unittest.main()
