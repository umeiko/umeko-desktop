"""Video settings migration and QML form behavior with local fake data only."""
import copy
import json
from pathlib import Path
import re
import tempfile
import unittest

from PySide6.QtCore import QCoreApplication
from PySide6.QtQml import QJSEngine

from app.multimodal_settings import DEFAULTS, normalize, validate
from app.storage import Store

APP = QCoreApplication.instance() or QCoreApplication([])
ROOT = Path(__file__).resolve().parents[1]
QML = ROOT / 'app' / 'qml'
VIDEO_DEFAULTS = {'providerId': '', 'model': '', 'seconds': '', 'size': ''}


class VideoSettingsTests(unittest.TestCase):
    def test_defaults_are_optional_and_normalized_copies_are_independent(self):
        self.assertEqual(DEFAULTS['video'], VIDEO_DEFAULTS)
        first, second = normalize(None), normalize({})
        first['video']['model'] = 'changed'
        self.assertEqual(second['video'], VIDEO_DEFAULTS)
        self.assertEqual(DEFAULTS['video'], VIDEO_DEFAULTS)

    def test_old_profile_adds_video_without_changing_image_or_speech(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            legacy = {'image': {**DEFAULTS['image'], 'model': 'image-existing', 'count': 2},
                      'speech': {**DEFAULTS['speech'], 'model': 'speech-existing', 'voice': 'voice-existing'}}
            store.data['multimodal'] = copy.deepcopy(legacy)
            store.save()
            loaded = Store(Path(directory)).data['multimodal']
            self.assertEqual(loaded, {**legacy, 'video': VIDEO_DEFAULTS})

    def test_optional_video_values_remain_strings(self):
        for seconds, size in [('', ''), ('8', '1280x720'), (' 12 ', ' 720x1280 ')]:
            with self.subTest(seconds=seconds, size=size):
                result = validate({'video': {'seconds': seconds, 'size': size}})['video']
                self.assertEqual(result, {'seconds': seconds.strip(), 'size': size.strip()})
                self.assertIsInstance(result['seconds'], str)
                self.assertIsInstance(result['size'], str)

    def test_invalid_durations_are_rejected(self):
        for value in [0, 8, True, None, 1.5, '0', '00', '-1', '1.5', '+3', '1e2', '８', '2\n']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate({'video': {'seconds': value}})

    def test_invalid_resolutions_and_unknown_fields_are_rejected(self):
        for value in [None, 720, '0x720', '720x0', '1280X720', '1280*720', '1280 x 720', '720p', '-1x720']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate({'video': {'size': value}})
        for field in ['key', 'baseUrl', 'format', 'quality', 'voice']:
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate({'video': {field: 'unsupported'}})

    def test_invalid_saved_field_falls_back_without_erasing_valid_selection(self):
        value = {'video': {'providerId': 'account-video', 'model': 'custom-video',
                           'seconds': 'bad', 'size': '1920x1080', 'key': 'discard'}}
        self.assertEqual(normalize(value)['video'],
                         {'providerId': 'account-video', 'model': 'custom-video',
                          'seconds': '', 'size': '1920x1080'})

    def test_saved_video_roundtrip_references_existing_account(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            providers = [{'id': 'existing-account', 'name': 'Existing account', 'api': 'openai',
                          'baseUrl': 'https://fixture.invalid/v1', 'key': '',
                          'models': [{'upstream': 'custom-video', 'alias': 'video'}]}]
            store.data['providers'] = copy.deepcopy(providers)
            selection = {'providerId': 'existing-account', 'model': 'custom-video',
                         'seconds': '5', 'size': '1280x720'}
            store.data['multimodal'].update(validate({'video': selection}))
            store.save()
            loaded = Store(Path(directory)).data
            self.assertEqual(loaded['multimodal']['video'], selection)
            self.assertEqual(loaded['providers'], providers)
            self.assertEqual(set(loaded['multimodal']['video']), set(VIDEO_DEFAULTS))

    def evaluate(self, script):
        engine = QJSEngine()
        result = engine.evaluate(script)
        self.assertFalse(result.isError(), result.toString())
        return result.toVariant()

    def test_real_card_load_and_values_keep_video_options_as_strings(self):
        source = (QML / 'GenerationSettingsCard.qml').read_text(encoding='utf-8')
        methods = '\n'.join(re.findall(r'    function (?:load|values)\(\) \{[\s\S]*?\n    }', source))
        self.assertEqual(methods.count('function '), 2)
        for kind, settings in [('video', {**VIDEO_DEFAULTS, 'providerId': 'existing-account',
                                         'model': 'manual-video', 'seconds': '8', 'size': '1280x720'}),
                               ('video', VIDEO_DEFAULTS), ('image', DEFAULTS['image']),
                               ('speech', DEFAULTS['speech'])]:
            with self.subTest(kind=kind, settings=settings):
                fixture = f"""
                    var kind = {json.dumps(kind)}, providerId = '', modelId = '', formatValue = '';
                    var backend = {{config: {{multimodal: {{{kind}: {json.dumps(settings)}}}}}}};
                    var size = {{}}, quality = {{}}, count = {{}}, voice = {{}}, speed = {{}};
                    var videoSize = {{}}, seconds = {{}};
                    var Qt = {{callLater: function() {{}}}}, syncPickers = function() {{}};
                """
                self.assertEqual(self.evaluate(fixture + methods + '\nload(); values();'), settings)

    def test_card_reuses_openai_and_video_capable_accounts_and_models(self):
        source = (QML / 'GenerationSettingsCard.qml').read_text(encoding='utf-8')
        expression = re.search(r'property var accounts: (.*)', source).group(1)
        fixture = """
            var root = {kind: 'video'};
            var backend = {config: {providers: [
                {id: 'openai-account', api: 'openai'},
                {id: 'video-plugin', api: 'plugin', generationCapabilities: ['video']},
                {id: 'speech-plugin', api: 'plugin', generationCapabilities: ['speech']},
                {id: 'chat-account', api: 'anthropic'}
            ]}};
        """
        self.assertEqual(self.evaluate(fixture + '(' + expression + ').map(p => p.id)'),
                         ['openai-account', 'video-plugin'])
        self.assertIn('account ? account.models : []', source)
        self.assertIn('onTextEdited: root.modelId = text', source)

    def test_settings_form_saves_and_reloads_the_real_video_card(self):
        source = (QML / 'MultimodalSettings.qml').read_text(encoding='utf-8')
        self.assertIn('objectName: "videoGenerationSettings"', source)
        self.assertIn('kind: "video"', source)
        self.assertIn('video: video.values()', source)
        self.assertIn('video.load()', source)
        self.assertNotIn('videoGenerationNotice', source)
        self.assertIn('objectName: "imageUnderstandingNotice"', source)
        self.assertIn('独立的识图模型设置预留于此，方案仍在 #49 讨论。', source)

    def test_video_labels_and_provider_disclosure_have_english_translations(self):
        source = (QML / 'english.js').read_text(encoding='utf-8').replace('.pragma library', '')
        translations = self.evaluate(source + '\nstrings;')
        expected = {'时长（秒）': 'Duration (seconds)', '分辨率（宽x高）': 'Resolution (WIDTHxHEIGHT)',
                    '供应商默认，例如 1280x720': 'Provider default, e.g. 1280x720', '生成中': 'Generating',
                    '视频提示词会发送给所选供应商，生成前逐次确认。':
                    'Video prompts are sent to the selected provider, with confirmation before each call.'}
        for chinese, english in expected.items():
            self.assertEqual(translations[chinese], english)


if __name__ == '__main__':
    unittest.main()
