import unittest

from app.model_context import context_suggestion, normalize_context, parse_context_window


class ModelContextTests(unittest.TestCase):
    def test_specific_name_capacity_precedes_family_default(self):
        cases = {
            "k3": 1048576, "Kimi K3": 1048576, "moonshot/kimi-k3": 1048576,
            "k3-256": 262144, "kimi-k3-256k": 262144,
            "k3-256-preview": 262144, "k3-128K": 131072,
            "kimi-k2.5": 262144, "kimi-for-coding-highspeed": 262144,
            "kimi-for-coding": 1048576, "deepseek-v4-flash": 1048576,
            "deepseek-v4.1-pro": 1048576, "gpt-4.1-2025-04-14": 1047576,
            "gpt-4o-mini": 128000, "claude-sonnet-4-6": 1000000,
            "claude-haiku-4-5-20251001": 200000, "gemini-2.5-pro": 1048576,
            "unlisted-1m": 1048576,
        }
        for name, tokens in cases.items():
            with self.subTest(name=name):
                self.assertEqual(context_suggestion(name), {"tokens": tokens, "matched": True})
        for name in ("k30", "k3-2560", "gpt-4.11", "unknown-8b", "default", "", "model-128kb"):
            with self.subTest(name=name):
                self.assertEqual(context_suggestion(name), {"tokens": 128000, "matched": False})

    def test_units_and_validation_do_not_silently_truncate(self):
        for raw, expected in (("256K", 262144), ("1m", 1048576), ("0.5M", 524288),
                              (" 200000 ", 200000), (1048576, 1048576), (2048.0, 2048)):
            self.assertEqual(parse_context_window(raw), expected)
        for invalid in (None, True, False, "", "0", "1023", "16.1M", "1e6", "NaN", "1.1K", "2048 tokens", [], -1):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                parse_context_window(invalid)

    def test_manual_overrides_survive_legacy_edit_and_auto_recalculates(self):
        original = {"upstream": "k3", "alias": "k3-256"}
        self.assertEqual(normalize_context(original), {"contextWindow": 1048576, "contextWindowAuto": True})
        manual = {**original, "contextWindow": 200000}
        self.assertEqual(normalize_context(manual), {"contextWindow": 200000, "contextWindowAuto": False})
        self.assertEqual(normalize_context({"upstream": "k3-256", "alias": "new"}, manual),
                         {"contextWindow": 200000, "contextWindowAuto": False})
        self.assertEqual(normalize_context({"upstream": "k3-256", "contextWindowAuto": True, "contextWindow": "stale"}, manual),
                         {"contextWindow": 262144, "contextWindowAuto": True})
        with self.assertRaises(ValueError):
            normalize_context({"upstream": "k3", "contextWindowAuto": False, "contextWindow": ""})
        with self.assertRaises(ValueError):
            normalize_context({"upstream": "k3", "contextWindowAuto": "false"})
