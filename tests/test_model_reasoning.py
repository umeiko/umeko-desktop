import unittest
from types import SimpleNamespace

from app.model_capabilities import normalize_model
from app.model_reasoning import reasoning_levels, reconcile_effort


class ModelReasoningTests(unittest.TestCase):
    def test_legacy_defaults_custom_and_off_only(self):
        self.assertEqual(reasoning_levels(normalize_model({})), [])
        custom = normalize_model({'reasoningLevels': [' medium ', 'xhigh', 'vendor-custom']})
        self.assertEqual(custom['reasoningLevels'], ['medium', 'xhigh', 'vendor-custom'])
        self.assertEqual(reasoning_levels(normalize_model({'alias': 'renamed'}, custom)), custom['reasoningLevels'])
        self.assertEqual(reasoning_levels(normalize_model({'reasoningLevels': []}, custom)), [])

    def test_invalid_values_are_rejected(self):
        for levels in (None, 'low', [False], [''], ['off'], ['OFF'], ['low', 'LOW'], ['two words'], ['a\nname'], ['a' * 65], ['a'] * 33):
            with self.subTest(levels=levels), self.assertRaises(ValueError):
                normalize_model({'reasoningLevels': levels})

    def test_switching_and_reopening_only_uses_supported_levels(self):
        for value, levels, expected in (
            ('off', ['medium'], 'off'), ('high', ['low', 'medium'], 'medium'),
            ('xhigh', ['high', 'max'], 'high'), ('vendor-custom', ['vendor-custom'], 'vendor-custom'),
            ('vendor-custom', ['medium'], 'off'), ('max', [], 'off')):
            self.assertEqual(reconcile_effort(value, levels), expected)

    def test_plugin_discovery_preserves_manual_levels(self):
        from app.provider_plugins import ProviderPlugins
        record = {'id': 'fixture', 'models': [{'upstream': 'model', 'alias': 'model', 'reasoningLevels': ['medium', 'xhigh']}]}
        host = SimpleNamespace(c=SimpleNamespace(store=SimpleNamespace(data={'providers': [record]})))
        models = ProviderPlugins._models(host, record, [{'id': 'model'}])
        self.assertEqual(models[0]['reasoningLevels'], ['medium', 'xhigh'])


class EditorDraftAutomaticTests(unittest.TestCase):
    """Saving the provider or mapping editor must not freeze stale automatic values."""
    def setUp(self):
        self.known = {'upstream': 'test-model', 'reasoningLevels': ['low', 'high'], 'reasoningLevelsAuto': True,
                      'reasoningFormat': 'qwen', 'reasoningFormatAuto': True,
                      'reasoningDetection': {'state': 'known', 'levels': ['low', 'high']},
                      'reasoningFormatDetection': {'state': 'known', 'format': 'qwen'}}

    def test_automatic_rows_keep_detected_values_over_draft_values(self):
        draft = {'upstream': 'test-model', 'reasoningLevels': ['low', 'high', 'max'], 'reasoningLevelsAuto': True,
                 'reasoningFormat': 'openai', 'reasoningFormatAuto': True}
        saved = normalize_model(draft, normalize_model(self.known))
        self.assertEqual((saved['reasoningLevels'], saved['reasoningFormat']), (['low', 'high'], 'qwen'))
        undetected = normalize_model({'upstream': 'test-model'})
        saved = normalize_model({**draft, 'reasoningLevels': ['low', 'high', 'max']}, undetected)
        self.assertNotIn('reasoningLevels', saved)
        self.assertEqual(reasoning_levels(saved), [])

    def test_switching_manual_to_automatic_restores_cache_or_queues_detection(self):
        manual = normalize_model({**self.known, 'reasoningLevels': ['custom'], 'reasoningLevelsAuto': False,
                                  'reasoningFormat': 'deepseek', 'reasoningFormatAuto': False})
        draft = {'upstream': 'test-model', 'reasoningLevels': ['custom'], 'reasoningLevelsAuto': True,
                 'reasoningFormat': 'deepseek', 'reasoningFormatAuto': True}
        saved = normalize_model(draft, manual)
        self.assertEqual((saved['reasoningLevels'], saved['reasoningFormat']), (['low', 'high'], 'qwen'))
        unknown = normalize_model({'upstream': 'test-model', 'reasoningLevels': ['custom'], 'reasoningLevelsAuto': False,
                                   'reasoningFormat': 'deepseek', 'reasoningFormatAuto': False})
        saved = normalize_model(draft, unknown)
        self.assertNotIn('reasoningLevels', saved)
        self.assertEqual((saved['reasoningDetection']['state'], saved['reasoningFormatDetection']['state']), ('unknown', 'unknown'))

    def test_manual_draft_values_are_saved_exactly(self):
        draft = {'upstream': 'test-model', 'reasoningLevels': ['b', 'a'], 'reasoningLevelsAuto': False,
                 'reasoningFormat': 'chat-template', 'reasoningFormatAuto': False}
        saved = normalize_model(draft, normalize_model(self.known))
        self.assertEqual((saved['reasoningLevels'], saved['reasoningFormat']), (['b', 'a'], 'chat-template'))
