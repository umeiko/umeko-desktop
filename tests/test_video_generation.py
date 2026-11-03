"""Offline, request-count-driven video lifecycle and cancellation fixtures."""
import base64
import json
import os
import ssl
import tempfile
import threading
import unittest
import urllib.parse
from contextlib import nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.gateway import Gateway
from app import generation
from app.generation import GenerationCancelled, generate, generation_config
from app.request_diagnostics import RequestFailure
from umeko_provider_sdk import Provider, ProviderContext, ProviderError, request_scope
from tests.http_fixture import peer_disconnected

MP4 = b'\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isomfixture-video'


def await_event(event):
    # Deadlines bound hangs only. No assertions use elapsed time.
    if not event.wait(30):
        raise TimeoutError('Local video fixture did not complete')


class VideoGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.calls = []
        self.jobs = [dict(id='video_fixture', status='queued', progress=0),
                     dict(id='video_fixture', status='in_progress', progress=45),
                     dict(id='video_fixture', status='completed', progress=100)]
        self.polls = 0
        self.mode = ''
        self.error_stage = ''
        self.started = threading.Event()
        self.closed = threading.Event()
        self.deleted = threading.Event()
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *_):
                pass

            def reply(self, value, content_type='application/json', status=200):
                raw = json.dumps(value).encode() if isinstance(value, dict) else value
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except OSError:
                    pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                fixture.calls.append(('POST', self.path, dict(self.headers), body))
                if fixture.error_stage == 'create':
                    return self.reply({'error': {'message': 'create quota fixture-secret'}}, status=429)
                self.reply(fixture.jobs[0])

            def do_GET(self):
                fixture.calls.append(('GET', self.path, dict(self.headers), None))
                path = urllib.parse.urlsplit(self.path).path
                stage = 'content' if path.endswith('/content') else 'poll'
                if fixture.error_stage == stage:
                    return self.reply({'error': {'message': stage + ' denied fixture-secret'}}, status=400)
                if fixture.mode == stage + '-wait' or fixture.mode == stage + '-body-wait':
                    if fixture.mode.endswith('body-wait'):
                        self.send_response(200)
                        self.send_header('Content-Type', 'video/mp4' if stage == 'content' else 'application/json')
                        self.send_header('Content-Length', '100000')
                        self.end_headers()
                        self.wfile.write(MP4 if stage == 'content' else b'{')
                        self.wfile.flush()
                    fixture.started.set()
                    self.connection.settimeout(30)
                    try:
                        if peer_disconnected(self.connection):
                            fixture.closed.set()
                    finally:
                        self.close_connection = True
                    return
                if stage == 'content':
                    return self.reply(MP4 if fixture.mode != 'invalid-content' else b'not-video', 'video/mp4')
                fixture.polls += 1
                self.reply(fixture.jobs[min(fixture.polls, len(fixture.jobs) - 1)])

            def do_DELETE(self):
                fixture.calls.append(('DELETE', self.path, dict(self.headers), None))
                fixture.deleted.set()
                self.reply({'deleted': True}, status=500 if fixture.mode == 'delete-error' else 200)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.provider = {'id': 'fixture', 'name': 'Video fixture', 'api': 'openai',
                         'baseUrl': self.base + '/v1', 'key': 'fixture-secret', 'models': [],
                         'proxy': {'mode': 'direct', 'url': ''}}
        self.store = SimpleNamespace(directory=Path(self.temp.name), data={
            'providers': [self.provider], 'multimodal': {
                'video': {'providerId': 'fixture', 'model': 'manual-video', 'seconds': '', 'size': ''}}})
        self.gateway = Gateway(self.store, None)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def run_video(self, callback=None, **options):
        return generate(self.gateway, {'kind': 'video', 'prompt': 'a moving dot', **options},
                        callback, poll_interval=0)

    def test_lifecycle_payload_and_progress(self):
        progress = []
        self.store.data['multimodal']['video'].update(seconds='8', size='1280x720')
        result = self.run_video(progress.append)
        self.assertEqual(result, {'provider': 'Video fixture', 'model': 'manual-video', 'items': [
            {'data': base64.b64encode(MP4).decode(), 'mimeType': 'video/mp4', 'extension': 'mp4'}]})
        self.assertEqual(progress, self.jobs)
        self.assertEqual([(c[0], c[1]) for c in self.calls], [
            ('POST', '/v1/videos'), ('GET', '/v1/videos/video_fixture'),
            ('GET', '/v1/videos/video_fixture'), ('GET', '/v1/videos/video_fixture/content')])
        self.assertEqual(self.calls[0][3], {'model': 'manual-video', 'prompt': 'a moving dot',
                                          'seconds': '8', 'size': '1280x720'})
        self.assertTrue(all(c[2]['Authorization'] == 'Bearer fixture-secret' for c in self.calls))

    def test_optional_parameters_are_omitted_and_overrides_used(self):
        self.jobs = [self.jobs[-1]]
        self.run_video()
        self.assertEqual(self.calls[0][3], {'model': 'manual-video', 'prompt': 'a moving dot'})
        self.store.data['multimodal']['video'].update(seconds='4', size='720x1280')
        self.run_video(seconds='12', size='1280x720')
        self.assertEqual(self.calls[2][3]['seconds'], '12')
        self.assertEqual(self.calls[2][3]['size'], '1280x720')

    def test_configuration_requires_valid_account_model_key_and_base(self):
        self.assertEqual(generation_config(self.store.data)['video'], {'provider': 'Video fixture', 'model': 'manual-video'})
        for field, value in [('key', ''), ('baseUrl', 'invalid'), ('api', 'anthropic')]:
            original = self.provider[field]
            self.provider[field] = value
            self.assertIsNone(generation_config(self.store.data)['video'])
            self.provider[field] = original
        self.store.data['multimodal']['video']['model'] = ''
        self.assertIsNone(generation_config(self.store.data)['video'])
        self.store.data['multimodal']['video'].update(model='video', providerId='missing')
        self.assertIsNone(generation_config(self.store.data)['video'])
        self.assertFalse(self.calls)

    def test_invalid_options_do_not_send_requests(self):
        for options in ({'seconds': 8}, {'seconds': '0'}, {'seconds': '-4'},
                        {'size': 'HD'}, {'size': '0x720'}, {'size': []}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.run_video(**options)
        self.assertFalse(self.calls)

    def test_failed_job_reason_and_secret_redaction(self):
        self.jobs[1] = dict(id='video_fixture', status='failed', progress=20,
                            error={'message': 'video policy fixture-secret'})
        with self.assertRaises(RequestFailure) as captured:
            self.run_video()
        self.assertIn('video policy', str(captured.exception))
        self.assertNotIn('fixture-secret', str(captured.exception))
        self.assertEqual(len(self.calls), 2)

    def test_http_reasons_at_create_poll_and_content(self):
        self.jobs = [self.jobs[0], self.jobs[-1]]
        for stage in ('create', 'poll', 'content'):
            self.error_stage = stage
            with self.subTest(stage=stage), self.assertRaises(RequestFailure) as captured:
                self.run_video()
            self.assertIn(stage, str(captured.exception))
            self.assertNotIn('fixture-secret', str(captured.exception))
        reports = list((Path(self.temp.name) / 'request-errors').glob('*.json'))
        self.assertTrue(reports)
        self.assertTrue(all('fixture-secret' not in p.read_text(encoding='utf-8') for p in reports))

    def test_invalid_media_is_rejected(self):
        self.mode = 'invalid-content'
        with self.assertRaises(RequestFailure):
            self.run_video()

    def test_cancel_from_progress_stops_polling_and_ignores_delete_error(self):
        self.mode = 'delete-error'
        cancelled = threading.Event()
        progress = []
        def callback(value):
            progress.append(value)
            cancelled.set()
        with request_scope(cancelled), self.assertRaises(GenerationCancelled):
            self.run_video(callback)
        self.assertEqual(progress, [self.jobs[0]])
        self.assertEqual([(c[0], c[1]) for c in self.calls],
                         [('POST', '/v1/videos'), ('DELETE', '/v1/videos/video_fixture')])
        self.assertFalse((Path(self.temp.name) / 'request-errors').exists())

    def run_transport_cancel(self, mode):
        self.mode = mode
        if mode.startswith('content'):
            self.jobs = [self.jobs[-1]]
        cancelled, finished = threading.Event(), threading.Event()
        results, errors = [], []
        def run():
            try:
                with request_scope(cancelled):
                    results.append(self.run_video())
            except Exception as exc:
                errors.append(exc)
            finally:
                finished.set()
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        await_event(self.started)
        cancelled.set()
        await_event(finished)
        await_event(self.closed)
        worker.join()
        self.assertFalse(results)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], GenerationCancelled)
        self.assertTrue(self.deleted.is_set())
        self.assertEqual(self.calls[-1][0], 'DELETE')

    def test_cancel_during_poll_headers(self):
        self.run_transport_cancel('poll-wait')

    def test_cancel_during_poll_body(self):
        self.run_transport_cancel('poll-body-wait')

    def test_cancel_during_content_headers(self):
        self.run_transport_cancel('content-wait')

    def test_cancel_during_content_body(self):
        self.run_transport_cancel('content-body-wait')

    def test_cancel_interrupts_poll_interval_wait(self):
        waiting = threading.Event()
        class CancelEvent(threading.Event):
            def wait(self, timeout=None):
                if timeout == 60:
                    waiting.set()
                return super().wait(timeout)
        cancelled, finished = CancelEvent(), threading.Event()
        errors = []
        def run():
            try:
                with request_scope(cancelled):
                    generate(self.gateway, {'kind': 'video', 'prompt': 'wait fixture'}, poll_interval=60)
            except Exception as exc:
                errors.append(exc)
            finally:
                finished.set()
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        await_event(waiting)
        cancelled.set()
        await_event(finished)
        worker.join()
        self.assertIsInstance(errors[0], GenerationCancelled)
        self.assertEqual([c[0] for c in self.calls], ['POST', 'DELETE'])

    def test_late_completion_and_download_are_discarded_after_cancel(self):
        self.jobs = [self.jobs[0], self.jobs[-1]]
        original = generation._Transport.request
        for suffix in ('/video_fixture', '/content'):
            cancelled = threading.Event()
            def request(transport, url, *args, **kwargs):
                result = original(transport, url, *args, **kwargs)
                if url.endswith(suffix) and kwargs.get('method') != 'DELETE':
                    cancelled.set()
                return result
            with self.subTest(stage=suffix), request_scope(cancelled), \
                    patch.object(generation._Transport, 'request', request), self.assertRaises(GenerationCancelled):
                self.run_video()
            self.assertEqual(self.calls[-1][0], 'DELETE')

    def test_proxy_and_ca_policy_reused_for_lifecycle(self):
        policy = {'mode': 'direct', 'url': '', 'caFile': 'configured-ca.pem'}
        self.provider['proxy'] = policy
        with patch.object(generation, 'proxy_handler', wraps=generation.proxy_handler) as proxy, \
             patch.object(generation, 'tls_context', return_value=ssl.create_default_context()) as tls:
            self.run_video()
        proxy.assert_called_once_with(policy)
        tls.assert_called_once_with(policy)
        self.assertEqual(len(self.calls), 4)

    def test_custom_proxy_receives_create_poll_and_download(self):
        self.provider.update(baseUrl='http://provider.invalid/v1', proxy={'mode': 'custom', 'url': self.base})
        with patch.dict(os.environ, {'no_proxy': '', 'NO_PROXY': ''}):
            self.run_video()
        self.assertTrue(all(c[1].startswith('http://provider.invalid/v1/videos') for c in self.calls))

    def test_configured_ca_accepts_real_local_tls_lifecycle(self):
        certificates = Path(__file__).parent / 'fixtures/update-tls'
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certificates / 'server.pem', certificates / 'server-key.pem')
        server = ThreadingHTTPServer(('127.0.0.1', 0), self.server.RequestHandlerClass)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            self.provider.update(baseUrl=f'https://127.0.0.1:{server.server_port}/v1',
                proxy={'mode': 'direct', 'url': '', 'caFile': str(certificates / 'ca.pem')})
            self.assertEqual(base64.b64decode(self.run_video()['items'][0]['data']), MP4)
        finally:
            server.shutdown()
            server.server_close()
            worker.join()

    def test_sdk_optional_extension_and_plugin_dispatch(self):
        from app.provider_plugins import ProviderPlugins
        provider = Provider(ProviderContext({}, Path(self.temp.name), None))
        with self.assertRaisesRegex(ProviderError, '视频'):
            provider.generate_video('video', 'dot', {})
        calls = []
        def video(model, prompt, options, on_progress=None):
            calls.append((model, prompt, options))
            if on_progress:
                on_progress(self.jobs[-1])
            return [{'data': MP4, 'mimeType': 'video/mp4'}]
        client = SimpleNamespace(generate_video=video)
        dispatcher = SimpleNamespace(_record=lambda _: {},
            _package=lambda _: (None, ({'generationCapabilities': ['video']}, {}, {})),
            _lease=lambda _: nullcontext(client))
        class Plugins:
            def generate(_, *args, **kwargs):
                return ProviderPlugins.generate(dispatcher, *args, **kwargs)
        self.gateway.plugins = Plugins()
        self.provider.update(api='plugin', key='', generationCapabilities=['video'])
        progress = []
        self.assertEqual(self.run_video(progress.append)['items'][0]['extension'], 'mp4')
        self.assertEqual(progress, [self.jobs[-1]])
        self.assertEqual(calls, [('manual-video', 'a moving dot', {})])

    def test_plugin_manifest_accepts_video_capability(self):
        from umeko_provider_sdk.packages import validate_folder
        from app.provider_plugins import ProviderPlugins
        folder = Path(self.temp.name) / 'video-plugin'
        (folder / 'scripts').mkdir(parents=True)
        (folder / 'scripts/provider.py').write_text('def create_provider(context): pass\n', encoding='utf-8')
        (folder / 'config.json').write_text('{}', encoding='utf-8')
        (folder / 'config.schema.json').write_text('{"type":"object"}', encoding='utf-8')
        manifest = {'apiVersion': 1, 'id': 'video-fixture', 'version': '1.0.0', 'name': 'Video fixture',
                    'entrypoint': 'scripts/provider.py:create_provider', 'generationCapabilities': ['video']}
        (folder / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        validated, _, _ = validate_folder(folder)
        self.assertEqual(ProviderPlugins._new_account(validated)['generationCapabilities'], ['video'])


if __name__ == '__main__':
    unittest.main()
