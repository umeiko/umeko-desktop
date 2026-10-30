"""Desktop plugin ZIP, worker, session boundary and bounded demo regressions."""
import copy, importlib.util, json, os, shutil, stat, subprocess, sys, tempfile, time, unittest, zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'plugin-runtime'))
from umeko_plugin_sdk import Context, PluginError
from umeko_plugin_sdk.packages import install, validate
from PySide6.QtCore import QObject, Signal, QCoreApplication, QUrl
from app.desktop_plugins import DesktopPlugins

class Pool(QObject):
    event=Signal(object,object)
    def __init__(self,record):super().__init__();self.records={record.key:record}
    def find(self,identifier):return next((row for row in self.records.values() if row.id==identifier),None)

class Host(QObject):
    viewChanged=Signal();chatChanged=Signal();toast=Signal(str);documentRequested=Signal(str,str,str)
    def __init__(self,directory):
        super().__init__();self.root=ROOT;self.store=SimpleNamespace(directory=directory/'profile')
        self._view=SimpleNamespace(key='token-one',id='session-one',workspace=str(directory/'workspace'),title='Fixture',busy=False,messages=[{'role':'user','text':'fixture context'}])
        self._pool=Pool(self._view)
        Path(self._view.workspace).mkdir();self.sent=[];self.attached=[];self.revealed=[]
    def send(self,text):self.sent.append((self._view.id,text,False))
    def steer(self,text):self.sent.append((self._view.id,text,True))
    def attachChatboxFile(self,path):self.attached.append(path)
    def openChatboxPath(self,path,reveal):self.revealed.append((path,reveal))

class DesktopPluginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QCoreApplication.instance() or QCoreApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name).resolve()
        self.host=Host(self.path);self.manager=DesktopPlugins(self.host);self.addCleanup(self.manager.close)
        self.responses={};self.manager.response.connect(lambda key,value:self.responses.__setitem__(key,value))
    def wait(self,predicate):
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            self.app.processEvents()
            if predicate():return
            time.sleep(.01)
        self.fail('Plugin operation timed out: '+self.manager.status+' '+str(self.manager.page))
    def call(self,method,args=None):
        key=self.manager.call(method,json.dumps(args or {}));self.assertTrue(key)
        self.wait(lambda:key in self.responses);return self.responses[key]
    def fixture(self,identifier='session-demo',version='1.0.0',config=None,lifecycle='session'):
        folder=self.path/(identifier+'-'+version);shutil.copytree(ROOT/'umeko-plugins/file-tree',folder)
        manifest=json.loads((folder/'manifest.json').read_text());manifest.update(id=identifier,version=version,builtin=True,permissions=['workspace.read','session.read','session.write'])
        manifest['agent']['methods']={'rpc':{'description':'Return supplied data and publish progress','parameters':{'type':'object','properties':{'value':{'type':'string','maxLength':8}},'required':['value'],'additionalProperties':False}}}
        manifest['lifecycle']=lifecycle
        if lifecycle=='application':
            manifest.pop('page',None)
            for name in ('capture','notifySaved','delayed'):
                manifest['agent']['methods'][name]={'description':name,'parameters':{'type':'object','properties':{},'additionalProperties':False}}
        (folder/'manifest.json').write_text(json.dumps(manifest))
        marker=self.path/'activated'
        (folder/'scripts/plugin.py').write_text('from pathlib import Path\nfrom umeko_plugin_sdk import Plugin\nimport time\n'+f'Path({str(marker)!r}).write_text("activated")\n'+'''class Fixture(Plugin):
    def handle(self,method,args):
        if method=='rpc':
            message=self.context.notify_agent('inspection progress',data={'value':args['value']})
            self.context.publish('inspection',{'value':args['value']})
            return {'request':self.context.request_id,'source':self.context.call_source,'value':args['value'],'messageId':message,'stateDir':str(self.context.state_dir),'workspace':str(self.context.workspace)}
        if method=='capture':
            self.saved=self.context.capture_session()
            return self.saved
        if method=='notifySaved':
            self.context.notify_agent('saved target update',session=self.saved,request_id='')
            return {'sent':True}
        if method=='delayed':
            self.context.notify_agent('delayed begin')
            time.sleep(.7)
            self.context.notify_agent('delayed complete',data={'workspace':str(self.context.workspace)})
            return {'workspace':str(self.context.workspace)}
        if method=='late':time.sleep(.7)
        self.context.send_message('from-plugin',True)
        return {'session':self.context.session['id'],'messages':len(self.context.session.get('messages',[]))}
def create_plugin(context):return Fixture(context)
''')
        if config is not None:(folder/'config.schema.json').write_text(json.dumps(config))
        archive=self.path/(identifier+'-'+version+'.zip')
        with zipfile.ZipFile(archive,'w') as stream:
            for p in folder.rglob('*'):
                if p.is_file():stream.write(p,p.relative_to(folder).as_posix())
        return archive,marker
    def test_official_tree_is_lazy_bounded_and_closes_worker(self):
        directory=Path(self.host._view.workspace);(directory/'a.py').write_text('print(1)');(directory/'nested').mkdir();(directory/'nested/x.txt').write_text('hello')
        self.assertEqual(len(self.manager.sessionPlugins),2)
        self.assertTrue(self.manager.openPage('file-tree'));result=self.call('list',{'path':'.'})
        self.assertTrue(result['ok']);entries=result['result']['entries'];self.assertEqual(entries[0]['name'],'nested')
        self.assertNotIn('x.txt',str(entries))
        self.assertNotIn('messages',self.manager.session)
        self.assertFalse(self.call('list',{'path':'..'})['ok'])
        self.manager.closePage();self.assertEqual(set(self.manager.workers),{'desktop-pet'});self.app.processEvents()

    def desktop_control(self):
        from app.umeko_control import UmekoControl
        control=UmekoControl.__new__(UmekoControl);QObject.__init__(control)
        control.b=self.host;control.jobs={}
        control.operations=json.loads((ROOT/'runtime/umeko-operations.json').read_text(encoding='utf-8'))['operations']
        self.host.desktopPlugins=self.manager
        return control

    def test_widget_agent_rpc_discovery_schema_progress_result_and_session_scope(self):
        archive,_=self.fixture();self.manager.importZip(QUrl.fromLocalFile(str(archive)).toString());self.wait(lambda:not self.manager.busy)
        control=self.desktop_control()
        self.assertFalse(control.execute({'operation':'widgets.call','arguments':{'id':'session-demo','method':'rpc','arguments':{'value':'yes'}}})['ok'])
        control.execute({'operation':'widgets.activate','arguments':{'id':'session-demo','enabled':True}})
        self.manager.openPage('session-demo')
        docs=control.execute({'operation':'widgets.docs','arguments':{'id':'session-demo'}})
        self.assertTrue(docs['ok']);self.assertIn('rpc',docs['methods']);self.assertTrue(Path(docs['document']['path']).is_file())
        published=[];self.manager.event.connect(lambda name,data:published.append((name,data)))
        rejected=control.execute({'operation':'widgets.call','arguments':{'id':'session-demo','method':'private','arguments':{}}})
        self.assertFalse(rejected['ok'])
        invalid=control.execute({'operation':'widgets.call','arguments':{'id':'session-demo','method':'rpc','arguments':{'value':'too-long-input'}}})
        self.wait(lambda:self.manager.bridge.calls[invalid['requestId']]['status']!='running')
        self.assertFalse(self.manager.bridge.calls[invalid['requestId']]['result']['ok'])
        accepted=control.execute({'operation':'widgets.call','arguments':{'id':'session-demo','method':'rpc','arguments':{'value':'yes'}}})
        self.assertEqual(accepted['status'],'accepted');request=accepted['requestId']
        self.wait(lambda:self.manager.bridge.calls[request]['status']=='completed')
        value=control.execute({'operation':'widgets.result','arguments':{'requestId':request}})
        self.assertEqual(value['result']['result']['request'],request);self.assertEqual(value['result']['result']['source'],'agent')
        self.assertEqual(value['updates'][0]['data'],{'value':'yes'});self.assertEqual(value['updates'][0]['requestId'],request)
        self.assertIn(('inspection',{'value':'yes'}),published)
        self.assertEqual(control.jobs[accepted['jobId']]['status'],'done')
        updates=control.execute({'operation':'widgets.messages','arguments':{'id':'session-demo','after':0,'limit':1}})
        self.assertEqual(updates['updates'][0]['message'],'inspection progress')
        self.assertEqual(control.execute({'operation':'widgets.messages','arguments':{'after':updates['nextCursor']}})['updates'],[])
        self.assertFalse(control.execute({'operation':'widgets.list','arguments':{'activeOnly':'true'}})['ok'])
        other=copy.copy(self.host._view)
        self.assertFalse(control.execute({'operation':'widgets.docs','arguments':{'id':'session-demo'}},other)['ok'])
        self.host._view.key='token-two';self.host._view.id='session-two';self.host.viewChanged.emit()
        self.assertFalse(control.execute({'operation':'widgets.result','arguments':{'requestId':request}})['ok'])
        self.assertFalse(control.execute({'operation':'jobs.get','arguments':{'id':accepted['jobId']}})['ok'])
        self.assertEqual(control.execute({'operation':'widgets.messages'})['updates'],[])

    def test_widget_management_uses_observable_jobs_and_preserves_failed_config(self):
        archive,_=self.fixture();control=self.desktop_control()
        accepted=control.execute({'operation':'widgets.import','arguments':{'path':str(archive)}})
        self.assertEqual(accepted['status'],'accepted')
        self.wait(lambda:control.jobs[accepted['jobId']]['status']!='running')
        self.assertEqual(control.jobs[accepted['jobId']]['status'],'done')
        self.assertIn('session-demo',self.manager.entries)
        failed=control.execute({'operation':'widgets.config','arguments':{'id':'session-demo','config':{'showHidden':'bad'}}})
        self.wait(lambda:control.jobs[failed['jobId']]['status']!='running')
        self.assertEqual(control.jobs[failed['jobId']]['status'],'failed')
        self.assertNotEqual(self.manager.settings['config']['session-demo'].get('showHidden'),'bad')
        saved=control.execute({'operation':'widgets.config','arguments':{'id':'session-demo','config':{'showHidden':True,'directoryLimit':200}}})
        self.wait(lambda:control.jobs[saved['jobId']]['status']!='running')
        self.assertEqual(control.jobs[saved['jobId']]['status'],'done')
        self.assertIs(self.manager.settings['config']['session-demo']['showHidden'],True)
        self.assertTrue(control.execute({'operation':'widgets.uninstall','arguments':{'id':'session-demo'}})['ok'])
        self.assertNotIn('session-demo',self.manager.entries)

    def test_widget_notification_push_is_separate_from_editor_and_has_delivery_receipts(self):
        self.host._view.ready=True;self.host._view.phase='running';self.host._view.busy=True
        self.host._view.draft='keep this draft';self.host._view.attachments=['keep attachment'];frames=[]
        self.host._write_pi=lambda frame,record:frames.append((record.key,frame))
        self.manager.openPage('file-tree');self.wait(lambda:self.manager.workers['file-tree']['ready'])
        update={'id':'a'*32,'message':'new result','data':{'count':2},'requestId':'','wake':True}
        self.manager.host_event('file-tree',{'event':'agent.notify','arguments':update})
        self.assertEqual(len(frames),1);self.assertEqual(frames[0][1]['type'],'widget-notify')
        self.assertEqual(self.host._view.draft,'keep this draft');self.assertEqual(self.host._view.attachments,['keep attachment']);self.assertFalse(self.host.sent)
        self.manager.bridge.pi_event(self.host._view,{'type':'widget_delivery','id':'a'*32,'status':'delivered'})
        self.assertEqual(self.manager.bridge.messages[0]['delivery'],'delivered')
        self.manager.host_event('file-tree',{'event':'agent.notify','arguments':update});self.assertEqual(len(frames),1)
        old=copy.copy(self.host._view);self.host._view.key='other-token';self.host._view.id='other-session';self.host.viewChanged.emit()
        self.manager.bridge.pi_event(old,{'type':'widget_delivery','id':'a'*32,'status':'failed'})
        self.assertEqual(self.manager.bridge.messages,[])
        self.host._view.key=old.key;self.host._view.id=old.id;self.host.viewChanged.emit()
        self.assertEqual(self.manager.bridge.messages[0]['delivery'],'delivered')

    def test_widget_zip_requires_short_summary_complete_docs_and_valid_public_schema(self):
        self.fixture();folder=self.path/'session-demo-1.0.0';manifest_path=folder/'manifest.json'
        original=json.loads(manifest_path.read_text())
        for patch_value in ({'summary':''},{'summary':'x'*21},{'agent':{}},{'agent':{'document':'../outside.md'}},{'agent':{'document':'AGENT.md','methods':{'bad':{'description':'bad','parameters':{'type':'object','pattern':'unsupported'}}}}}):
            with self.subTest(value=patch_value):
                manifest_path.write_text(json.dumps({**original,**patch_value}))
                with self.assertRaises((PluginError,ValueError)):validate(folder)
        manifest_path.write_text(json.dumps(original));(folder/'AGENT.md').write_text('')
        with self.assertRaisesRegex(PluginError,'Markdown'):validate(folder)

    def test_application_service_is_inert_until_enabled_survives_navigation_and_restarts_with_app(self):
        archive,marker=self.fixture(lifecycle='application');self.manager.importZip(QUrl.fromLocalFile(str(archive)).toString());self.wait(lambda:not self.manager.busy)
        self.assertFalse(marker.exists());self.assertFalse(self.manager.enabled('session-demo'));self.assertNotIn('session-demo',self.manager.workers)
        control=self.desktop_control();control.execute({'operation':'widgets.enable','arguments':{'id':'session-demo','enabled':True}})
        self.wait(lambda:self.manager.workers['session-demo']['ready'])
        worker=self.manager.workers['session-demo'];pid=worker['process'].processId()
        self.assertEqual(worker['token'],self.manager.application_token);self.assertTrue(marker.exists())
        second=copy.copy(self.host._view);second.key='second-token';second.id='second-session';second.workspace=str(self.path/'second');Path(second.workspace).mkdir()
        self.host._pool.records[second.key]=second;self.host._view=second;self.host.viewChanged.emit()
        self.assertIs(self.manager.workers['session-demo'],worker);self.assertEqual(worker['process'].processId(),pid)
        self.manager.openPage('file-tree');self.manager.closePage();self.assertIs(self.manager.workers['session-demo'],worker)
        rows=control.execute({'operation':'widgets.list','arguments':{'activeOnly':True}})['widgets']
        service=next(row for row in rows if row['id']=='session-demo');self.assertEqual(service['lifecycle'],'application');self.assertTrue(service['active'])
        self.assertNotIn('session-demo',[row['id'] for row in self.manager.sessionPlugins])
        self.manager.close();restarted=DesktopPlugins(self.host);self.addCleanup(restarted.close)
        self.wait(lambda:restarted.workers.get('session-demo',{}).get('ready'))
        self.assertNotEqual(restarted.workers['session-demo']['process'].processId(),pid)
        restarted.setEnabled('session-demo',False);self.assertNotIn('session-demo',restarted.workers)

    def test_application_rpc_and_background_push_remain_bound_to_original_chat(self):
        archive,_=self.fixture(lifecycle='application');self.manager.importZip(QUrl.fromLocalFile(str(archive)).toString());self.wait(lambda:not self.manager.busy)
        control=self.desktop_control();control.execute({'operation':'widgets.enable','arguments':{'id':'session-demo','enabled':True}})
        self.wait(lambda:self.manager.workers['session-demo']['ready'])
        first=self.host._view;first.ready=True;first.busy=True;first.phase='running'
        frames=[];self.host._write_pi=lambda frame,record:frames.append((record.key,frame))
        capture=control.execute({'operation':'widgets.call','arguments':{'id':'session-demo','method':'capture'}})
        self.wait(lambda:self.manager.bridge.calls[capture['requestId']]['status']=='completed')
        delayed=control.execute({'operation':'widgets.call','arguments':{'id':'session-demo','method':'delayed'}})
        self.wait(lambda:any(row['message']=='delayed begin' for row in self.manager.bridge.messages))
        worker=self.manager.workers['session-demo']
        second=SimpleNamespace(key='second-token',id='second-session',workspace=str(self.path/'second'),title='Second',busy=True,phase='running',ready=True,messages=[],draft='untouched',attachments=['untouched'])
        Path(second.workspace).mkdir();self.host._pool.records[second.key]=second;self.host._view=second;self.host.viewChanged.emit()
        self.assertIs(self.manager.workers['session-demo'],worker)
        self.wait(lambda:self.manager.bridge.calls[delayed['requestId']]['status']=='completed')
        result=control.execute({'operation':'widgets.result','arguments':{'requestId':delayed['requestId']}},first)
        self.assertTrue(result['ok']);self.assertEqual(result['result']['result']['workspace'],first.workspace)
        self.assertEqual([row['message'] for row in result['updates']],['delayed begin','delayed complete'])
        self.assertFalse(control.execute({'operation':'widgets.result','arguments':{'requestId':delayed['requestId']}},second)['ok'])
        rpc=control.execute({'operation':'widgets.call','arguments':{'id':'session-demo','method':'rpc','arguments':{'value':'first'}}},first)
        self.wait(lambda:self.manager.bridge.calls[rpc['requestId']]['status']=='completed')
        info=self.manager.bridge.calls[rpc['requestId']]['result']['result']
        self.assertEqual(info['workspace'],first.workspace);self.assertEqual(Path(info['stateDir']).name,'application')
        saved=control.execute({'operation':'widgets.call','arguments':{'id':'session-demo','method':'notifySaved'}},second)
        self.wait(lambda:self.manager.bridge.calls[saved['requestId']]['status']=='completed')
        self.assertTrue(frames);self.assertEqual({token for token,_ in frames},{first.key})
        self.assertEqual(control.execute({'operation':'widgets.messages'},second)['updates'],[])
        self.assertEqual(second.draft,'untouched');self.assertEqual(second.attachments,['untouched'])
        event_id=frames[-1][1]['notification']['id']
        self.host._pool.event.emit(first,{'type':'widget_delivery','id':event_id,'status':'delivered'})
        updates=control.execute({'operation':'widgets.messages'},first)['updates']
        self.assertEqual(updates[-1]['delivery'],'delivered')
        self.assertTrue(control.execute({'operation':'jobs.get','arguments':{'id':delayed['jobId']}},first)['ok'])
        # A service keeps its original target even after that chat leaves the pool.
        self.host._pool.records.pop(first.key)
        count=len(frames)
        self.manager.bridge.notify('session-demo',{'id':'f'*32,'message':'waiting for original chat','data':{},'requestId':'','wake':True,'session':{'token':first.key,'id':first.id,'workspace':first.workspace}})
        self.assertEqual(len(frames),count)
        reopened=copy.copy(first);reopened.key='reopened-token';self.host._pool.records[reopened.key]=reopened;self.host._view=reopened;self.host.viewChanged.emit()
        self.wait(lambda:len(frames)>count)
        self.assertEqual(frames[-1][0],reopened.key);self.assertEqual(frames[-1][1]['notification']['id'],'f'*32)
        self.assertTrue(control.execute({'operation':'widgets.result','arguments':{'requestId':delayed['requestId']}},reopened)['ok'])
        self.assertTrue(control.execute({'operation':'jobs.get','arguments':{'id':delayed['jobId']}},reopened)['ok'])
        self.host._view=second;self.host.viewChanged.emit();self.host._pool.records.pop(reopened.key)
        self.manager.bridge.notify('session-demo',{'id':'e'*32,'message':'cancel before delivery','data':{},'requestId':'','wake':True,'session':{'token':first.key,'id':first.id,'workspace':first.workspace}})
        self.manager.setEnabled('session-demo',False)
        self.assertEqual(self.manager.bridge.states[first.key]['messages'][-1]['delivery'],'cancelled')

    def test_application_sdk_requires_captured_background_target_and_request_context_is_thread_local(self):
        import threading
        first={'token':'first','id':'first-id','workspace':self.host._view.workspace};second={'token':'second','id':'second-id','workspace':str(self.path/'second')};Path(second['workspace']).mkdir()
        events=[];context=Context(self.path,self.path,{},first,['workspace.read','session.write'],emit=events.append,lifecycle='application')
        captured=context.capture_session();context.session=second
        with self.assertRaises(PluginError):context.notify_agent('implicit target')
        with self.assertRaises(PluginError):context.resolve_workspace('.')
        context.request_id='main-request';context.request_session=first;seen=[]
        def send():
            seen.append(context.request_id)
            context.notify_agent('background result',session=captured)
            seen.append(str(context.resolve_workspace('.',session=captured)))
        thread=threading.Thread(target=send);thread.start();thread.join()
        self.assertEqual(seen,['',first['workspace']]);self.assertEqual(events[0]['arguments']['session'],captured)
        self.assertEqual(events[0]['arguments']['requestId'],'')
        self.fixture();folder=self.path/'session-demo-1.0.0';manifest=json.loads((folder/'manifest.json').read_text());manifest['lifecycle']='application';(folder/'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(PluginError,'page'):validate(folder)

    def test_application_service_startup_failure_does_not_restart_on_chat_updates(self):
        archive,_=self.fixture(lifecycle='application');folder=self.path/'session-demo-1.0.0';counter=self.path/'startup-count'
        (folder/'scripts/plugin.py').write_text('from pathlib import Path\nfrom umeko_plugin_sdk import PluginError\n'+f'counter=Path({str(counter)!r})\ncounter.write_text(str(int(counter.read_text())+1 if counter.exists() else 1))\n'+'def create_plugin(context):raise PluginError("fixture startup failure")\n')
        with zipfile.ZipFile(archive,'w') as stream:
            for path in folder.rglob('*'):
                if path.is_file():stream.write(path,path.relative_to(folder).as_posix())
        self.manager.importZip(QUrl.fromLocalFile(str(archive)).toString());self.wait(lambda:not self.manager.busy)
        self.manager.setEnabled('session-demo',True)
        self.wait(lambda:'session-demo' in self.manager._failed_services and 'session-demo' not in self.manager.workers)
        self.host._view.messages.append({'role':'user','text':'chat update'});self.host.viewChanged.emit()
        self.assertEqual(counter.read_text(),'1');self.assertNotIn('session-demo',self.manager.workers)
        self.manager.setEnabled('session-demo',True)
        self.wait(lambda:counter.read_text()=='2' and 'session-demo' not in self.manager.workers)

    def test_application_executable_uses_service_state_directory_without_a_chat(self):
        context=Context(self.path,self.path,{}, {},['process.execute'],executables={'python':{'system':sys.executable}},lifecycle='application')
        result=context.run_executable('python',['-c','import os;print(os.getcwd())'])
        self.assertEqual(result['code'],0);self.assertEqual(Path(result['text'].strip()),self.path)
    def test_zip_import_is_inert_and_message_is_bound_to_current_session(self):
        archive,marker=self.fixture();self.manager.importZip(QUrl.fromLocalFile(str(archive)).toString());self.wait(lambda:not self.manager.busy)
        self.assertIn('session-demo',self.manager.entries);self.assertFalse(self.manager.entries['session-demo'].get('builtin'));self.assertFalse(marker.exists());self.assertFalse(self.manager.openPage('session-demo'))
        self.manager.setSessionEnabled('session-demo',True);self.assertTrue(self.manager.openPage('session-demo'))
        result=self.call('ping');self.assertTrue(result['ok']);self.assertEqual(result['result'],{'session':'session-one','messages':1})
        self.assertEqual(self.host.sent,[('session-one','from-plugin',True)])
        self.assertTrue(marker.exists())
        self.manager.call('late','{}');self.host._view.key='token-two';self.host._view.id='session-two';self.host.viewChanged.emit()
        self.assertFalse(self.manager.page);self.assertEqual(set(self.manager.workers),{'desktop-pet'})
        deadline=time.monotonic()+1
        while time.monotonic()<deadline:self.app.processEvents();time.sleep(.01)
        self.assertEqual(len(self.host.sent),1)
    def test_enable_scope_config_and_uninstall_persist(self):
        archive,_=self.fixture();self.manager.importZip(QUrl.fromLocalFile(str(archive)).toString());self.wait(lambda:not self.manager.busy)
        self.manager.setSessionEnabled('session-demo',True);self.manager.setEnabled('session-demo',False)
        self.assertFalse(self.manager.openPage('session-demo'));self.assertTrue(self.manager.openPage('file-tree'));self.manager.closePage()
        self.manager.saveConfig('session-demo','{"showHidden":true,"directoryLimit":200}')
        self.wait(lambda:not self.manager.busy);self.assertTrue(self.manager.settings['config']['session-demo']['showHidden'])
        self.manager.saveConfig('session-demo','{"directoryLimit":1000000}')
        self.wait(lambda:not self.manager.busy);self.assertEqual(self.manager.settings['config']['session-demo']['directoryLimit'],200)
        self.assertFalse(self.manager.uninstall('file-tree'));self.assertTrue(self.manager.uninstall('session-demo'));self.assertNotIn('session-demo',self.manager.entries)
    def test_worker_unknown_method_reports_error_without_stopping_host(self):
        self.manager.openPage('file-tree');value=self.call('not-advertised');self.assertFalse(value['ok']);self.assertTrue(self.manager.page)
    def test_file_manager_rename_delete_clipboard_and_scope(self):
        workspace=Path(self.host._view.workspace);target=workspace/'original.txt';target.write_text('keep')
        self.manager.openPage('file-tree')
        self.assertTrue(self.call('rename',{'path':'original.txt','name':'renamed.txt'})['ok'])
        self.assertFalse(target.exists());self.assertEqual((workspace/'renamed.txt').read_text(),'keep')
        with patch('app.plugin_file_actions.copy_files') as clipboard:
            self.assertTrue(self.call('copy',{'path':'renamed.txt'})['ok'])
            self.assertEqual(clipboard.call_args.args,([workspace/'renamed.txt'],False))
            self.assertTrue(self.call('cut',{'path':'renamed.txt'})['ok'])
            self.assertEqual(clipboard.call_args.args,([workspace/'renamed.txt'],True))
        with patch('app.plugin_file_actions.open_with') as chooser:
            self.assertTrue(self.call('openWith',{'path':'renamed.txt'})['ok']);chooser.assert_called_once_with(workspace/'renamed.txt')
        (workspace/'existing.txt').write_text('existing')
        self.assertFalse(self.call('rename',{'path':'renamed.txt','name':'existing.txt'})['ok'])
        self.assertFalse(self.call('delete',{'path':'..'})['ok']);self.assertTrue(workspace.exists())
        self.assertFalse(self.call('delete',{'path':'.'})['ok']);self.assertTrue(workspace.exists())
        (workspace/'nested').mkdir();(workspace/'nested/child.txt').write_text('fixture')
        self.assertTrue(self.call('delete',{'path':'nested'})['ok']);self.assertFalse((workspace/'nested').exists())
        self.assertTrue(self.call('delete',{'path':'renamed.txt'})['ok']);self.assertFalse((workspace/'renamed.txt').exists())
    def test_file_reveal_events_are_scoped_and_explorer_selects_requested_file(self):
        target=Path(self.host._view.workspace)/'nested/file.txt';target.parent.mkdir();target.write_text('fixture')
        self.manager.host_event('git-viewer',{'event':'file.reveal','arguments':{'path':str(target)}})
        self.assertEqual(self.host.revealed,[(str(target),True)])
        self.manager.host_event('git-viewer',{'event':'file.reveal','arguments':{'path':str(self.path/'outside')}})
        self.assertEqual(len(self.host.revealed),1)
        self.manager.host_event('git-viewer',{'event':'explorer.reveal','arguments':{'path':str(target)}})
        self.assertEqual(self.manager.page['id'],'file-tree');self.assertEqual(self.manager.page['selection'],'nested/file.txt')
    def test_recent_widget_is_remembered_per_workspace_and_only_uses_enabled_pages(self):
        first_workspace=self.host._view.workspace
        self.assertTrue(self.manager.openPage('file-tree'));self.manager.closePage()
        self.assertEqual(self.manager.recentPlugin['id'],'file-tree')
        second=self.path/'other-workspace';second.mkdir()
        self.host._view.workspace=str(second);self.host.viewChanged.emit()
        self.assertTrue(self.manager.openPage('git-viewer'));self.manager.closePage()
        self.assertEqual(self.manager.recentPlugin['id'],'git-viewer')
        self.host._view.workspace=first_workspace;self.host.viewChanged.emit()
        self.assertEqual(self.manager.recentPlugin['id'],'file-tree')
        self.manager.setSessionEnabled('file-tree',False)
        self.assertEqual(self.manager.recentPlugin['id'],'git-viewer')
        self.manager.setEnabled('git-viewer',False)
        self.assertEqual(self.manager.recentPlugin,{})
        self.manager.setSessionEnabled('file-tree',True)
        persisted=DesktopPlugins(self.host)
        try:self.assertEqual(persisted.recentPlugin['id'],'file-tree')
        finally:persisted.close()
    def test_import_refuses_builtin_override_and_unsafe_zip_paths(self):
        for name in ('../outside.txt','/absolute.txt','C:/drive.txt','scripts\\bad.py','A.txt'):
            archive=self.path/'unsafe.zip'
            with zipfile.ZipFile(archive,'w') as stream:
                stream.writestr(name,'bad')
                if name=='A.txt':stream.writestr('a.txt','collision')
            with self.subTest(path=name),self.assertRaises(PluginError):install(archive,self.path/'packages')
        archive,_=self.fixture('file-tree')
        with self.assertRaises(PluginError):install(archive,self.path/'packages',['file-tree'])
    def test_upgrade_rejects_incompatible_saved_config_before_install(self):
        archive,_=self.fixture(version='2.0.0')
        with self.assertRaises(PluginError):install(archive,self.path/'packages',current_configs={'session-demo':{'showHidden':'wrong','directoryLimit':1000}})
        self.assertFalse((self.path/'packages/session-demo/2.0.0').exists())
    def test_provider_import_rejects_desktop_plugin_kind(self):
        from umeko_provider_sdk.packages import validate_folder
        from umeko_provider_sdk import ProviderError
        with self.assertRaisesRegex(ProviderError,'Umeko 插件管理'):
            validate_folder(ROOT/'umeko-plugins/file-tree')

    def test_sdk_denies_traversal_symlinks_and_undeclared_actions(self):
        context=Context(self.path,self.path,{},self.manager.session,['workspace.read'])
        with self.assertRaises(PluginError):context.resolve_workspace('../outside')
        with self.assertRaises(PluginError):context.send_message('not allowed')
        with self.assertRaises(PluginError):context.notify_agent('not allowed')
        if os.name!='nt':
            (Path(self.host._view.workspace)/'link').symlink_to(self.path,target_is_directory=True)
            with self.assertRaises(PluginError):context.resolve_workspace('link')

    def test_tree_directory_limit_and_large_diff_do_not_return_unbounded_payloads(self):
        directory=Path(self.host._view.workspace)
        for index in range(210): (directory/f'file-{index}.txt').write_text('x')
        self.manager.settings.setdefault('config',{})['file-tree']={'showHidden':False,'directoryLimit':200}
        self.manager.openPage('file-tree');value=self.call('list',{'path':'.'})
        self.assertTrue(value['ok']);self.assertEqual(len(value['result']['entries']),200);self.assertTrue(value['result']['truncated'])
        spec=importlib.util.spec_from_file_location('git_preview_limit',ROOT/'umeko-plugins/git-viewer/scripts/plugin.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        value=module.preview('x'*200000)
        self.assertTrue(value['truncated']);self.assertLessEqual(len(value['text']),2000)

    def test_declared_process_output_and_timeout_are_bounded(self):
        context=Context(self.path,self.path,{},self.manager.session,['workspace.read','process.execute'],{'python':{'system':sys.executable}})
        value=context.run_executable('python',['-c','import sys;sys.stdout.write("x"*2000000)'],limit=4096)
        self.assertTrue(value['truncated']);self.assertLessEqual(len(value['text']),4096)
        with self.assertRaises(PluginError):context.run_executable('python',['-c','import time;time.sleep(30)'],timeout=.1)
        self.assertFalse(context._processes);context.close()


class GitDemoTests(unittest.TestCase):
    def test_git_status_diff_stage_unstage_and_history_on_disposable_repository(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);subprocess.run(['git','init','-q',str(root)],check=True)
            spec=importlib.util.spec_from_file_location('git_demo',ROOT/'umeko-plugins/git-viewer/scripts/plugin.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            m,config,_=validate(ROOT/'umeko-plugins/git-viewer')
            context=Context(ROOT/'umeko-plugins/git-viewer',root,config,{'workspace':str(root)},m['permissions'],m['executables'])
            plugin=module.create_plugin(context);path=root/'space file.txt';path.write_text('first\n')
            status=plugin.handle('status',{});self.assertEqual(status['entries'][0]['group'],'untracked')
            self.assertIn('first',plugin.handle('diff',{'path':path.name,'group':'untracked'})['text'])
            plugin.handle('stage',{'path':path.name});self.assertEqual(plugin.handle('status',{})['entries'][0]['group'],'staged')
            plugin.handle('unstage',{'path':path.name});self.assertTrue(path.exists())
            self.assertEqual(plugin.handle('history',{})['entries'],[])
            subprocess.run(['git','-C',str(root),'config','user.email','fixture@example.invalid'],check=True);subprocess.run(['git','-C',str(root),'config','user.name','Fixture'],check=True)
            plugin.handle('stage',{'path':path.name});plugin.handle('commit',{'message':'Fixture commit'})
            path.write_text('second\n');self.assertIn('+second',plugin.handle('diff',{'path':path.name,'group':'changes'})['text'])
            self.assertEqual(plugin.handle('history',{})['entries'][0]['subject'],'Fixture commit')
            history=plugin.handle('history',{})['entries']
            self.assertEqual(history[0]['author'],'Fixture');self.assertEqual(history[0]['parents'],[])
            self.assertEqual(history[0]['graph']['column'],0)
            self.assertIn('first',plugin.handle('commitDiff',{'hash':history[0]['id']})['text'])
            with self.assertRaises(PluginError):plugin.handle('commitDiff',{'hash':'HEAD; invalid'})
            path.write_text('first\n')
            original=subprocess.check_output(['git','-C',str(root),'symbolic-ref','--short','HEAD'],text=True).strip()
            subprocess.run(['git','-C',str(root),'checkout','-q','-b','fixture-side'],check=True)
            (root/'side.txt').write_text('side\n');plugin.handle('stage',{'path':'side.txt'});plugin.handle('commit',{'message':'Side commit'})
            subprocess.run(['git','-C',str(root),'checkout','-q',original],check=True)
            (root/'main.txt').write_text('main\n');plugin.handle('stage',{'path':'main.txt'});plugin.handle('commit',{'message':'Main commit'})
            subprocess.run(['git','-C',str(root),'-c','core.hooksPath=NUL' if os.name=='nt' else 'core.hooksPath=/dev/null','-c','commit.gpgSign=false','merge','-q','--no-ff','fixture-side','-m','Merge fixture'],check=True)
            graph=plugin.handle('history',{})['entries']
            self.assertEqual(len(graph[0]['parents']),2)
            self.assertEqual(len(graph[0]['graph']['edges']),2)
            self.assertTrue(any(entry['graph']['columns']>1 for entry in graph))
            self.assertEqual({entry['subject'] for entry in graph},{'Fixture commit','Side commit','Main commit','Merge fixture'})
            self.assertIn(original,[entry['name'] for entry in plugin.handle('branches',{})['entries']])
            plugin.handle('createBranch',{'name':'ui-branch','ref':'refs/heads/'+original})
            self.assertEqual(plugin.handle('status',{})['branch'],'ui-branch')
            plugin.handle('checkout',{'ref':'refs/heads/'+original})
            plugin.handle('checkout',{'ref':graph[0]['id'],'detached':True})
            self.assertEqual(plugin.handle('status',{})['branch'],graph[0]['hash'])
            plugin.handle('checkout',{'ref':'refs/heads/'+original})
            with self.assertRaises(PluginError):plugin.handle('createBranch',{'name':'--bad','ref':'HEAD'})
            subprocess.run(['git','-C',str(root),'remote','add','origin','.'],check=True)
            subprocess.run(['git','-C',str(root),'update-ref','refs/remotes/origin/remote-fixture',graph[0]['id']],check=True)
            subprocess.run(['git','-C',str(root),'tag','fixture-tag',graph[0]['id']],check=True)
            self.assertEqual({row['kind'] for row in plugin.handle('branches',{})['entries']},{'branch','remote','tag'})
            plugin.handle('checkout',{'ref':'refs/remotes/origin/remote-fixture'})
            self.assertEqual(plugin.handle('status',{})['branch'],'remote-fixture')
            plugin.handle('checkout',{'ref':'refs/remotes/origin/remote-fixture'})
            plugin.handle('checkout',{'ref':'refs/tags/fixture-tag'})
            self.assertEqual(plugin.handle('status',{})['branch'],graph[0]['hash'])
            plugin.handle('checkout',{'ref':'refs/heads/'+original})
            self.assertEqual(plugin.handle('headFile',{'path':'main.txt'})['text'],'main\n')
            (root/'main.txt').write_text('changed\n');plugin.handle('discard',{'path':'main.txt','group':'changes'})
            self.assertEqual((root/'main.txt').read_text(),'main\n')
            self.assertTrue(any(p.read_text()=='changed\n' for p in (root/'discarded').glob('*/main.txt')))
            (root/'scratch.txt').write_text('recover me');plugin.handle('discard',{'path':'scratch.txt','group':'untracked'})
            self.assertFalse((root/'scratch.txt').exists());self.assertTrue(any(p.read_text()=='recover me' for p in (root/'discarded').glob('*/scratch.txt')))
            (root/'ignore me[1].txt').write_text('ignore');plugin.handle('ignore',{'path':'ignore me[1].txt'})
            self.assertEqual(subprocess.run(['git','-C',str(root),'check-ignore','-q','--','ignore me[1].txt']).returncode,0)
            context.close()
