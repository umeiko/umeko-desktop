"""Desktop plugin ZIP, worker, session boundary and bounded demo regressions."""
import copy, importlib.util, json, os, shutil, stat, subprocess, sys, tempfile, time, unittest, zipfile
from pathlib import Path
from types import SimpleNamespace
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'plugin-runtime'))
from umeko_plugin_sdk import Context, PluginError
from umeko_plugin_sdk.packages import install, validate
from PySide6.QtCore import QObject, Signal, QCoreApplication, QUrl
from app.desktop_plugins import DesktopPlugins

class Host(QObject):
    viewChanged=Signal();chatChanged=Signal();toast=Signal(str);documentRequested=Signal(str,str,str)
    def __init__(self,directory):
        super().__init__();self.root=ROOT;self.store=SimpleNamespace(directory=directory/'profile')
        self._view=SimpleNamespace(key='token-one',id='session-one',workspace=str(directory/'workspace'),title='Fixture',busy=False,messages=[{'role':'user','text':'fixture context'}])
        Path(self._view.workspace).mkdir();self.sent=[];self.attached=[]
    def send(self,text):self.sent.append((self._view.id,text,False))
    def steer(self,text):self.sent.append((self._view.id,text,True))
    def attachChatboxFile(self,path):self.attached.append(path)

class DesktopPluginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QCoreApplication.instance() or QCoreApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name)
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
    def fixture(self,identifier='session-demo',version='1.0.0',config=None):
        folder=self.path/(identifier+'-'+version);shutil.copytree(ROOT/'umeko-plugins/file-tree',folder)
        manifest=json.loads((folder/'manifest.json').read_text());manifest.update(id=identifier,version=version,builtin=True,permissions=['workspace.read','session.read','session.write'])
        (folder/'manifest.json').write_text(json.dumps(manifest))
        marker=self.path/'activated'
        (folder/'scripts/plugin.py').write_text('from pathlib import Path\nfrom umeko_plugin_sdk import Plugin\nimport time\n'+f'Path({str(marker)!r}).write_text("activated")\n'+'''class Fixture(Plugin):
    def handle(self,method,args):
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
        self.manager.closePage();self.assertFalse(self.manager.workers);self.app.processEvents()
    def test_zip_import_is_inert_and_message_is_bound_to_current_session(self):
        archive,marker=self.fixture();self.manager.importZip(QUrl.fromLocalFile(str(archive)).toString());self.wait(lambda:not self.manager.busy)
        self.assertIn('session-demo',self.manager.entries);self.assertFalse(self.manager.entries['session-demo'].get('builtin'));self.assertFalse(marker.exists());self.assertFalse(self.manager.openPage('session-demo'))
        self.manager.setSessionEnabled('session-demo',True);self.assertTrue(self.manager.openPage('session-demo'))
        result=self.call('ping');self.assertTrue(result['ok']);self.assertEqual(result['result'],{'session':'session-one','messages':1})
        self.assertEqual(self.host.sent,[('session-one','from-plugin',True)])
        self.assertTrue(marker.exists())
        self.manager.call('late','{}');self.host._view.key='token-two';self.host._view.id='session-two';self.host.viewChanged.emit()
        self.assertFalse(self.manager.page);self.assertFalse(self.manager.workers)
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
            context.close()
