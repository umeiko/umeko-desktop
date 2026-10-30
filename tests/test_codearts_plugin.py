"""Source-wrapper integration using private fake credentials and no network."""
from __future__ import annotations

import copy
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

from umeko_provider_sdk import ProviderContext, ProviderError


PACKAGE = "_codearts_wrapper_source_tests"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(Path(__file__).resolve().parents[1] / "provider_dev/bundled/codearts/scripts")]
sys.modules[PACKAGE] = package
plugin = importlib.import_module(PACKAGE + ".provider")
Account = importlib.import_module(PACKAGE + ".account").CodeartsAccount

AK, SK = "FAKE_WRAPPER_AK", "FAKE_WRAPPER_SK"
CSV = f"Access Key Id,Secret Access Key\n{AK},{SK}\n"
MODEL = "huaweicloud/fake-wrapper-model"
CONSOLE_URL = "https://console.huaweicloud.com/console/?locale=zh-cn"


class MemorySecrets:
    def __init__(self):
        self.values = {}

    def get(self, name, default=None):
        return copy.deepcopy(self.values.get(name, default))

    def set(self, name, value):
        self.values[name] = copy.deepcopy(value)

    def delete(self, name):
        self.values.pop(name, None)


class FakeTransport:
    def __init__(self, context, account):
        self.context, self.account = context, account
        self.close = Mock()


class PluginWrapperTests(unittest.TestCase):
    def setUp(self):
        base = Path("C:/UmekoTests") if os.name == "nt" else Path(tempfile.gettempdir()) / "UmekoTests"
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="codearts-wrapper-", dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.downloads = self.root / "Downloads"
        self.downloads.mkdir()
        self.notifications = []
        self.ready = threading.Event()
        self.secrets = MemorySecrets()
        self.calls = []
        self.context = ProviderContext(config={}, state_dir=self.root / "state", secrets=self.secrets,
                                       downloads_dir=self.downloads, language="en", notify=self._notify)

        def runner(command, *, env, cwd, timeout):
            self.assertEqual(command[-1], "models")
            self.assertEqual((env["CODEARTS_CLI_AK"], env["CODEARTS_CLI_SK"]), (AK, SK))
            self.assertTrue(Path(cwd).is_relative_to(self.context.state_dir))
            self.assertEqual(Path(cwd).name, "work")
            self.calls.append(command)
            return subprocess.CompletedProcess(command, 0, (MODEL + "\n").encode(), b"")

        def account_factory(context, **kwargs):
            # The real account/parser runs; only CLI discovery, the subprocess
            # and legacy access are fakes. No real Windows vault can be read.
            legacy = Mock()
            legacy.get_password.side_effect = AssertionError("No legacy access expected")
            account = Account(context, legacy_store=legacy, runner=runner, **kwargs)
            account._find_cli = lambda: self.root / "fake-codearts.cmd"
            account.close = Mock(wraps=account.close)
            return account

        with patch.object(plugin, "CodeartsAccount", side_effect=account_factory), \
                patch.object(plugin, "CodeartsTransport", FakeTransport):
            self.provider = plugin.create_provider(self.context)
        self.addCleanup(self.provider.close)

    def _notify(self, value):
        self.notifications.append(copy.deepcopy(value))
        if value.get("refreshModels"):
            self.ready.set()

    def assert_public(self, *values):
        encoded = json.dumps([*values, self.notifications], ensure_ascii=False)
        self.assertNotIn(AK, encoded)
        self.assertNotIn(SK, encoded)

    def test_console_action_watches_new_csv_not_preexisting_or_unrelated(self):
        old = self.downloads / "preexisting.csv"
        old.write_text(CSV, encoding="utf-8")
        with patch("webbrowser.open") as browser:
            result = self.provider.card_action("open_console")
            self.assertEqual(result["url"], CONSOLE_URL)
            browser.assert_not_called()
        unrelated = self.downloads / "new-unrelated.csv"
        unrelated.write_text("name,count\nbook,2\n", encoding="utf-8")
        fresh = self.downloads / "browser-renamed-access-key.CSV"
        fresh.write_text(CSV, encoding="utf-8")
        self.assertTrue(self.ready.wait(3), "Wrapper did not publish the successful CSV import")
        self.provider._stop_watch()
        self.assertEqual(self.secrets.get("account"), {"ak": AK, "sk": SK})
        self.assertFalse(fresh.exists())
        self.assertTrue(old.exists())
        self.assertTrue(unrelated.exists())
        self.assertTrue(self.notifications[-1]["refreshModels"])
        self.assertEqual(self.provider.list_models(refresh=True), [{"id": MODEL}])
        self.assertEqual(len(self.calls), 1)
        self.assert_public(result, self.provider.card_status(), self.provider.card_fields())

    def test_private_paste_stops_watch_and_returns_only_public_fields(self):
        self.provider.card_action("open_console")
        watcher = self.provider._watcher
        result = self.provider.set_card_secret("credentials", f"{AK}\n{SK}")
        self.assertEqual(set(result), {"message"})
        self.assertIsNone(self.provider._watcher)
        self.assertFalse(watcher.is_alive())
        self.assertTrue(self.provider._watch_stop.is_set())
        fields = self.provider.card_fields()
        self.assertTrue(fields[0]["hasValue"])
        self.assertNotIn("value", fields[0])
        self.assertEqual(self.provider.list_models(refresh=True), [{"id": MODEL}])
        self.assertEqual(len(self.calls), 1)
        self.assert_public(result, fields, self.provider.card_status())

    def test_authenticate_then_list_models_reuses_verified_catalog(self):
        self.secrets.set("account", {"ak": AK, "sk": SK})
        authenticated = self.provider.authenticate({})
        self.assertEqual(authenticated, {"label": "CodeArts connected."})
        self.assertEqual(self.provider.list_models(refresh=True), [{"id": MODEL}])
        self.assertEqual(self.provider.list_models(), [{"id": MODEL}])
        self.assertEqual(len(self.calls), 1)
        self.assert_public(authenticated, self.provider.card_actions())

    def test_authenticate_rejects_verification_failure_but_allows_missing_credentials_guide(self):
        message = self.provider._text("verify_failed")
        failed = {"ready": False, "models": [], "message": message}
        with patch.object(self.provider.account, "begin", return_value=failed):
            with self.assertRaises(ProviderError) as error:
                self.provider.authenticate({})
        self.assertEqual(str(error.exception), message)
        guide = {"ready": False, "models": [], "message": self.provider._text("guide")}
        with patch.object(self.provider.account, "begin", return_value=guide):
            result = self.provider.authenticate({})
        self.assertEqual(result, {"label": "CodeArts is not connected."})
        self.assertEqual(self.provider.list_models(refresh=True), [])
        self.assertFalse(self.provider.card_fields()[0]["hasValue"])
        self.assertFalse(self.calls)
        self.assert_public(str(error.exception), result, self.provider.card_status())

    def test_close_cancels_watch_and_closes_account_and_transport(self):
        self.provider.card_action("open_console")
        watcher = self.provider._watcher
        self.provider.close()
        self.assertTrue(self.context.cancelled.is_set())
        self.assertTrue(self.provider.account._cancelled.is_set())
        self.assertIsNone(self.provider._watcher)
        self.assertFalse(watcher.is_alive())
        self.provider.account.close.assert_called_once_with()
        self.provider.transport.close.assert_called_once_with()
        self.assertFalse(self.calls)
        self.assert_public(self.provider.card_status())

    def test_unconnected_card_has_only_console_action_and_no_duplicate_status(self):
        with patch.object(self.provider.account, "begin", return_value={
                "ready": False, "models": [], "message": self.provider._text("guide")}):
            self.assertEqual(self.provider.authenticate({})["label"], self.provider._text("status_unconnected"))
        self.assertEqual([a["key"] for a in self.provider.card_actions()], ["open_console"])
        self.assertEqual(self.provider.card_status(), "")
        self.assertEqual(self.provider.card_fields()[0]["hint"], self.provider._text("guide"))

    def test_waiting_card_shows_cancel_only_until_watcher_stops(self):
        self.provider.card_action("open_console")
        self.assertEqual([a["key"] for a in self.provider.card_actions()], ["open_console", "cancel_import"])
        self.assertEqual(self.provider.card_status(), "")
        self.provider.card_action("cancel_import")
        self.assertEqual([a["key"] for a in self.provider.card_actions()], ["open_console"])

    def test_connected_card_hides_cancel_before_success_notification(self):
        observed = []
        def notify(event):
            if event.get("refreshModels"):
                observed.append([a["key"] for a in self.provider.card_actions()])
            self._notify(event)
        self.context.notify = notify
        self.provider.card_action("open_console")
        (self.downloads / "new-key.csv").write_text(CSV, encoding="utf-8")
        self.assertTrue(self.ready.wait(3))
        self.assertEqual(observed, [["open_console"]])
        self.assertTrue(self.provider._connected)
        self.assertEqual([a["key"] for a in self.provider.card_actions()], ["open_console"])
        self.assertEqual(self.provider.card_status(), "")


if __name__ == "__main__":
    unittest.main()
