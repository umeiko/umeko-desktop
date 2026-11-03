"""Generation preferences migrate without credentials or extra provider models."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication
from app.controller import Controller
from app.multimodal_settings import DEFAULTS, normalize, validate
from app.storage import Store
from app.generation import generation_config

APP = QCoreApplication.instance() or QCoreApplication([])
ROOT = Path(__file__).resolve().parents[1]


class MultimodalSettingsTests(unittest.TestCase):
    def test_old_profiles_load_defaults_and_partial_settings_merge(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            old = Store(path)
            old.data.pop('multimodal')
            old.save()
            loaded = Store(path)
            self.assertEqual(loaded.data['multimodal'], DEFAULTS)
            loaded.data['multimodal'] = {'image': {'providerId': 'account', 'model': 'manual-image'}}
            loaded.save()
            self.assertEqual(Store(path).data['multimodal']['image'],
                             {**DEFAULTS['image'], 'providerId': 'account', 'model': 'manual-image'})
            self.assertEqual(Store(path).data['multimodal']['speech'], DEFAULTS['speech'])

    def test_invalid_saved_values_use_defaults_but_invalid_edits_are_rejected(self):
        self.assertEqual(normalize(None), DEFAULTS)
        self.assertEqual(normalize({'image': {'count': True, 'format': 'exe'}, 'speech': {'speed': float('nan')}}), DEFAULTS)
        for value in ([], {'image': {'key': 'never-store'}}, {'unknown': {}}, {'speech': {'speed': 9}},
                      {'image': {'count': 11}}, {'image': {'providerId': 'bad\nvalue'}}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate(value)

    def test_save_keeps_credentials_and_catalogue_and_survives_reload(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'UMEKO_DATA_DIR': directory}), \
                patch('app.provider_plugins.BundledProviders.sync', return_value=[]):
            controller = Controller(ROOT)
            try:
                self.assertTrue(controller.saveProvider('', 'Test provider', 'openai', 'https://provider.invalid/v1',
                                                        'fixture-key', 'test-image-model,test-voice-model'))
                provider = copy.deepcopy(controller.store.data['providers'][0])
                selection = {'video': DEFAULTS['video'].copy(),
                             'image': {**DEFAULTS['image'], 'providerId': provider['id'], 'model': 'manual-image'},
                             'speech': {**DEFAULTS['speech'], 'providerId': provider['id'],
                                        'model': 'test-voice-model', 'voice': 'test-voice'}}
                with patch.object(controller, '_restart_pi') as restart:
                    self.assertTrue(controller.saveMultimodalSettings(json.dumps(selection)))
                    restart.assert_called_once()
                self.assertEqual(controller.store.data['providers'][0], provider)
                self.assertEqual(Store(Path(directory)).data['multimodal'], selection)
                self.assertNotIn('fixture-key', controller.store.path.read_text(encoding='utf-8'))
                self.assertNotIn('key', controller.config['providers'][0])
                self.assertEqual(generation_config(controller.store.data)['image'],
                                 {'provider': 'Test provider', 'model': 'manual-image'})
                before = copy.deepcopy(selection)
                with patch.object(controller.store, 'save', side_effect=OSError('fixture save failure')):
                    self.assertFalse(controller.saveMultimodalSettings(json.dumps({'image': {'model': 'another-image'}})))
                self.assertEqual(controller.store.data['multimodal'], before)
                controller._view.phase = 'running'
                controller._view.provider = 'another-chat-account'
                self.assertTrue(controller._models_busy(provider['id']))
                self.assertFalse(controller.saveProvider(provider['id'], 'Changed during generation', 'openai',
                                                         provider['baseUrl'], '', json.dumps(provider['models'])))
                self.assertFalse(controller.saveMultimodalSettings(json.dumps({'image': {'model': 'while-running'}})))
                controller._view.phase = 'idle'
                self.assertTrue(controller.saveMultimodalSettings(json.dumps({'image': {'providerId': ''}})))
                self.assertIsNone(generation_config(controller.store.data)['image'])
                self.assertEqual(controller.store.data['multimodal']['image']['model'], '')
                controller.store.data['providers'] = []
                self.assertIsNone(generation_config(controller.store.data)['speech'])
            finally:
                controller._view.phase = 'idle'
                controller.close()

    def test_unready_or_unsupported_selection_cannot_be_enabled(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'UMEKO_DATA_DIR': directory}), \
                patch('app.provider_plugins.BundledProviders.sync', return_value=[]):
            controller = Controller(ROOT)
            try:
                self.assertFalse(controller.saveMultimodalSettings(json.dumps({'image': {'providerId': 'missing', 'model': 'image'}})))
                self.assertTrue(controller.saveProvider('', 'Test provider', 'openai', 'https://provider.invalid/v1', 'fixture-key', 'test-voice-model'))
                provider_id = controller.store.data['providers'][0]['id']
                self.assertFalse(controller.saveMultimodalSettings(json.dumps({'speech': {'providerId': provider_id, 'model': 'test-voice-model'}})))
                self.assertFalse(controller.saveMultimodalSettings(json.dumps({'image': {'providerId': provider_id}})))
            finally:
                controller.close()
