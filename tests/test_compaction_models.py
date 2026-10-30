import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.gateway import Gateway
from app.model_capabilities import normalize_model
from app.model_context import normalize_context, provider_context_window
from app.provider_plugins import ProviderPlugins


class ProviderContextModelTests(unittest.TestCase):
    def test_provider_capacities_are_independent_of_editable_window_bounds(self):
        for raw, expected in ((512, 512), ("512", 512), (512.0, 512),
                              (33554432, 33554432), ("33554432", 33554432),
                              (9007199254740990, 9007199254740990)):
            with self.subTest(raw=raw):
                self.assertEqual(provider_context_window({"context_length": raw}), expected)
                automatic = normalize_context({"upstream": "k3", "providerContextWindow": raw})
                self.assertEqual(automatic["contextWindow"], expected)
                self.assertEqual(automatic["providerContextWindow"], expected)
        for invalid in (True, 0, -1, "0", 512.5, "512.5", "1K", 9007199254740991,
                        float("inf"), float("nan"), None, []):
            with self.subTest(invalid=invalid):
                self.assertIsNone(provider_context_window({"context_length": invalid}))
                if invalid is not None:
                    with self.assertRaises(ValueError):
                        normalize_context({"upstream": "k3", "providerContextWindow": invalid})

    def test_provider_context_shapes_and_input_limit_precedence(self):
        for key in ("max_model_len", "context_length", "context_window", "max_context_length", "max_input_tokens", "inputTokenLimit", "contextWindow"):
            with self.subTest(key=key):
                self.assertEqual(provider_context_window({key: 32768}), 32768)
        for row, expected in (({"top_provider": {"context_length": 65536}}, 65536),
                              ({"limits": {"max_input_tokens": "32768"}}, 32768),
                              ({"metadata": {"limits": {"context_window": 16384}}}, 16384),
                              ({"model_info": {"max_input_tokens": 48000}}, 48000),
                              ({"parameters": {"max_input_tokens": 64000}}, 64000)):
            with self.subTest(row=row):
                self.assertEqual(provider_context_window(row), expected)
        self.assertEqual(provider_context_window({"context_length": 65536, "top_provider": {"context_length": 32768}}), 32768)
        self.assertIsNone(provider_context_window({"context_length": True, "max_output_tokens": 32768, "max_model_len": "bad"}))

    def test_provider_auto_manual_and_server_owned_metadata(self):
        old = {"upstream": "k3", "providerContextWindow": 32768, "contextWindowAuto": True}
        automatic = normalize_model(old)
        self.assertEqual(automatic["contextWindow"], 32768)
        manual = normalize_model({**old, "contextWindowAuto": False, "contextWindow": 65536})
        self.assertEqual(manual["contextWindow"], 65536)
        for incoming in ({"upstream": "k3"}, {"upstream": "k3", "providerContextWindow": 999999},
                         {"upstream": "k3", "providerContextWindow": None}):
            with self.subTest(incoming=incoming):
                edited = normalize_model(incoming, automatic)
                self.assertEqual(edited["providerContextWindow"], 32768)
                self.assertEqual(edited["contextWindow"], 32768)
        self.assertNotIn("providerContextWindow", normalize_model({"upstream": "k3", "providerContextWindow": 999999}, {}))
        changed_model = normalize_model({"upstream": "unlisted", "providerContextWindow": 999999}, old)
        self.assertNotIn("providerContextWindow", changed_model)
        self.assertEqual(changed_model["contextWindow"], 128000)
        self.assertEqual(normalize_context({"upstream": "unknown"}), {"contextWindow": 128000, "contextWindowAuto": True})

    def test_plugin_refresh_preserves_alias_and_user_override(self):
        old = {"upstream": "fixture", "alias": "mine", "contextWindow": 65536, "contextWindowAuto": False,
               "contextWindowSource": "custom", "providerContextWindow": 32768,
               "vision": False, "visionAuto": False, "visionSource": "custom"}
        record = {"id": "provider", "models": [old]}
        manager = SimpleNamespace(c=SimpleNamespace(store=SimpleNamespace(data={"providers": [record]})))
        refreshed = ProviderPlugins._models(manager, record, [{"id": "fixture", "limits": {"max_input_tokens": 48000}}])[0]
        self.assertEqual((refreshed["alias"], refreshed["contextWindow"], refreshed["providerContextWindow"]),
                         ("mine", 65536, 48000))
        edited = ProviderPlugins.modelSettings({"upstream": "fixture", "providerContextWindow": 999999}, refreshed)
        self.assertEqual(edited["providerContextWindow"], 48000)
        record["models"] = []
        auto = ProviderPlugins._models(manager, record, [{"id": "fixture", "top_provider": {"context_length": 16384}}])[0]
        self.assertEqual(auto["contextWindow"], 16384)

    def test_gateway_delivers_provider_context_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SimpleNamespace(directory=Path(directory), data={"providers": [{"api": "openai", "name": "fixture", "models": [
                {"upstream": "fixture", "alias": "alias", "providerContextWindow": 32768}
            ]}]})
            row = Gateway(store, SimpleNamespace()).models()[0]
            self.assertEqual((row["contextWindow"], row["providerContextWindow"]), (32768, 32768))
