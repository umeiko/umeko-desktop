"""Real PTY sharing, Unicode/VT output, chat grants and process cleanup."""
import importlib.util, json, os, sys, tempfile, time, types, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];PACKAGE=ROOT/'umeko-plugins/terminal'
sys.path.insert(0,str(ROOT/'plugin-runtime'));sys.path.insert(0,str(PACKAGE/'vendor'))
from umeko_plugin_sdk import Context, PluginError
from umeko_plugin_sdk.packages import validate
namespace=types.ModuleType('_umeko_terminal_test');namespace.__path__=[str(PACKAGE/'scripts')];sys.modules[namespace.__name__]=namespace
spec=importlib.util.spec_from_file_location(namespace.__name__+'.plugin',PACKAGE/'scripts/plugin.py');module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)


class TerminalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name);workspace=self.path/'中文工作区';workspace.mkdir()
        self.a={'token':'chat-a','id':'session-a','workspace':str(workspace),'language':'zh'}
        self.b={'token':'chat-b','id':'session-b','workspace':str(workspace),'language':'en'}
        self.events=[];manifest,config,_=validate(PACKAGE);config['useShellProfile']=False
        state=self.path/'state';state.mkdir();self.context=Context(PACKAGE,state,config,self.a,manifest['permissions'],emit=self.events.append,lifecycle='application')
        self.plugin=module.create_plugin(self.context);self.addCleanup(self.plugin.close)
    def call(self,method,args=None,source='ui',session=None):
        self.context.call_source=source;self.context.request_session=session or self.a;self.context.request_id='fixture-request'
        try:return self.plugin.handle(method,args or {})
        finally:self.context.call_source='';self.context.request_session={};self.context.request_id=''
    def create(self,**args):return self.call('create',args)['id']
    def wait_text(self,identifier,text):
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            output=self.call('read',{'terminalId':identifier,'lines':300})
            if text in output.get('text',''):return output
            time.sleep(.03)
        self.fail('Expected terminal output did not arrive: '+text+'\n'+output.get('text',''))
    def command(self,windows,posix):return windows if os.name=='nt' else posix

    def test_real_terminal_parses_unicode_colors_resize_and_preserves_same_environment(self):
        identifier=self.create();terminal=self.plugin.terminals[identifier];pid=terminal.backend.pid
        self.call('run',{'terminalId':identifier,'command':self.command("$env:UMEKO_TERMINAL_FIXTURE='same-process'; [Console]::Write(([char]27)+'[31mVT_RED'+([char]27)+'[0m'); [Console]::WriteLine('中文输出')",r"export UMEKO_TERMINAL_FIXTURE=same-process; printf '\033[31mVT_RED\033[0m中文输出\n'")})
        self.wait_text(identifier,'VT_RED中文输出')
        frame=self.call('view',{'ids':[identifier]})['frames'][0]
        self.assertTrue(any(run[2]=='red' and 'VT_RED' in run[1] for row in frame['screen'] for run in row['runs']))
        colors="[Console]::Write(([char]27)+'[38;5;33mVT_256'+([char]27)+'[38;2;12;34;56mVT_RGB'+([char]27)+'[0m')"
        self.call('run',{'terminalId':identifier,'command':self.command(colors,r"printf '\033[38;5;33mVT_256\033[38;2;12;34;56mVT_RGB\033[0m'")})
        self.wait_text(identifier,'VT_256VT_RGB')
        frame=self.call('view',{'ids':[identifier]})['frames'][0]
        self.assertTrue(any(run[2]=='0087ff' and 'VT_256' in run[1] for row in frame['screen'] for run in row['runs']))
        self.assertTrue(any(run[2]=='0c2238' and 'VT_RGB' in run[1] for row in frame['screen'] for run in row['runs']))
        self.call('resize',{'terminalId':identifier,'columns':100,'rows':30})
        self.assertEqual(terminal.screen.columns,100);self.assertEqual(terminal.screen.lines,30)
        self.call('attach',{'terminalId':identifier})
        self.call('run',{'terminalId':identifier,'command':self.command("Write-Output ('AGENT_'+$env:UMEKO_TERMINAL_FIXTURE)","printf 'AGENT_%s\n' \"$UMEKO_TERMINAL_FIXTURE\"")},source='agent')
        self.wait_text(identifier,'AGENT_same-process');self.assertEqual(terminal.backend.pid,pid)
        text=self.call('read',{'terminalId':identifier},source='agent')['text'];self.assertNotIn('\x1b',text)

    def test_attach_is_localized_and_required_for_each_chat_and_split_terminal(self):
        identifier=self.create()
        self.assertEqual(self.call('list',source='agent')['terminals'],[])
        with self.assertRaisesRegex(PluginError,'没有关联'):self.call('read',{'terminalId':identifier},source='agent')
        attached=self.call('attach',{'terminalId':identifier})
        self.assertEqual(attached['text'],'用户附带了来自widget：'+identifier+'的终端')
        self.assertEqual(self.events[-1]['event'],'session.draft');self.assertEqual(self.events[-1]['arguments']['session']['token'],'chat-a')
        self.assertTrue(self.call('read',{'terminalId':identifier},source='agent')['changed'])
        with self.assertRaises(PluginError):self.call('run',{'terminalId':identifier,'command':'echo denied'},source='agent',session=self.b)
        english=self.call('attach',{'terminalId':identifier},session=self.b)
        self.assertEqual(english['text'],'The user attached a terminal from widget: '+identifier+'.')
        split=self.create(splitFrom=identifier)
        self.assertEqual(self.plugin.terminals[split].group,self.plugin.terminals[identifier].group)
        with self.assertRaises(PluginError):self.call('read',{'terminalId':split},source='agent')
        self.call('rename',{'terminalId':split,'name':'第二终端'});self.assertEqual(self.plugin.terminals[split].name,'第二终端')
        terminal=self.plugin.terminals[split];self.call('kill',{'terminalId':split});self.assertFalse(terminal.backend.isalive());self.assertFalse(terminal.reader.is_alive())

    def test_interrupt_and_panel_close_keep_the_shared_shell_alive(self):
        if os.name=='nt':
            import ctypes
            # Reproduce launcher/CI process groups which disable Ctrl+C and
            # pass that flag down even into a fresh ConPTY session.
            ctypes.windll.kernel32.SetConsoleCtrlHandler(None,True)
            self.addCleanup(lambda:ctypes.windll.kernel32.SetConsoleCtrlHandler(None,False))
        identifier=self.create();terminal=self.plugin.terminals[identifier];self.call('attach',{'terminalId':identifier})
        self.call('run',{'terminalId':identifier,'command':self.command("Write-Output ('WAIT_'+'STARTED'); Start-Sleep -Seconds 30","printf 'WAIT_%s\n' STARTED; sleep 30")},source='agent')
        self.wait_text(identifier,'WAIT_STARTED')
        self.call('interrupt',{'terminalId':identifier},source='agent')
        until=time.monotonic()+8
        while time.monotonic()<until:
            output=self.call('read',{'terminalId':identifier})['text'].rsplit('WAIT_STARTED',1)[-1].strip()
            if output.endswith(('>','$','#','%')):break
            time.sleep(.03)
        else:self.fail('Ctrl+C did not return the shared shell prompt')
        self.call('run',{'terminalId':identifier,'command':self.command("Write-Output ('AFTER_'+'INTERRUPT')","printf 'AFTER_%s\n' INTERRUPT")},source='agent')
        self.wait_text(identifier,'AFTER_INTERRUPT')
        self.plugin.on_event('page.visibility',{'visible':False});self.assertTrue(terminal.backend.isalive())
        self.plugin.on_event('session.changed',self.b);self.assertTrue(terminal.backend.isalive())
        self.plugin.close();self.assertFalse(terminal.backend.isalive());self.assertFalse(terminal.reader.is_alive())

    def test_unsplit_preserves_live_shells_and_chat_grants_after_the_original_terminal_closed(self):
        original=self.create();left=self.create(splitFrom=original)
        self.call('kill',{'terminalId':original});right=self.create(splitFrom=left)
        self.call('attach',{'terminalId':left})
        before={identifier:self.plugin.terminals[identifier].backend.pid for identifier in (left,right)}
        self.call('unsplit',{'terminalId':left})
        for identifier in (left,right):
            terminal=self.plugin.terminals[identifier]
            self.assertEqual(terminal.group,identifier);self.assertEqual(terminal.backend.pid,before[identifier]);self.assertTrue(terminal.backend.isalive())
        self.assertTrue(self.call('read',{'terminalId':left},source='agent')['changed'])
        with self.assertRaises(PluginError):self.call('read',{'terminalId':right},source='agent')

    def test_bounded_scrollback_and_read_cursor_do_not_return_unbounded_output(self):
        self.context.config['scrollback']=100;identifier=self.create();terminal=self.plugin.terminals[identifier]
        with terminal.lock:
            terminal.stream.feed(''.join('line-%04d\r\n'%index for index in range(500)));terminal.revision+=1
            # Keep synthetic buffer input and its assertion atomic: ConPTY's
            # asynchronous shell startup may otherwise clear the screen here.
            value=self.call('read',{'terminalId':identifier,'lines':20})
            self.assertTrue(value['truncated']);self.assertIn('line-0499',value['text'])
        self.assertLessEqual(len(terminal.screen.history.top),100)
        with terminal.lock:
            stable=terminal.contents(20)
            unchanged=terminal.contents(20,stable['sequence'])
        self.assertFalse(unchanged['changed'])
        frame=terminal.frame(reset=True);self.assertLess(len(json.dumps(frame,ensure_ascii=True)),400000)


if __name__=='__main__':unittest.main()
