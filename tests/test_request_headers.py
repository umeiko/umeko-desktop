"""Verify headers on the wire, not just the settings representation."""
import base64
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication
from app.request_headers import DEFAULTS, build, validate
from app.gateway import Gateway
from app.generation import generate
from app.integration import UnconfiguredAdapter
from app.storage import Store

APP = QCoreApplication.instance() or QCoreApplication([])


class RequestHeaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))
        fixture = self
        self.calls = []
        self.fail = False
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                fixture.calls.append((self.path, dict(self.headers), body))
                if fixture.fail:
                    data = {'error': {'message': 'upstream echoed opaque-header-secret and fixture-key'}}
                elif self.path.endswith('/messages'):
                    data = {'id':'fixture','type':'message','role':'assistant','content':[{'type':'text','text':'ok'}], 'stop_reason':'end_turn','usage':{}}
                elif self.path.endswith('/responses'):
                    data = {'id':'fixture','object':'response','status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'ok'}]}],'usage':{}}
                elif self.path.endswith('/images/generations'):
                    data = {'data':[{'url':fixture.base+'/download'}]}
                elif self.path.endswith('/audio/speech'):
                    return self.reply(b'fixture-audio', 'audio/mpeg')
                elif self.path.endswith('/videos'):
                    data = {'id':'video-1','status':'completed'}
                else:
                    data = {'choices':[{'message':{'role':'assistant','content':'ok'},'finish_reason':'stop'}]}
                self.reply(json.dumps(data).encode(), status=400 if fixture.fail else 200)
            def do_GET(self):
                fixture.calls.append((self.path, dict(self.headers), {}))
                if self.path.endswith('/models'):
                    return self.reply(json.dumps({'data':[{'id':'actual','context_window':100000}]}).encode())
                data = b'\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isomfixture-video' if '/videos/' in self.path else base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=')
                self.reply(data, 'video/mp4' if '/videos/' in self.path else 'image/png')
            def reply(self, data, mime='application/json', status=200):
                self.send_response(status); self.send_header('Content-Type',mime)
                self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.provider = {'id':'fixture','name':'Fixture','api':'openai','baseUrl':self.base+'/v1','key':'fixture-key',
                         'proxy':{'mode':'direct'},'models':[{'upstream':'actual','alias':'friendly'}]}
        self.store.data['providers'] = [self.provider]
        self.gateway = Gateway(self.store, UnconfiguredAdapter())

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()

    def call(self):
        return list(self.gateway.events('friendly',[{'role':'user','content':'hello'}]))

    def headers(self):
        return {key.lower():value for key,value in self.calls[-1][1].items()}

    def policy(self):
        value = copy.deepcopy(DEFAULTS)
        value[1]['value'] = 'My-Client/1.0'
        value[2]['name'] = 'X-Custom-Auth'
        value.append({'id':'custom-project','name':'X-Project','value':'opaque-header-secret','enabled':True})
        return value

    def test_protocols_rename_add_disable_reset_and_live_update(self):
        self.store.data['requestHeaders'] = self.policy()
        for protocol in ('chat', 'responses', 'anthropic'):
            self.provider['api'] = 'anthropic' if protocol == 'anthropic' else 'openai'
            self.provider['wireApi'] = 'responses' if protocol == 'responses' else ''
            self.call(); headers = self.headers()
            self.assertEqual(headers['user-agent'],'My-Client/1.0')
            self.assertEqual(headers['x-project'],'opaque-header-secret')
            self.assertNotIn('authorization',headers)
            if protocol == 'anthropic':
                self.assertEqual(headers['x-api-key'],'fixture-key'); self.assertNotIn('x-custom-auth',headers)
            else:
                self.assertEqual(headers['x-custom-auth'],'Bearer fixture-key'); self.assertNotIn('x-api-key',headers)
        self.provider['api'] = 'openai'
        for row in self.store.data['requestHeaders']:
            if row['id'] in ('content-type','user-agent','custom-project'): row['enabled'] = False
        self.call()
        for name in ('content-type','user-agent','x-project'): self.assertNotIn(name,self.headers())
        self.store.data['requestHeaders'] = []
        self.call()
        self.assertEqual(self.headers()['user-agent'],'Umeko-Desktop')
        self.assertEqual(self.headers()['authorization'],'Bearer fixture-key')
        self.assertNotIn('x-project',self.headers())

    def test_generation_and_poll_headers_external_download_isolation(self):
        self.store.data['requestHeaders'] = self.policy()
        self.store.data['multimodal'] = {kind:{'providerId':'fixture','model':'actual','voice':'voice'} for kind in ('image','speech','video')}
        for kind,body in [('image',{'prompt':'test'}),('speech',{'text':'test'}),('video',{'prompt':'test'})]:
            start = len(self.calls)
            result = generate(self.gateway, {'kind':kind,**body},poll_interval=.01)
            self.assertTrue(result['items'])
            for path,headers,_ in self.calls[start:]:
                headers = {key.lower():value for key,value in headers.items()}
                if path == '/download':
                    self.assertNotIn('x-project',headers); self.assertNotIn('x-custom-auth',headers)
                else:
                    self.assertEqual(headers['user-agent'],'My-Client/1.0')
                    self.assertEqual(headers['x-custom-auth'],'Bearer fixture-key')

    def test_echoed_custom_header_values_are_redacted(self):
        self.store.data['requestHeaders'] = self.policy(); self.fail = True
        with self.assertRaises(ValueError) as caught: self.call()
        report = next((Path(self.temp.name)/'request-errors').glob('*.json')).read_text()
        for secret in ('opaque-header-secret','fixture-key'):
            self.assertNotIn(secret,report); self.assertNotIn(secret,str(caught.exception))

    def test_validation_and_protocol_scope(self):
        self.assertEqual(validate([]),DEFAULTS)
        for patch in ({'name':'X\r\nInjected'}, {'name':'X-End\n'}, {'id':'trailing\n'}, {'value':'text\nnext'}, {'value':'中文'},
                      {'enabled':1}, {'name':'Host'}, {'name':''}):
            rows = self.policy(); rows[-1].update(patch)
            with self.subTest(patch=patch), self.assertRaises(ValueError): validate(rows)
        rows = self.policy(); rows[-1]['name'] = 'USER-agent'
        with self.assertRaises(ValueError): validate(rows)
        rows[-1]['enabled'] = False; validate(rows)
        with self.assertRaises(ValueError): validate([rows[0],rows[0]])
        self.assertNotIn('x-api-key',build([],self.provider)[0])
        rows=self.policy();rows[-1]['id']='constructor'
        self.assertEqual(build(rows,{**self.provider,'key':'dollar$&token'})[0]['X-Custom-Auth'],'Bearer dollar$&token')
        self.assertIn('X-Project',build(rows,self.provider)[0])
        for key in ('x\nInjected','x'*4097):
            with self.assertRaises(ValueError): build(rows,{**self.provider,'key':key})

    def test_model_catalog_uses_the_same_headers(self):
        from app.provider_models import fetch_model_windows
        self.assertIn('actual',fetch_model_windows(self.provider,self.policy()))
        self.assertEqual(self.headers()['user-agent'],'My-Client/1.0')
        self.assertEqual(self.headers()['x-custom-auth'],'Bearer fixture-key')

    def test_settings_persist_rollback_reset_and_preserve_other_fields(self):
        from app.controller import Controller
        with patch.dict('os.environ', {'UMEKO_DATA_DIR':str(Path(self.temp.name)/'controller')}):
            controller = Controller(Path(__file__).resolve().parents[1])
        try:
            before = copy.deepcopy(controller.store.data)
            self.assertTrue(controller.saveRequestHeaders(json.dumps(self.policy())))
            self.assertEqual(controller.requestHeaders,self.policy())
            self.assertEqual(Store(controller.store.directory).data['requestHeaders'],self.policy())
            controlled=controller._umeko_control.execute({'operation':'settings.get'})['config']['requestHeaders']
            self.assertTrue(all(row['value']=='[redacted]' for row in controlled))
            with patch.object(controller.store,'save',side_effect=OSError('fixture write failure')):
                self.assertFalse(controller.saveRequestHeaders('[]'))
            self.assertEqual(controller.requestHeaders,self.policy())
            self.assertFalse(controller.saveRequestHeaders('[{}]'))
            self.assertTrue(controller.saveRequestHeaders('[]'))
            after = copy.deepcopy(controller.store.data); after.pop('requestHeaders')
            self.assertEqual(before,after)
        finally: controller.close()


if __name__ == '__main__': unittest.main()
