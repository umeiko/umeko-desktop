"""Offline SDK capability fixtures: old hosts load an inert upgrade notice."""
from __future__ import annotations

import importlib
import sys
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import umeko_provider_sdk as current_sdk


SCRIPTS = Path(__file__).resolve().parents[1] / "provider_dev/plugins/codearts/scripts"


class LegacyProvider:
    """Bounded v0.6.0 Provider surface (SDK_VERSION was already 0.2.1)."""
    def __init__(self, context):
        self.context = context

    def authenticate(self, credentials):
        raise NotImplementedError

    def list_models(self, refresh=False):
        raise NotImplementedError

    def events(self, model, messages, tools, max_tokens, parameters):
        raise NotImplementedError

    def close(self):
        self.context.cancelled.set()


class LegacyHttpSession:
    def __init__(self, allowed_urls, *, environment_proxy=True):
        raise AssertionError("Compatibility detection must not construct HTTP sessions")


def context(**extra):
    # No filesystem, profiles, secrets, CLI or network are used by these tests.
    return types.SimpleNamespace(config={}, state_dir=None, secrets=None,
                                 cancelled=threading.Event(), **extra)


def modern_context():
    value = context(profile_dir=None, downloads_dir=None, language="en", notify=None)
    value.request_cancelled = value.cancelled
    return value


class CodeartsCompatibilityTests(unittest.TestCase):
    def load_plugin(self, *, provider=current_sdk.Provider, http=current_sdk.HttpSession):
        name = "_codearts_compat_fixture"
        package = types.ModuleType(name)
        package.__path__ = [str(SCRIPTS)]
        sdk = types.ModuleType("umeko_provider_sdk")
        sdk.Provider, sdk.ProviderError, sdk.HttpSession = provider, current_sdk.ProviderError, http
        # The old and current SDK expose this same value. Detection must ignore it.
        sdk.SDK_VERSION = "0.2.1"
        account = types.ModuleType(name + ".account")
        account.CodeartsAccount = Mock(name="account_factory")
        transport = types.ModuleType(name + ".transport")
        transport.CodeartsTransport = Mock(name="transport_factory")
        with patch.dict(sys.modules, {name: package, "umeko_provider_sdk": sdk,
                                     account.__name__: account, transport.__name__: transport}):
            plugin = importlib.import_module(name + ".provider")
        return plugin, account.CodeartsAccount, transport.CodeartsTransport

    def assert_inert(self, plugin, account, transport, value):
        instance = plugin.create_provider(value)
        self.assertIsInstance(instance, plugin.UpgradeRequiredProvider)
        label = instance.authenticate({})["label"]
        self.assertIn("#10", label)
        self.assertIn("facef966", label)
        self.assertIn("v0.6.0", label)
        self.assertNotIn("0.6.1", label)
        self.assertEqual(instance.list_models(refresh=True), [])
        self.assertEqual(instance.card_status(), "")
        self.assertEqual(instance.card_fields(), [])
        self.assertEqual(instance.card_actions(), [])
        for invoke in (lambda: instance.events("unused", [], [], 1, {}),
                       lambda: instance.card_action("open_console"),
                       lambda: instance.set_card_secret("credentials", "unused")):
            with self.assertRaises(current_sdk.ProviderError) as error:
                invoke()
            self.assertEqual(str(error.exception), label)
        account.assert_not_called()
        transport.assert_not_called()
        instance.close()
        self.assertTrue(value.cancelled.is_set())
        return label

    def test_released_v060_surface_loads_with_chinese_upgrade_label(self):
        plugin, account, transport = self.load_plugin(provider=LegacyProvider, http=LegacyHttpSession)
        label = self.assert_inert(plugin, account, transport, context())
        self.assertIn("请升级", label)

    def test_missing_card_hook_alone_blocks_before_account_initialization(self):
        for hook in ("card_actions", "card_action", "card_status", "card_fields", "set_card_secret"):
            with self.subTest(hook=hook):
                partial = type("PartialProvider", (current_sdk.Provider,), {hook: None})
                plugin, account, transport = self.load_plugin(provider=partial)
                self.assert_inert(plugin, account, transport, modern_context())

    def test_missing_http_scope_blocks_with_english_upgrade_label(self):
        plugin, account, transport = self.load_plugin(http=LegacyHttpSession)
        label = self.assert_inert(plugin, account, transport, modern_context())
        self.assertIn("Upgrade Umeko", label)

    def test_missing_context_capabilities_block(self):
        for field in ("profile_dir", "downloads_dir", "language", "notify", "request_cancelled"):
            with self.subTest(field=field):
                value = modern_context()
                delattr(value, field)
                self.assert_inert(*self.load_plugin(), value)

    def test_current_sdk_keeps_normal_factory_and_transport(self):
        plugin, account, transport = self.load_plugin()
        value = modern_context()
        instance = plugin.create_provider(value)
        self.assertIsInstance(instance, plugin.CodeartsProvider)
        account.assert_called_once_with(value, progress=instance._progress)
        transport.assert_called_once_with(value, account.return_value)
        self.assertEqual(instance.card_status(), "")
        self.assertEqual([action["key"] for action in instance.card_actions()], ["open_console"])
        transport.return_value.events.return_value = iter([{"offline": True}])
        self.assertEqual(list(instance.events("fixture", [], [], 1, {})), [{"offline": True}])
        instance.close()


if __name__ == "__main__":
    unittest.main()
