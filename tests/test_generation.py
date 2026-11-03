"""Offline protocol and cancellation fixtures; no installed application profile."""
import base64
import copy
import http.client
import json
import os
import socket
import ssl
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.gateway import Gateway, LocalServer
from app.generation import GenerationCancelled, generation_config
from app.request_diagnostics import RequestFailure
from umeko_provider_sdk import Provider, ProviderContext, ProviderError, request_scope
from tests.http_fixture import peer_disconnected

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=')
AUDIO = b'ID3\x04\x00\x00fixture-audio'


def await_event(event):
    # The deadline only bounds a hung test; assertions concern state and EOF,
    # never elapsed duration or a cancellation latency target.
    if not event.wait(30):
        raise TimeoutError('Local fixture did not complete')


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.mode = 'b64'
        self.calls = []
        self.started = threading.Event()
        self.upstream_closed = threading.Event()
        self.upstream_observed = threading.Event()
        self.upstream_outcome = None
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *_):
                pass

            def reply(self, raw, content_type='application/json', status=200):
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                fixture.calls.append((self.path, dict(self.headers), body))
                if fixture.mode in ('headers-wait', 'body-wait'):
                    if fixture.mode == 'body-wait':
                        self.send_response(200)
                        self.send_header('Content-Type', 'audio/mpeg')
                        self.send_header('Content-Length', '100000')
                        self.end_headers()
                        self.wfile.write(AUDIO)
                        self.wfile.flush()
                    fixture.started.set()
                    self.connection.settimeout(60)
                    try:
                        closed = peer_disconnected(self.connection)
                        fixture.upstream_outcome = {'state': 'peer-disconnected' if closed else 'unexpected-data'}
                        if closed:
                            fixture.upstream_closed.set()
                    except OSError as exc:
                        fixture.upstream_outcome = {'state': 'error', 'error': repr(exc)}
                    finally:
                        fixture.upstream_observed.set()
                        self.close_connection = True
                    return
                if fixture.mode == 'error':
                    return self.reply(json.dumps({'error': {'message': 'test quota reason; key=fixture-secret', 'code': 'insufficient_quota'}}).encode(), status=429)
                if self.path == '/v1/audio/speech':
                    return self.reply(AUDIO, 'audio/mpeg')
                if fixture.mode == 'url':
                    value = {'url': fixture.base + '/media.png?signature=private'}
                elif fixture.mode == 'bad':
                    value = {'b64_json': '%%%'}
                elif fixture.mode == 'oversize':
                    self.send_response(200)
                    self.send_header('Content-Length', '1000000000')
                    self.end_headers()
                    self.close_connection = True
                    return
                else:
                    value = {'b64_json': base64.b64encode(PNG).decode()}
                self.reply(json.dumps({'data': [value]}).encode())

            def do_GET(self):
                fixture.calls.append((self.path, dict(self.headers), None))
                self.reply(PNG, 'image/png')

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)
        provider = {'id': 'fixture', 'name': 'Fixture account', 'api': 'openai',
                    'baseUrl': self.base + '/v1', 'key': 'fixture-secret', 'models': [],
                    'proxy': {'mode': 'direct', 'url': ''}}
        self.store = SimpleNamespace(directory=Path(self.temp.name), data={
            'providers': [provider], 'multimodal': {
                'image': {'providerId': 'fixture', 'model': 'manual-image'},
                'speech': {'providerId': 'fixture', 'model': 'manual-voice', 'voice': 'test-voice'}}})
        self.gateway = Gateway(self.store, None)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_b64_image_raw_model_and_defaults(self):
        result = self.gateway.generate({'kind': 'image', 'prompt': 'a dot', 'size': '1024x1024', 'quality': 'test-quality', 'format': 'png'})
        self.assertEqual(result, {'provider': 'Fixture account', 'model': 'manual-image',
            'items': [{'data': base64.b64encode(PNG).decode(), 'mimeType': 'image/png', 'extension': 'png'}]})
        path, headers, body = self.calls[0]
        self.assertEqual(path, '/v1/images/generations')
        self.assertEqual(headers['Authorization'], 'Bearer fixture-secret')
        self.assertEqual(body, {'model': 'manual-image', 'prompt': 'a dot', 'n': 1, 'size': '1024x1024', 'quality': 'test-quality', 'output_format': 'png'})

    def test_url_image_download_has_no_provider_authorization(self):
        self.mode = 'url'
        result = self.gateway.generate({'kind': 'image', 'prompt': 'a dot'})
        self.assertEqual(base64.b64decode(result['items'][0]['data']), PNG)
        self.assertEqual(len(self.calls), 2)
        self.assertNotIn('Authorization', self.calls[1][1])
        self.assertNotIn('response_format', self.calls[0][2])
        self.assertNotIn('size', self.calls[0][2])

    def test_speech_binary_and_current_configuration(self):
        self.store.data['multimodal']['speech']['model'] = 'new-voice-model'
        result = self.gateway.generate({'kind': 'speech', 'text': 'hello', 'speed': 1.25})
        self.assertEqual(base64.b64decode(result['items'][0]['data']), AUDIO)
        self.assertEqual(result['items'][0]['extension'], 'mp3')
        self.assertEqual(self.calls[0][0], '/v1/audio/speech')
        self.assertEqual(self.calls[0][2], {'model': 'new-voice-model', 'input': 'hello', 'voice': 'test-voice', 'response_format': 'mp3', 'speed': 1.25})

    def test_configuration_description_requires_voice_and_valid_account(self):
        self.assertEqual(generation_config(self.store.data)['image'], {'provider': 'Fixture account', 'model': 'manual-image'})
        self.store.data['multimodal']['speech']['voice'] = ''
        self.assertIsNone(generation_config(self.store.data)['speech'])
        self.store.data['providers'][0]['api'] = 'anthropic'
        self.assertIsNone(generation_config(self.store.data)['image'])
        with self.assertRaises(ValueError):
            self.gateway.generate({'kind': 'image', 'prompt': 'a dot'})
        self.assertFalse(self.calls)

    def test_error_reason_is_preserved_and_secret_is_redacted(self):
        self.mode = 'error'
        with self.assertRaises(RequestFailure) as captured:
            self.gateway.generate({'kind': 'image', 'prompt': 'a dot'})
        self.assertIn('test quota reason', str(captured.exception))
        self.assertNotIn('fixture-secret', str(captured.exception))
        self.assertFalse(captured.exception.retryable)
        report = next((Path(self.temp.name) / 'request-errors').glob('*.json')).read_text(encoding='utf-8')
        self.assertNotIn('fixture-secret', report)

    def test_success_media_not_added_to_diagnostic_records(self):
        self.mode = 'bad'
        with self.assertRaises(RequestFailure):
            self.gateway.generate({'kind': 'image', 'prompt': 'a dot'})
        report = next((Path(self.temp.name) / 'request-errors').glob('*.json')).read_text(encoding='utf-8')
        self.assertNotIn('b64_json', report)

    def test_response_size_bound(self):
        self.mode = 'oversize'
        with self.assertRaises(RequestFailure):
            self.gateway.generate({'kind': 'image', 'prompt': 'a dot'})

    def test_proxy_and_ca_policy_used_for_generation_and_media(self):
        self.mode = 'url'
        from app import generation
        policy = {'mode': 'direct', 'url': '', 'caFile': 'configured-ca.pem'}
        self.store.data['providers'][0]['proxy'] = policy
        with patch.object(generation, 'proxy_handler', wraps=generation.proxy_handler) as proxy, \
             patch.object(generation, 'tls_context', return_value=__import__('ssl').create_default_context()) as tls:
            self.gateway.generate({'kind': 'image', 'prompt': 'a dot'})
        proxy.assert_called_once_with(policy)
        tls.assert_called_once_with(policy)
        self.assertEqual(len(self.calls), 2)

    def test_custom_proxy_receives_the_generation_request(self):
        provider = self.store.data['providers'][0]
        provider['baseUrl'] = 'http://provider.invalid/v1'
        provider['proxy'] = {'mode': 'custom', 'url': self.base}
        with patch.dict(os.environ, {'no_proxy': '', 'NO_PROXY': ''}):
            self.gateway.generate({'kind': 'image', 'prompt': 'proxy fixture'})
        self.assertEqual(self.calls[0][0], 'http://provider.invalid/v1/images/generations')
        self.assertEqual(self.calls[0][2]['model'], 'manual-image')

    def test_provider_ca_validates_a_real_local_tls_generation_request(self):
        certificates = Path(__file__).parent / 'fixtures/update-tls'
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certificates / 'server.pem', certificates / 'server-key.pem')
        server = ThreadingHTTPServer(('127.0.0.1', 0), self.server.RequestHandlerClass)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = self.store.data['providers'][0]
            provider['baseUrl'] = f'https://127.0.0.1:{server.server_port}/v1'
            provider['proxy'] = {'mode': 'direct', 'url': '', 'caFile': str(certificates / 'ca.pem')}
            result = self.gateway.generate({'kind': 'image', 'prompt': 'TLS fixture'})
            self.assertEqual(base64.b64decode(result['items'][0]['data']), PNG)
            self.assertEqual(self.calls[0][0], '/v1/images/generations')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def run_cancel(self, mode):
        self.mode = mode
        cancelled = threading.Event()
        errors = []
        finished = threading.Event()
        read_started = threading.Event()
        original_read = http.client.HTTPResponse.read
        def read_response(response, *args, **kwargs):
            read_started.set()
            return original_read(response, *args, **kwargs)
        def run():
            try:
                with request_scope(cancelled):
                    self.gateway.generate({'kind': 'speech', 'text': 'hello'})
            except Exception as exc:
                errors.append(exc)
            finally:
                finished.set()
        with patch.object(http.client.HTTPResponse, 'read', read_response):
            worker = threading.Thread(target=run, daemon=True)
            worker.start()
            await_event(self.started)
            if mode == 'body-wait':
                # A server write alone does not mean the client has finished
                # reading headers and entered its blocking response-body read.
                await_event(read_started)
            cancelled.set()
            await_event(finished)
            await_event(self.upstream_observed)
            worker.join()
        self.assertTrue(self.upstream_closed.is_set(), self.upstream_outcome)
        self.assertEqual(len(errors), 1, errors)
        self.assertIsInstance(errors[0], GenerationCancelled)
        self.assertFalse((Path(self.temp.name) / 'request-errors').exists())
        self.cancel_observation = {'mode': mode, 'response_read_entered': read_started.is_set(),
            'worker_finished': finished.is_set(), 'upstream': self.upstream_outcome,
            'exception': type(errors[0]).__name__}

    def test_cancel_before_response_headers_aborts_upstream(self):
        self.run_cancel('headers-wait')

    def test_cancel_during_response_read_aborts_upstream(self):
        self.run_cancel('body-wait')

    def test_private_endpoint_and_public_exclusion(self):
        private = LocalServer(self.gateway, 0, 'private-fixture', private=True)
        public = LocalServer(self.gateway, 0, 'public-fixture')
        self.addCleanup(private.close)
        self.addCleanup(public.close)
        def request(server, token):
            return urllib.request.Request('http://127.0.0.1:' + str(server.port) + '/umeko/generate',
                data=json.dumps({'kind': 'image', 'prompt': 'a dot'}).encode(),
                headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request(private, 'private-fixture')) as response:
            self.assertEqual(json.load(response)['model'], 'manual-image')
        with self.assertRaises(urllib.error.HTTPError) as captured:
            urllib.request.urlopen(request(public, 'public-fixture'))
        self.assertEqual(captured.exception.code, 404)
        captured.exception.close()
        self.assertEqual(len(self.calls), 1)

    def test_private_disconnect_cancels_generation(self):
        self.mode = 'headers-wait'
        private = LocalServer(self.gateway, 0, 'private-fixture', private=True)
        self.addCleanup(private.close)
        client = socket.create_connection(('127.0.0.1', private.port))
        self.addCleanup(client.close)
        raw = json.dumps({'kind': 'speech', 'text': 'hello'}).encode()
        client.sendall(b'POST /umeko/generate HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer private-fixture\r\nContent-Length: ' + str(len(raw)).encode() + b'\r\n\r\n' + raw)
        await_event(self.started)
        client.shutdown(socket.SHUT_RDWR)
        client.close()
        await_event(self.upstream_closed)

    def test_plugin_extension_defaults_and_dispatch(self):
        context = ProviderContext({}, Path(self.temp.name), None)
        provider = Provider(context)
        with self.assertRaises(ProviderError):
            provider.generate_image('fixture', 'dot', {})
        with self.assertRaises(ProviderError):
            provider.generate_speech('fixture', 'hello', {})
        self.store.data['providers'][0].update(api='plugin', key='', generationCapabilities=['image'])
        calls = []
        class Plugins:
            def generate(self, *args):
                calls.append(args)
                return [{'data': PNG, 'mimeType': 'image/png'}]
        self.gateway.plugins = Plugins()
        self.assertEqual(self.gateway.generate({'kind': 'image', 'prompt': 'dot'})['items'][0]['extension'], 'png')
        self.assertEqual(calls[0][:4], ('fixture', 'image', 'manual-image', 'dot'))

    def test_plugin_manifest_generation_declaration(self):
        from umeko_provider_sdk.packages import validate_folder
        from app.provider_plugins import ProviderPlugins
        folder = Path(self.temp.name) / 'provider'
        (folder / 'scripts').mkdir(parents=True)
        (folder / 'scripts/provider.py').write_text('def create_provider(context): pass\n', encoding='utf-8')
        (folder / 'config.json').write_text('{}', encoding='utf-8')
        (folder / 'config.schema.json').write_text('{"type":"object"}', encoding='utf-8')
        manifest = {'apiVersion': 1, 'id': 'generation-fixture', 'version': '1.0.0',
                    'name': 'Generation fixture', 'entrypoint': 'scripts/provider.py:create_provider',
                    'generationCapabilities': ['image', 'speech']}
        (folder / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        validated, _, _ = validate_folder(folder)
        self.assertEqual(ProviderPlugins._new_account(validated)['generationCapabilities'], ['image', 'speech'])
        invalid = copy.deepcopy(manifest)
        invalid['generationCapabilities'] = ['image', 'unsupported']
        (folder / 'manifest.json').write_text(json.dumps(invalid), encoding='utf-8')
        with self.assertRaises(ProviderError):
            validate_folder(folder)


if __name__ == '__main__':
    unittest.main()
