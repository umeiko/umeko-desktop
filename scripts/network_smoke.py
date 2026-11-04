"""Exercise SSL creation and verified HTTPS through the actual frozen runtime."""
import json
import os
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PROBE = '''from pathlib import Path
from types import SimpleNamespace
import ssl, urllib.request, urllib.error
from umeko_plugin_sdk import Plugin
from umeko_provider_sdk import HttpSession
from umeko_provider_sdk.network import network_scope
from app.gateway import Gateway
from app.integration import UnconfiguredAdapter

class Probe(Plugin):
    def handle(self, method, args):
        context = ssl.create_default_context()
        assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
        try:
            opener.open(args['url'], timeout=5)
        except urllib.error.URLError as error:
            assert isinstance(error.reason, ssl.SSLCertVerificationError), type(error.reason).__name__
        else:
            raise AssertionError('An untrusted server certificate was accepted')
        provider = {'id':'fixture', 'name':'Fixture', 'api':'openai', 'key':'synthetic-key',
                    'baseUrl':args['url']+'/v1', 'models':[{'alias':'fixture', 'upstream':'fixture'}],
                    'proxy':{'mode':'direct', 'caFile':args['ca']}}
        store = SimpleNamespace(directory=self.context.state_dir, data={'providers':[provider]})
        completion = Gateway(store, UnconfiguredAdapter()).complete('fixture', [{'role':'user','content':'Test HTTPS streaming'}], max_tokens=32)
        assert completion.text == 'TLS stream OK', completion.text
        with network_scope(provider['proxy']):
            with HttpSession([args['url']]).request(args['url']+'/v1/chat/completions', method='POST', data={}) as response:
                assert response.status == 200 and b'[DONE]' in response.read()
        return {'tls':'passed', 'untrustedCertificate':'rejected', 'gatewayStream':'passed', 'sdkHttps':'passed'}

def create_plugin(context): return Probe(context)
'''


def verify_network_worker(command, environment, report_dir):
    fixture = Path(__file__).resolve().parents[1] / 'tests/fixtures/update-tls'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            events = [
                {'choices':[{'delta':{'content':'TLS '},'finish_reason':None}]},
                {'choices':[{'delta':{'content':'stream OK'},'finish_reason':'stop'}]},
            ]
            raw = (''.join('data: '+json.dumps(row)+'\n\n' for row in events)+'data: [DONE]\n\n').encode()
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream')
            self.send_header('Content-Length',str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(fixture/'server.pem',fixture/'server-key.pem')
    server.socket = context.wrap_socket(server.socket,server_side=True)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    package = report_dir/'network-fixture'
    package.mkdir(parents=True,exist_ok=True)
    manifest = {'kind':'umeko-plugin','apiVersion':1,'id':'network-fixture','name':'Network fixture',
                'summary':'HTTPS fixture','version':'1.0.0','entrypoint':'plugin.py:create_plugin',
                'permissions':[],'agent':{'document':'README.md','methods':{}}}
    for name,value in [('manifest.json',manifest),('config.json',{}),('config.schema.json',{'type':'object','properties':{},'additionalProperties':False})]:
        (package/name).write_text(json.dumps(value),encoding='utf-8')
    (package/'README.md').write_text('Local synthetic HTTPS test.',encoding='utf-8')
    (package/'plugin.py').write_text(PROBE,encoding='utf-8')
    requests = [
        {'id':'initialize','operation':'initialize','arguments':{'path':str(package.resolve()),'stateDir':str((report_dir/'network-state').resolve()),'config':{},'session':{'id':'fixture','token':'fixture','workspace':str(report_dir.resolve())}}},
        {'id':'probe','operation':'call','arguments':{'method':'probe','arguments':{'url':f'https://127.0.0.1:{server.server_port}','ca':str(fixture/'ca.pem')}}},
    ]
    env = dict(environment)
    for key in ('NODE_EXTRA_CA_CERTS','UMEKO_MODEL_CA_FILE','SSL_CERT_FILE','SSL_CERT_DIR'):
        env.pop(key,None)
    try:
        result = subprocess.run(command,input=''.join(json.dumps(row)+'\n' for row in requests),
                                env=env,text=True,capture_output=True,timeout=30,
                                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        (report_dir/'network-worker.log').write_text(result.stdout+result.stderr,encoding='utf-8')
        rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        probe = next((row for row in rows if row.get('id')=='probe'),{})
        expected = {'tls':'passed','untrustedCertificate':'rejected','gatewayStream':'passed','sdkHttps':'passed'}
        if result.returncode or not probe.get('ok') or probe.get('result') != expected:
            raise RuntimeError('Packaged HTTPS test failed; see network-worker.log')
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
    print('Packaged SSL, verified HTTPS streaming and certificate rejection verified')
