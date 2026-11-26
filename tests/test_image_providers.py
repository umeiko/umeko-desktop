"""Offline account and protocol contracts for the built-in image providers."""
import base64
import copy
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication
from app.controller import Controller
from app.gateway import Gateway
from app.generation import generation_config
from app.image_providers import PRESETS, CUSTOM_PRESET, profile
from app.multimodal_settings import DEFAULTS
from app.request_diagnostics import RequestFailure
from app.storage import Store

ROOT = Path(__file__).resolve().parents[1]
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAUAAAAC0CAIAAABqhmJGAAACJ0lEQVR4nO3TQQ0AIBDAsDOKHUSgFg98yJImFbDPZp0NRM33AuCZgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEGZgCDMwhBkYwgwMYQaGMANDmIEhzMAQZmAIMzCEGRjCDAxhBoYwA0OYgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEGZgCDMwhBkYwgwMYQaGMANDmIEhzMAQZmAIMzCEGRjCDAxhBoYwA0OYgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEGZgCDMwhBkYwgwMYQaGMANDmIEhzMAQZmAIMzCEGRjCDAxhBoYwA0OYgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEGZgCDMwhBkYwgwMYQaGMANDmIEhzMAQZmAIMzCEGRjCDAxhBoYwA0OYgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEGZgCDMwhBkYwgwMYQaGMANDmIEhzMAQZmAIMzCEGRjCDAxhBoYwA0OYgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEGZgCDMwhBkYwgwMYQaGMANDmIEhzMAQZmAIMzCEGRjCDAxhBoYwA0OYgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEGZgCDMwhBkYwgwMYQaGMANDmIEhzMAQZmAIMzCEGRjCDAxhBoYwA0OYgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEHYBQnrwk3UEUloAAAAASUVORK5CYII=')


class ImageProviderAccountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='umeko-image-provider-')
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, UMEKO_DATA_DIR=self.temp.name, PI_CODING_AGENT_DIR=str(Path(self.temp.name)/'agent'))
        env.start(); self.addCleanup(env.stop)
        with patch('app.provider_plugins.BundledProviders.sync', return_value=[]):
            self.b = Controller(ROOT)
        self.addCleanup(self.b.close)

    def test_key_only_presets_activate_images_without_changing_chat_or_exposing_keys(self):
        chat = (self.b.store.data['selectedProvider'], self.b.store.data['selectedModel'])
        for preset in PRESETS:
            with patch.object(self.b, '_job', side_effect=AssertionError('Adding an account must not contact the provider')):
                self.assertTrue(self.b.saveImageProvider(preset['id'], 'fixture-image-secret'))
            selected = self.b.store.data['multimodal']['image']
            provider = self.b.gateway.provider(selected['providerId'])
            self.assertEqual((provider['api'], provider['models']), ('image', []))
            self.assertEqual(selected['model'], preset['models'][0])
            self.assertEqual(provider['baseUrl'], preset['baseUrl'])
            self.assertEqual((self.b.store.data['selectedProvider'], self.b.store.data['selectedModel']), chat)
            self.assertEqual(self.b.gateway.models(), [])
            public = json.dumps([self.b.config, self.b.imageProviders, self.b.imageProviderPresets, generation_config(self.b.store.data)])
            self.assertNotIn('fixture-image-secret', public)
            self.assertNotIn('fixture-image-secret', self.b.store.path.read_text())
            self.assertEqual(Store(Path(self.temp.name)).data['providers'][-1]['key'], 'fixture-image-secret')
            self.assertTrue(preset['keyUrl'].startswith('https://'))
        self.assertEqual(len(self.b.imageProviders), 2)

    def test_edits_keep_the_account_and_blank_key_and_do_not_write_unchanged_credentials(self):
        self.assertTrue(self.b.saveImageProvider('qwen-image', 'fixture-key'))
        identifier = self.b.imageProviders[0]['id']
        with patch.object(self.b.store, 'save') as save, patch.object(self.b, '_restart_pi') as restart:
            self.assertTrue(self.b.saveImageProvider('qwen-image', ''))
            save.assert_not_called(); restart.assert_not_called()
        self.assertTrue(self.b.saveImageProvider('qwen-image', 'replacement-key'))
        self.assertEqual(len(self.b.imageProviders), 1)
        self.assertNotEqual(self.b.imageProviders[0]['id'], identifier)
        self.assertIsNone(self.b.gateway.provider(identifier))
        self.assertEqual(self.b.gateway.provider(self.b.imageProviders[0]['id'])['key'], 'replacement-key')

    def test_custom_openai_accounts_round_trip_edit_and_remove_independently(self):
        def save(**changes):
            return self.b.saveCustomImageProvider(json.dumps({'name': 'My images', 'baseUrl': 'https://images.example/v1',
                'model': 'custom-image', 'key': 'custom-secret', **changes}))
        self.assertTrue(save())
        first = self.b.imageProviders[0]['id']
        self.assertTrue(save(name='Second service'))
        second = self.b.imageProviders[1]['id']
        self.assertNotEqual(first, second)
        self.assertTrue(save(id=second, name='Updated service', model='new-image', key=''))
        self.assertEqual(len(self.b.imageProviders), 2)
        self.assertEqual(self.b.store.data['multimodal']['image']['model'], 'new-image')
        self.assertEqual(self.b.gateway.provider(second)['key'], 'custom-secret')
        self.assertNotIn('custom-secret', self.b.store.path.read_text())
        self.assertNotIn('custom-secret', json.dumps([self.b.config, self.b.imageProviders]))
        self.assertEqual(Store(Path(self.temp.name)).data['providers'][1]['key'], 'custom-secret')
        self.assertEqual(self.b.gateway.models(), [])
        before = copy.deepcopy(self.b.store.data)
        for invalid in ({'baseUrl': 'file:///tmp/images'}, {'name': ''}, {'model': 'bad\nmodel'}, {'id': 'missing'}, {'key': 'bad\nkey'}):
            self.assertFalse(save(**invalid))
            self.assertEqual(self.b.store.data, before)
        self.assertTrue(self.b.removeImageProvider(first))
        self.assertEqual(self.b.store.data['multimodal']['image']['providerId'], second)
        self.b.removeProvider(second)
        self.assertFalse(self.b.imageProviders)
        self.assertEqual(self.b.store.data['multimodal']['image'], DEFAULTS['image'])

    def test_failed_file_replacement_does_not_overwrite_the_old_persisted_key(self):
        self.assertTrue(self.b.saveImageProvider('qwen-image', 'original-image-key'))
        identifier = self.b.imageProviders[0]['id']
        with patch.object(Path, 'replace', side_effect=OSError('fixture atomic replacement failed')):
            self.assertFalse(self.b.saveImageProvider('qwen-image', 'new-image-key'))
        self.assertEqual(self.b.gateway.provider(identifier)['key'], 'original-image-key')
        disk = Store(Path(self.temp.name))
        self.assertEqual(disk.data['providers'][0]['key'], 'original-image-key')
        self.assertEqual(disk.data['multimodal']['image']['providerId'], identifier)

    def test_validation_and_failed_save_preserve_accounts_selections_and_drafts(self):
        self.b.store.data['sessionMeta']['history'] = {'draft': 'Keep this draft'}
        before = copy.deepcopy(self.b.store.data)
        for preset, key in [('missing', 'fixture'), ('qwen-image', ''), ('qwen-image', 'bad\nkey')]:
            self.assertFalse(self.b.saveImageProvider(preset, key))
            self.assertEqual(self.b.store.data, before)
        with patch.object(self.b.store, 'save', side_effect=OSError('fixture write failure')), patch.object(self.b, '_restart_pi') as restart:
            self.assertFalse(self.b.saveImageProvider('qwen-image', 'fixture-key'))
            self.assertEqual(self.b.store.data, before)
            restart.assert_not_called()

    def test_remove_clears_only_the_selected_image_account(self):
        self.assertTrue(self.b.saveImageProvider('qwen-image', 'fixture-key'))
        self.assertTrue(self.b.saveImageProvider('volcengine-image', 'fixture-key'))
        voice = dict(self.b.store.data['multimodal']['speech'])
        self.assertTrue(self.b.removeImageProvider('qwen-image'))
        self.assertEqual(len(self.b.imageProviders), 1)
        self.assertTrue(self.b.store.data['multimodal']['image']['providerId'])
        self.assertTrue(self.b.removeImageProvider('volcengine-image'))
        self.assertEqual(self.b.store.data['multimodal']['image'], DEFAULTS['image'])
        self.assertEqual(self.b.store.data['multimodal']['speech'], voice)
        self.assertEqual(Store(Path(self.temp.name)).data['providers'], [])

    def test_busy_generation_blocks_account_changes_and_settings_validate_capabilities(self):
        self.assertTrue(self.b.saveImageProvider('volcengine-image', 'fixture-key'))
        identifier = self.b.imageProviders[0]['id']
        self.b._view.phase = 'running'
        try:
            self.assertFalse(self.b.saveImageProvider('volcengine-image', 'changed-key'))
            self.assertFalse(self.b.removeImageProvider('volcengine-image'))
        finally:
            self.b._view.phase = 'idle'
        self.assertFalse(self.b.saveMultimodalSettings(json.dumps({'image': {'count': 2}})))
        self.assertFalse(self.b.saveMultimodalSettings(json.dumps({'image': {'format': 'webp'}})))
        self.assertEqual(self.b.gateway.provider(identifier)['key'], 'fixture-key')
        self.assertTrue(self.b.saveMultimodalSettings(json.dumps({'image': {'size': '2048x2048', 'format': 'png'}})))

    def test_dedicated_speech_and_video_providers_stay_out_of_chat_models(self):
        self.assertTrue(self.b.saveCustomMultimodalProvider('speech', json.dumps({
            'name': 'My voice service', 'baseUrl': 'https://voice.example/v1', 'model': 'tts-1', 'key': 'voice-secret'})))
        self.assertTrue(self.b.saveCustomMultimodalProvider('video', json.dumps({
            'name': 'My video service', 'baseUrl': 'https://video.example/v1', 'model': 'vid-1', 'key': 'video-secret'})))
        self.assertEqual(self.b.gateway.models(), [])
        speech_id = self.b.store.data['multimodal']['speech']['providerId']
        video_id = self.b.store.data['multimodal']['video']['providerId']
        self.assertEqual(self.b.store.data['multimodal']['speech']['model'], 'tts-1')
        self.assertEqual(self.b.store.data['multimodal']['video']['model'], 'vid-1')
        self.assertEqual(len(self.b.multimodalProviders), 2)
        self.assertNotIn('voice-secret', self.b.store.path.read_text())
        self.assertNotIn('video-secret', self.b.store.path.read_text())
        self.assertTrue(self.b.removeMultimodalProvider(speech_id))
        self.assertEqual(self.b.store.data['multimodal']['speech'], DEFAULTS['speech'])
        self.assertTrue(self.b.removeMultimodalProvider(video_id))
        self.assertEqual(self.b.store.data['multimodal']['video'], DEFAULTS['video'])
        self.assertFalse(self.b.multimodalProviders)


class ImageProviderProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.calls = []; self.mode = 'normal'
        fixture = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def reply(self, body, content_type='application/json', status=200):
                self.send_response(status); self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                fixture.calls.append((self.path, dict(self.headers), body))
                url = f'http://127.0.0.1:{self.server.server_port}/result.png'
                if fixture.mode == 'error': value = {'code': 'QuotaExceeded', 'message': 'fixture-image-secret quota exhausted'}
                elif fixture.mode == 'malformed': value = {'output': {'choices': [{'message': {'content': 'bad'}}]}}
                elif 'multimodal-generation' in self.path: value = {'output': {'choices': [{'message': {'content': [{'text': 'Done'}, {'image': url}]}}]}}
                else: value = {'data': [{'url': url}]} if fixture.mode != 'b64' else {'data': [{'b64_json': base64.b64encode(PNG).decode()}]}
                self.reply(json.dumps(value).encode())
            def do_GET(self):
                fixture.calls.append((self.path, dict(self.headers), None)); self.reply(PNG, 'image/png')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def gateway(self, preset_id, model=None):
        preset = next(p for p in [*PRESETS, CUSTOM_PRESET] if p['id'] == preset_id)
        provider = {'id': 'fixture', 'name': preset['name'], 'api': 'image', 'key': 'fixture-image-secret',
                    'models': [], 'presetId': preset_id, 'imageProtocol': preset['protocol'],
                    'baseUrl': f'http://127.0.0.1:{self.server.server_port}/api', 'proxy': {'mode': 'direct', 'url': ''}}
        store = SimpleNamespace(directory=Path(self.temp.name), data={'providers': [provider],
            'multimodal': {'image': {'providerId': 'fixture', 'model': model or preset.get('models', ['custom-image'])[0]}}})
        return Gateway(store, None)

    def test_dashscope_request_normalizes_dimensions_and_downloads_without_credentials(self):
        gateway = self.gateway('qwen-image')
        result = gateway.generate({'kind': 'image', 'prompt': 'an orange cat', 'size': '1024x1024', 'format': 'png'})
        self.assertEqual(base64.b64decode(result['items'][0]['data']), PNG)
        path, headers, body = self.calls[0]
        self.assertEqual(path, '/api/services/aigc/multimodal-generation/generation')
        self.assertEqual(headers['Authorization'], 'Bearer fixture-image-secret')
        self.assertEqual(body, {'model': 'qwen-image-3.0-pro', 'input': {'messages': [{'role': 'user', 'content': [{'text': 'an orange cat'}]}]}, 'parameters': {'n': 1, 'size': '1024*1024'}})
        self.assertNotIn('Authorization', self.calls[1][1])
        self.assertEqual(generation_config(gateway.store.data)['image']['maxCount'], 6)

    def test_ark_request_omits_unsupported_n_and_quality(self):
        gateway = self.gateway('volcengine-image')
        result = gateway.generate({'kind': 'image', 'prompt': 'an orange cat', 'size': '2K', 'format': 'png'})
        self.assertEqual(base64.b64decode(result['items'][0]['data']), PNG)
        path, headers, body = self.calls[0]
        self.assertEqual(path, '/api/images/generations')
        self.assertEqual(headers['Authorization'], 'Bearer fixture-image-secret')
        self.assertEqual(body, {'model': 'doubao-seedream-5-5-261028', 'prompt': 'an orange cat', 'size': '2K', 'output_format': 'png', 'response_format': 'url'})
        self.assertNotIn('Authorization', self.calls[1][1])
        self.assertEqual(generation_config(gateway.store.data)['image']['maxCount'], 1)

    def test_custom_openai_request_supports_arbitrary_model_and_base64_response(self):
        gateway = self.gateway('openai-image'); self.mode = 'b64'
        result = gateway.generate({'kind': 'image', 'prompt': 'a cat', 'size': '1024x1024', 'quality': 'high', 'format': 'png'})
        self.assertEqual(base64.b64decode(result['items'][0]['data']), PNG)
        self.assertEqual(self.calls[0][0], '/api/images/generations')
        self.assertEqual(self.calls[0][2], {'model': 'custom-image', 'prompt': 'a cat', 'n': 1, 'size': '1024x1024', 'quality': 'high', 'output_format': 'png'})

    def test_each_native_model_uses_its_own_limits_and_request_shape(self):
        for preset in PRESETS:
            for model in preset['models']:
                with self.subTest(model=model):
                    gateway = self.gateway(preset['id'], model)
                    limits = profile(gateway.store.data['providers'][0], model)
                    count = min(3, limits['maxCount'])
                    size = limits['sizeTiers'][-1] if limits['sizeTiers'] else '1024x1024'
                    gateway.generate({'kind': 'image', 'prompt': 'a cat', 'size': size, 'count': count, 'format': limits['formats'][0]})
                    body = self.calls[-2][2]
                    self.assertEqual(body['model'], model)
                    if preset['protocol'] == 'ark':
                        self.assertNotIn('n', body)
                        if count > 1:
                            self.assertEqual(body['sequential_image_generation_options'], {'max_images': count})
                        if 'seedream-4-' in model:
                            self.assertNotIn('output_format', body)
                    self.assertEqual(generation_config(gateway.store.data)['image']['maxCount'], limits['maxCount'])
        self.calls.clear()
        with self.assertRaises(RequestFailure):
            self.gateway('qwen-image').generate({'kind': 'image', 'prompt': 'cat', 'size': '8192x128'})
        with self.assertRaises(RequestFailure):
            self.gateway('volcengine-image', 'doubao-seedream-4-5-251128').generate({'kind': 'image', 'prompt': 'cat', 'format': 'png'})
        self.assertFalse(self.calls)

    def test_ark_base64_and_unsupported_options_fail_before_a_paid_request(self):
        gateway = self.gateway('volcengine-image'); self.mode = 'b64'
        self.assertEqual(base64.b64decode(gateway.generate({'kind': 'image', 'prompt': 'cat'})['items'][0]['data']), PNG)
        self.calls.clear()
        for options in [{'count': 2}, {'size': '256x256'}, {'quality': 'high'}, {'format': 'webp'}]:
            with self.assertRaises(RequestFailure): gateway.generate({'kind': 'image', 'prompt': 'cat', **options})
        self.assertFalse(self.calls)
        gateway = self.gateway('qwen-image')
        for options in [{'count': 7}, {'format': 'jpeg'}, {'size': '2K'}]:
            with self.assertRaises(RequestFailure): gateway.generate({'kind': 'image', 'prompt': 'cat', **options})
        self.assertFalse(self.calls)

    def test_native_errors_are_sanitized_and_malformed_results_are_rejected(self):
        gateway = self.gateway('qwen-image'); self.mode = 'error'
        with self.assertRaises(RequestFailure) as error: gateway.generate({'kind': 'image', 'prompt': 'cat'})
        self.assertNotIn('fixture-image-secret', str(error.exception))
        self.assertIn('quota exhausted', str(error.exception))
        self.mode = 'malformed'
        with self.assertRaises(RequestFailure): gateway.generate({'kind': 'image', 'prompt': 'cat'})
        for report in (Path(self.temp.name)/'request-errors').glob('*.json'):
            self.assertNotIn('fixture-image-secret', report.read_text())
