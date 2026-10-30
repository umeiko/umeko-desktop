"""Offline TLS coverage using public synthetic loopback certificates."""
import json
import os
from pathlib import Path
import ssl
import tempfile
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from app.controller import Controller
from app.gateway import Gateway
from app.integration import UnconfiguredAdapter
from app.network_retry import certificate_failure, transient_failure, upstream_failure
from app.provider_models import fetch_model_windows
from app.request_diagnostics import RequestFailure
from app.storage import Store
from umeko_provider_sdk.http import HttpSession
from umeko_provider_sdk.network import network_scope

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/update-tls'


class ModelTlsTests(unittest.TestCase):
    def test_model_discovery_uses_provider_ca_and_rejects_untrusted_or_redirected_catalogs(self):
        paths = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass

            def do_GET(self):
                paths.append(self.path)
                if self.path == '/redirect/models':
                    self.send_response(302)
                    self.send_header('Location', '/models')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                raw = json.dumps({'data': [{'id': 'fixture', 'context_length': 64000}]}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(FIXTURE / 'server.pem', FIXTURE / 'server-key.pem')
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ):
                os.environ.pop('UMEKO_MODEL_CA_FILE', None)
                os.environ.pop('NODE_EXTRA_CA_CERTS', None)
                base = f'https://127.0.0.1:{server.server_port}'
                provider = {'api': 'openai', 'baseUrl': base, 'key': 'synthetic-model-key',
                            'proxy': {'mode': 'direct', 'caFile': str(FIXTURE / 'ca.pem')}}
                self.assertEqual(fetch_model_windows(provider), {'fixture': 64000})
                with self.assertRaises(urllib.error.URLError) as caught:
                    fetch_model_windows({**provider, 'proxy': {'mode': 'direct'}})
                self.assertIsInstance(caught.exception.reason, ssl.SSLCertVerificationError)
                with self.assertRaisesRegex(ValueError, '重定向'):
                    fetch_model_windows({**provider, 'baseUrl': base + '/redirect'})
                self.assertEqual(paths, ['/models', '/redirect/models'])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_verified_provider_and_sdk_trust_is_isolated_and_failures_are_terminal(self):
        class Handler(BaseHTTPRequestHandler):
            calls = 0
            def log_message(self, *_): pass
            def do_POST(self):
                Handler.calls += 1
                self.rfile.read(int(self.headers.get('Content-Length', 0)))
                raw = json.dumps({'choices': [{'message': {'role': 'assistant', 'content': 'TLS fixture'}, 'finish_reason': 'stop'}]}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(FIXTURE / 'server.pem', FIXTURE / 'server-key.pem')
        server.socket = context.wrap_socket(server.socket, server_side=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ):
                os.environ.pop('UMEKO_MODEL_CA_FILE', None)
                os.environ.pop('NODE_EXTRA_CA_CERTS', None)
                store = Store(Path(temp))
                url = f'https://127.0.0.1:{server.server_port}/v1'
                provider = {'id': 'fixture', 'name': 'Fixture', 'api': 'openai', 'key': 'synthetic-model-key',
                            'baseUrl': url, 'models': [{'upstream': 'fixture', 'alias': 'fixture'}],
                            'proxy': {'mode': 'direct', 'caFile': str(FIXTURE / 'ca.pem')}}
                store.data['providers'] = [provider]
                gateway = Gateway(store, UnconfiguredAdapter())
                self.assertEqual(gateway.complete('fixture', [{'role': 'user', 'content': 'hello'}]).text, 'TLS fixture')
                with network_scope(provider['proxy']):
                    with HttpSession([url]).request(url, method='POST', data={}) as response:
                        self.assertEqual(response.status, 200)
                provider['proxy'] = {'mode': 'direct'}
                with self.assertRaises(RequestFailure) as caught:
                    gateway.complete('fixture', [{'role': 'user', 'content': 'untrusted'}])
                self.assertFalse(caught.exception.retryable)
                self.assertEqual(caught.exception.tls_code, 'CERTIFICATE_VERIFY_FAILED')
                self.assertIn('CERTIFICATE_VERIFY_FAILED', str(caught.exception))
                self.assertEqual(upstream_failure(caught.exception)['code'], 'umeko_tls_certificate')
                raw = next((Path(temp) / 'request-errors').glob('*.json')).read_text(encoding='utf-8')
                record = json.loads(raw)
                self.assertIn('verifyMessage', json.dumps(record['error']))
                self.assertNotIn('synthetic-model-key', raw)
                self.assertNotIn('BEGIN CERTIFICATE', raw)
                self.assertEqual(Handler.calls, 2)
        finally:
            server.shutdown()
            server.server_close()

    def test_network_settings_validate_atomically_and_proxy_changes_preserve_ca(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'UMEKO_DATA_DIR': temp}):
            backend = Controller(ROOT)
            try:
                self.assertTrue(backend.saveProvider('', 'Fixture', 'openai', 'http://127.0.0.1:1/v1', 'synthetic-key', json.dumps([{'upstream': 'fixture', 'alias': 'fixture'}])))
                provider = backend.store.data['providers'][0]
                identifier = provider['id']
                ca = str((FIXTURE / 'ca.pem').resolve())
                self.assertTrue(backend.setProviderNetwork(identifier, 'direct', '', ca))
                self.assertEqual(provider['proxy']['caFile'], ca)
                self.assertTrue(backend.setProviderProxy(identifier, 'custom', 'http://127.0.0.1:7890'))
                self.assertEqual(provider['proxy']['caFile'], ca)
                previous = provider['proxy'].copy()
                self.assertFalse(backend.setProviderNetwork(identifier, 'system', '', str(Path(temp) / 'missing.pem')))
                self.assertEqual(provider['proxy'], previous)
                self.assertTrue(backend.setProviderCertificate(identifier, ''))
                self.assertNotIn('caFile', provider['proxy'])
                self.assertEqual(provider['proxy']['mode'], 'custom')
                self.assertNotIn('caFile', Store(Path(temp)).data['providers'][0]['proxy'])
            finally:
                backend.close()

    def test_nested_tls_failure_dominates_generic_fetch_error(self):
        certificate = ssl.SSLCertVerificationError(1, 'certificate verify failed')
        error = RuntimeError('fetch failed')
        error.__cause__ = urllib.error.URLError(certificate)
        self.assertTrue(certificate_failure(error))
        self.assertFalse(transient_failure(error, [{'response': {'status': 503}}]))
        self.assertTrue(transient_failure(ConnectionResetError('connection reset')))


if __name__ == '__main__':
    unittest.main()
