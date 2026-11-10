"""Offline HTTP fixtures for direct media, model discovery and SDK retries."""
import base64
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from app.gateway import Gateway
from app.provider_models import fetch_model_windows
from umeko_provider_sdk import ProviderError
from umeko_provider_sdk.http import HttpSession
from umeko_provider_sdk.network import network_scope

# Acceptance artifacts and temporary profiles stay outside the Codex profile.
TEMP_ROOT = Path('C:/UmekoTests/p124')
TEMP_ROOT.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TEMP_ROOT)
os.environ['TMP'] = os.environ['TEMP'] = str(TEMP_ROOT)
PNG = b'\x89PNG\r\n\x1a\nfixture'


class DirectCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.calls = []
        self.reject = None
        self.statuses = []
        self.error_payload = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def handle_request(self):
                raw = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                body = json.loads(raw) if raw else None
                owner.calls.append((self.path, body))
                status = owner.statuses.pop(0) if owner.statuses else 200
                if status != 200:
                    value = {'error': {'message': 'temporary fixture overload', 'type': 'server_error'}}
                elif owner.reject and body and owner.reject in body:
                    status = 400
                    value = {'error': {'message': 'Unsupported parameter: ' + owner.reject,
                                      'param': owner.reject, 'code': 'unsupported_parameter'}}
                elif owner.error_payload is not None:
                    value = owner.error_payload
                elif self.path.endswith('/models'):
                    value = {'data': [{'id': 'fixture-model', 'context_window': 4096}]}
                elif self.path.endswith('/audio/speech'):
                    value = None
                else:
                    value = {'data': [{'b64_json': base64.b64encode(PNG).decode()}]}
                response = json.dumps(value).encode() if value is not None else b'ID3fixture'
                self.send_response(status)
                self.send_header('Content-Type', 'application/json' if value is not None else 'audio/mpeg')
                self.send_header('Content-Length', str(len(response)))
                self.send_header('Retry-After', '0')
                self.end_headers()
                self.wfile.write(response)

            do_POST = do_GET = handle_request

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.base = f'http://127.0.0.1:{self.server.server_port}/v1'
        self.provider = {'id': 'direct-fixture', 'name': 'Offline fixture', 'api': 'openai',
                         'baseUrl': self.base, 'key': 'fixture-private', 'models': [],
                         'proxy': {'mode': 'direct', 'url': ''}}
        self.store = SimpleNamespace(directory=Path(self.temp.name), data={
            'providers': [self.provider], 'multimodal': {
                'image': {'providerId': self.provider['id'], 'model': 'fixture-image'},
                'speech': {'providerId': self.provider['id'], 'model': 'fixture-speech', 'voice': 'fixture'}}})
        self.gateway = Gateway(self.store, None)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_image_auto_count_rejection_is_retried_and_remembered(self):
        self.reject = 'n'
        self.gateway.generate({'kind': 'image', 'prompt': 'dot'})
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[0][1]['n'], 1)
        self.assertNotIn('n', self.calls[1][1])
        Gateway(self.store, None).generate({'kind': 'image', 'prompt': 'dot again'})
        self.assertEqual(len(self.calls), 3)
        self.assertNotIn('n', self.calls[-1][1])

    def test_saved_image_count_is_not_removed(self):
        self.reject = 'n'
        self.store.data['multimodal']['image']['count'] = 1
        with self.assertRaisesRegex(Exception, 'Unsupported parameter: n'):
            self.gateway.generate({'kind': 'image', 'prompt': 'dot'})
        self.assertEqual(len(self.calls), 1)

    def test_explicit_image_count_is_not_removed(self):
        self.reject = 'n'
        with self.assertRaisesRegex(Exception, 'Unsupported parameter: n'):
            self.gateway.generate({'kind': 'image', 'prompt': 'dot', 'count': 1})
        self.assertEqual(len(self.calls), 1)

    def test_speech_auto_format_rejection_is_retried(self):
        self.reject = 'response_format'
        result = self.gateway.generate({'kind': 'speech', 'text': 'hello'})
        self.assertEqual(result['items'][0]['extension'], 'mp3')
        self.assertEqual(len(self.calls), 2)
        self.assertNotIn('response_format', self.calls[-1][1])

    def test_speech_auto_speed_rejection_is_retried(self):
        self.reject = 'speed'
        self.gateway.generate({'kind': 'speech', 'text': 'hello'})
        self.assertEqual(len(self.calls), 2)
        self.assertNotIn('speed', self.calls[-1][1])

    def test_saved_speech_format_is_not_removed(self):
        self.reject = 'response_format'
        self.store.data['multimodal']['speech']['format'] = 'mp3'
        with self.assertRaisesRegex(Exception, 'Unsupported parameter: response_format'):
            self.gateway.generate({'kind': 'speech', 'text': 'hello'})
        self.assertEqual(len(self.calls), 1)

    def test_media_retries_429_and_503(self):
        self.statuses = [429, 503, 200]
        self.gateway.generate({'kind': 'image', 'prompt': 'dot'})
        self.assertEqual(len(self.calls), 3)

    def test_media_final_failure_keeps_all_attempts(self):
        self.statuses = [503, 503, 503]
        with self.assertRaisesRegex(Exception, 'temporary fixture overload'):
            self.gateway.generate({'kind': 'image', 'prompt': 'dot'})
        self.assertEqual(len(self.calls), 3)
        report_path = next((self.store.directory / 'request-errors').glob('*.json'))
        report = json.loads(report_path.read_text(encoding='utf-8'))
        self.assertEqual(len(report['http']), 3)

    def test_media_http_200_error_shows_remote_cause(self):
        self.error_payload = {'error': {'message': 'fixture media validation rejected', 'type': 'validation_error'}}
        for kind, text_key in [('image', 'prompt'), ('speech', 'text')]:
            with self.subTest(kind=kind), self.assertRaisesRegex(Exception, 'fixture media validation rejected'):
                self.gateway.generate({'kind': kind, text_key: 'hello'})

    def test_model_list_retries_429_and_503(self):
        self.statuses = [429, 503, 200]
        windows = fetch_model_windows(self.provider)
        self.assertIn('fixture-model', windows)
        self.assertEqual(len(self.calls), 3)

    def test_model_list_http_200_error_shows_remote_cause(self):
        self.error_payload = {'error': {'message': 'fixture catalog access denied; key=fixture-private', 'type': 'permission_error'}}
        with self.assertRaisesRegex(ValueError, 'fixture catalog access denied') as captured:
            fetch_model_windows(self.provider)
        self.assertNotIn('fixture-private', str(captured.exception))

    def test_http_session_inference_retry_traces_each_attempt(self):
        self.statuses = [429, 503, 200]
        records = []
        session = HttpSession([self.base], environment_proxy=False)
        with network_scope(records=records):
            with session.request(self.base + '/chat/completions', method='POST', data={'model': 'fixture'}) as response:
                json.load(response)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual([r['response']['status'] for r in records], [429, 503, 200])

    def test_http_session_login_is_not_retried(self):
        self.statuses = [503, 200]
        session = HttpSession([self.base], environment_proxy=False)
        with self.assertRaises(ProviderError):
            session.request(self.base + '/login', method='POST', data={'username': 'fixture'})
        self.assertEqual(len(self.calls), 1)


if __name__ == '__main__':
    unittest.main()
