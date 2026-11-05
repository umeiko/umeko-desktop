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
