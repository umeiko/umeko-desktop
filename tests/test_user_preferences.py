import concurrent.futures
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import unittest
import ast
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PySide6.QtCore import QObject, QLocale
from PySide6.QtGui import QFont, QGuiApplication
from app.platform_support import migrate_profile
from app.storage import Store
from app.gateway import Gateway
from app.integration import UnconfiguredAdapter
from app.request_diagnostics import RequestFailure


class PreferencesTests(unittest.TestCase):
    def test_line_spacing_defaults_to_standard(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp))
            self.assertEqual(store.data['ui']['lineSpacing'], 'standard')

    def test_line_spacing_migrates_missing_and_invalid_values(self):
        for value in ('missing', '', 'wide', None, 1.2, [], {}):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / 'settings.json'
                ui = {'language': 'zh', 'fontScale': 1.3, 'sidebarWidth': 300}
                if value != 'missing':
                    ui['lineSpacing'] = value
                path.write_text(json.dumps({'ui': ui, 'server': {'keys': []},
                                           'agent': {'outputLimitDefaultVersion': 1}}), encoding='utf-8')
                store = Store(Path(temp))
                self.assertEqual(store.data['ui'], {**ui, 'sidebarCollapsed': False, 'lineSpacing': 'standard'})
                self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['ui']['lineSpacing'], 'standard')

    def test_line_spacing_updates_immediately_and_round_trips(self):
        from app.controller import Controller

        class AppearanceController(Controller):
            def __init__(self, store):
                QObject.__init__(self)
                self.store = store
                self._appearance_save = Mock()

        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp))
            controller = AppearanceController(store)
            changes = []
            controller.appearanceChanged.connect(lambda: changes.append(controller.lineSpacing))
            for spacing in ('compact', 'standard', 'relaxed'):
                controller.setLineSpacing(spacing)
                self.assertEqual(changes[-1], spacing)
                store.save()
                self.assertEqual(Store(Path(temp)).data['ui']['lineSpacing'], spacing)
            for invalid in ('', 'wide', 'RELAXED', None, 1.2, [], {}):
                controller.setLineSpacing(invalid)
            controller.setLineSpacing('relaxed')
            self.assertEqual(changes, ['compact', 'standard', 'relaxed'])
            self.assertEqual(controller._appearance_save.start.call_count, 3)

    def test_reset_font_family_restores_platform_default(self):
        from app.controller import Controller
        for platform_name, expected in (('nt', 'Microsoft YaHei UI'), ('posix', 'Fixture Default')):
            with self.subTest(platform=platform_name):
                application = Mock(spec=QGuiApplication)
                controller = SimpleNamespace(store=SimpleNamespace(data={'fontFamily': 'Custom Font'}, save=Mock()),
                                             changed=Mock())
                with patch('app.controller.QGuiApplication.instance', return_value=application), \
                     patch('app.controller.os.name', platform_name), \
                     patch('app.controller.QFontDatabase.systemFont', return_value=QFont('Fixture Default', 10)):
                    Controller.setFontFamily(controller, '系统默认')
                self.assertEqual(controller.store.data['fontFamily'], '')
                self.assertEqual(application.setFont.call_args.args[0].family(), expected)

    def test_output_default_migrates_once_and_keeps_other_custom_limits(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            store = Store(path)
            self.assertEqual(store.data['agent']['maxTokens'], 32768)
            for value, expected in [(8192,32768), (4096,4096)]:
                legacy = json.loads(store.path.read_text(encoding='utf-8'))
                legacy['agent'].pop('outputLimitDefaultVersion')
                legacy['agent']['maxTokens'] = value
                store.path.write_text(json.dumps(legacy), encoding='utf-8')
                migrated = Store(path)
                self.assertEqual(migrated.data['agent']['maxTokens'], expected)
                self.assertEqual(json.loads(store.path.read_text())['agent']['outputLimitDefaultVersion'], 1)
            migrated.data['agent']['maxTokens'] = 8192
            migrated.save()
            self.assertEqual(Store(path).data['agent']['maxTokens'], 8192)

    def test_system_locale_is_used_only_until_user_chooses(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'UMEKO_LANGUAGE': ''}), patch('app.storage.QLocale.system', return_value=QLocale('en_US')):
            store = Store(Path(temp))
            self.assertEqual(store.data['ui']['language'], 'en')
            store.data['ui'].update(language='zh', fontScale=2.)
            store.save()
            self.assertEqual(Store(Path(temp)).data['ui']['language'], 'zh')
            self.assertEqual(Store(Path(temp)).data['ui']['fontScale'], 2.)
            with patch('app.storage.QLocale.system', return_value=QLocale('zh_CN')):
                self.assertEqual(Store(Path(temp)/'chinese').data['ui']['language'],'zh')

    def test_all_static_ui_translations_have_english_entries(self):
        root=Path(__file__).resolve().parents[1]/'app/qml'
        raw=(root/'english.js').read_text(encoding='utf-8');dictionary=json.loads(raw[raw.index('{'):])
        missing=[]
        for path in root.glob('*.qml'):
            for match in re.finditer(r'I18n\.t\(("(?:\\.|[^"\\])*"|\x27(?:\\.|[^\x27\\])*\x27)\)',path.read_text(encoding='utf-8')):
                text=ast.literal_eval(match[1])
                if text not in dictionary:missing.append((path.name,text))
        self.assertEqual(missing,[])

    def test_migration_keeps_source_and_remaps_only_managed_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); old = root/'old'; new = root/'home/.umeko/desktop'
            session = old/'pi/sessions/one.jsonl'; session.parent.mkdir(parents=True)
            body = b'{"type":"message","message":{"content":"keep old paths in user text"}}\n'
            session.write_bytes(json.dumps({'type':'session', 'cwd':str(old/'workspace')}).encode()+b'\n'+body)
            plugin = old/'provider-plugins/packages/example/1.0.0'; plugin.mkdir(parents=True)
            (plugin/'manifest.json').write_text('{"id":"example"}')
            (old/'settings.json').write_text(json.dumps({'providers':[{'id':'account','key':'protected-placeholder'}], 'workspace':str(old/'workspace')}))
            (old/'sessions.json').write_text(json.dumps([{'file':str(session), 'workspace':str(old/'workspace')}]))
            original = (old/'settings.json').read_bytes()
            migrate_profile(old,new)
            self.assertEqual((old/'settings.json').read_bytes(), original)
            self.assertEqual(json.loads((new/'settings.json').read_text())['providers'][0]['key'], 'protected-placeholder')
            self.assertEqual(json.loads((new/'sessions.json').read_text())[0]['file'], str(new/'pi/sessions/one.jsonl'))
            lines = (new/'pi/sessions/one.jsonl').read_bytes().splitlines(keepends=True)
            self.assertEqual(json.loads(lines[0])['cwd'], str(new/'workspace'))
            self.assertEqual(b''.join(lines[1:]), body)
            self.assertTrue((new/'provider-plugins/packages/example/1.0.0/manifest.json').exists())
            migrate_profile(old,new)  # Existing destinations are never overwritten.

    def test_direct_custom_and_system_are_isolated_and_errors_are_complete(self):
        hits = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_): pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                hits.append((self.server.label,self.path,body))
                failed = body['messages'][0]['content']=='fail'
                payload = ('detail-'*10000 + 'secret-test-key') if failed else json.dumps({'choices':[{'message':{'role':'assistant','content':self.server.label},'finish_reason':'stop'}]})
                raw = payload.encode()
                self.send_response(429 if failed else 200)
                self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        servers = []
        for label in ('direct','proxy'):
            server = ThreadingHTTPServer(('127.0.0.1',0),Handler);server.label=label
            threading.Thread(target=server.serve_forever,daemon=True).start();servers.append(server)
        try:
            with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'HTTP_PROXY':f'http://127.0.0.1:{servers[1].server_port}','NO_PROXY':'*'}):
                store = Store(Path(temp)); store.data['providers'] = []
                for mode in ('direct','custom','system'):
                    store.data['providers'].append({'id':mode,'name':mode,'api':'openai','baseUrl':f'http://127.0.0.1:{servers[0].server_port}/v1','key':'secret-test-key','models':[{'upstream':'model','alias':mode}], 'proxy':{'mode':mode,'url':f'http://127.0.0.1:{servers[1].server_port}'}})
                gateway = Gateway(store,UnconfiguredAdapter())
                def call(mode): return gateway.complete(mode,[{'role':'user','content':'hello'}]).text
                with concurrent.futures.ThreadPoolExecutor(2) as pool:
                    self.assertEqual(list(pool.map(call,('direct','custom'))),['direct','proxy'])
                self.assertEqual(call('system'),'direct')  # System NO_PROXY is respected.
                with self.assertRaises(RequestFailure) as caught:
                    gateway.complete('custom',[{'role':'user','content':'fail'}])
                identifier = re.search(r'\[Umeko:([a-f0-9-]+)\]',str(caught.exception))[1]
                raw = gateway.diagnostics.read(identifier); report = json.loads(raw)
                self.assertNotIn('secret-test-key',raw)
                self.assertEqual(report['http'][0]['request']['body']['messages'][0]['content'],'fail')
                self.assertEqual(report['response']['status'],429)
                self.assertEqual(report['response']['body'],'detail-'*10000+'[REDACTED]')
                self.assertEqual(gateway.diagnostics.read('../settings'),'')
        finally:
            for server in servers: server.shutdown();server.server_close()
