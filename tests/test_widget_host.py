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

    def __init__(self):
        super().__init__()
        management = SimpleNamespace(busy=False, status='idle', extensionUpdate={}, extensionDetails={}, extensionsCurrent=True, npmConfig={'npmRegistry':'https://registry.example/','npmUserconfig':'/fixture/npmrc','npmCafile':'/fixture/ca.pem','privateKey':'must-not-leak'},
            extensions=[{'id': str(n), 'path':'builtin:fixture'+str(n), 'name': 'fixture', 'info':{'description':'Local example'}} for n in range(250)],
            uninstallPackage=lambda identifier: None)
        self.calls, self.frames, self.replies = [], [], {}
        self.b = SimpleNamespace(piManagement=management, busy=False, kernelBusy=False,
            pendingApproval={}, _view=SimpleNamespace(extension_modes={}, resources={}), _umeko_control=SimpleNamespace(execute=self.execute))
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
        self.assertEqual(len(result['tools'][0]['description']),4096)
        identifier=self.request('pi.details',{'id':'missing'})
        self.assertFalse(self.manager.replies[identifier]['ok'])

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

    def test_required_abilities_are_rejected_before_confirmation(self):
        self.manager.b.piManagement.extensions[17]['info']['required']=True
        for operation,args in [('pi.activation',{'id':'17','mode':'disabled'}),('pi.enable',{'id':'17','enabled':False})]:
            identifier=self.request(operation,args)
            self.assertFalse(self.manager.replies[identifier]['ok'])
            self.assertFalse(self.host.pendingApproval)
        self.assertEqual(self.manager.calls,[])

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
