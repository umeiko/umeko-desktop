"""Offline card-extension checks with a synthetic host and in-memory secrets."""
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication, QObject, Signal

from app.provider_plugins import ProviderPlugins
from umeko_provider_sdk import Provider, ProviderContext, ProviderError, request_scope

SECRET = "fixture-private-credential"


class Secrets:
    def __init__(self): self.values = {"session": {"access_token": SECRET}}
    def _read(self): return self.values.copy()
    def get(self, key, default=None): return self.values.get(key, default)
    def set(self, key, value): self.values[key] = value
    def delete(self, key): self.values.pop(key, None)
    def clear(self): self.values.clear()


class Fixture(Provider):
    def __init__(self, context):
        super().__init__(context)
        self.calls, self.refreshes = [], []
        self.actions = [{"key": "start", "label": "Connect", "url": "https://example.test/start", "hint": "Open the public page"}]
        self.result = {"message": "Waiting for import", "url": "https://example.test/start", "ignored": SECRET}
        self.message = "Ready"
    def card_actions(self): return self.actions
    def card_status(self): return self.message
    def card_action(self, key):
        self.calls.append(key)
        return self.result
    def list_models(self, refresh=False):
        self.refreshes.append(refresh)
        return [{"id": "fixture-model"}]


class Host(QObject):
    changed = Signal()
    toast = Signal(str)
    def __init__(self, directory):
        super().__init__()
        self.root = directory
        self.language = "en"
        self.store = SimpleNamespace(directory=directory, data={"providers": [{
            "id": "fixture-account", "api": "plugin", "name": "Fixture", "pluginId": "fixture",
            "pluginVersion": "1.0.0", "models": [], "key": "", "baseUrl": "",
        }], "selectedProvider": "", "selectedModel": ""}, save=lambda: None)
    def _models_busy(self, _provider_id=None): return False
    def _restart_pi(self): pass


class ProviderCardActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        root = Path("C:/UmekoTests") if os.name == "nt" else Path(tempfile.gettempdir()) / "UmekoTests"
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="f6-cards-", dir=root)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.host = Host(self.path)
        self.manager = ProviderPlugins(self.host)
        self.addCleanup(self.manager.close)
        self.provider_id = "fixture-account"
        self.secrets = Secrets()
        self.manager._secrets = lambda _id: self.secrets
        self.manager._package = lambda _record: (self.path, ({
            "entrypoint": "fixture.py:create_provider", "auth": {"fields": []},
        }, {}, {"type": "object"}))
        self.manager._config_path = lambda _id: self.path / "config.json"
        self.notices = []
        self.host.toast.connect(self.notices.append)
        self.factory = Mock(return_value=SimpleNamespace(create_provider=Fixture))
        self.imports = patch("app.provider_plugins.importlib", SimpleNamespace(import_module=self.factory))
        self.imports.start()
        self.addCleanup(self.imports.stop)
        self.downloads = patch("app.provider_plugins.QStandardPaths.writableLocation", return_value=str(self.path / "Downloads"))
        self.downloads.start()
        self.addCleanup(self.downloads.stop)

    def activate(self): return self.manager._client(self.provider_id)

    def settle(self):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.app.processEvents()
            if not self.manager.busy:
                self.app.processEvents()
                if not self.manager.busy: return
            time.sleep(.005)
        self.fail("Synthetic provider operation timed out")

    def test_api_v1_defaults_and_context_fields_are_backward_compatible(self):
        context = ProviderContext({}, self.path, self.secrets)
        self.assertIsNone(context.profile_dir)
        self.assertIsNone(context.downloads_dir)
        self.assertIsNone(context.notify)
        self.assertEqual(context.language, "zh")
        provider = Provider(context)
        self.assertEqual(provider.card_actions(), [])
        self.assertEqual(provider.card_status(), "")
        with self.assertRaises(ProviderError): provider.card_action("unknown")
        self.assertEqual(self.manager.rows[0]["cardActions"], [])
        self.factory.assert_not_called()
        client = self.activate()
        self.assertEqual(client.context.profile_dir, self.path.resolve())
        self.assertEqual(client.context.downloads_dir, self.path / "Downloads")
        self.assertEqual(client.context.language, "en")
        self.assertTrue(callable(client.context.notify))

    def test_click_runs_action_and_host_opens_only_result_url(self):
        client = self.activate()
        with patch("app.provider_plugins.QDesktopServices.openUrl", return_value=True) as browser:
            row = self.manager.rows[0]
            self.assertEqual(row["cardStatus"], "Ready")
            self.assertEqual(row["cardActions"][0]["label"], "Connect")
            browser.assert_not_called()
            self.assertTrue(self.manager.cardAction(self.provider_id, "start"))
            self.settle()
            self.assertEqual(client.calls, ["start"])
            self.assertEqual(client.refreshes, [])
            browser.assert_called_once()
            self.assertEqual(browser.call_args.args[0].toString(), "https://example.test/start")
        self.assertIn("Waiting for import", self.manager.rows[0]["status"])
        self.assertNotIn(SECRET, json.dumps(self.manager.rows) + json.dumps(self.notices))

    def test_action_refresh_and_background_notification_update_models(self):
        client = self.activate()
        client.result = {"message": "Connected", "refreshModels": True}
        self.assertTrue(self.manager.cardAction(self.provider_id, "start"))
        self.settle()
        self.assertEqual(client.refreshes, [True])
        with patch("app.provider_plugins.QDesktopServices.openUrl") as browser:
            worker = threading.Thread(target=lambda: client.context.notify({
                "message": "Imported " + SECRET, "refreshModels": True, "url": "https://example.test/ignored", "token": SECRET,
            }))
            worker.start()
            worker.join()
            self.settle()
            browser.assert_not_called()
        self.assertEqual(client.refreshes, [True, True])
        self.assertEqual(self.manager.rows[0]["models"][0]["upstream"], "fixture-model")
        self.assertEqual(self.manager.rows[0]["status"], "Imported ***")
        self.assertNotIn(SECRET, json.dumps(self.manager.rows) + json.dumps(self.notices))

    def test_invalid_results_descriptors_and_unadvertised_actions_are_rejected(self):
        client = self.activate()
        self.assertFalse(self.manager.cardAction(self.provider_id, "unknown"))
        for invalid in (None, {"message": []}, {"refreshModels": "yes"}, {"url": "file:///tmp/example"},
                        {"url": "https://user:password@example.test"}, {"url": "https://example.test/" + SECRET}):
            with self.subTest(result=invalid), patch("app.provider_plugins.QDesktopServices.openUrl") as browser:
                client.result = invalid
                self.assertTrue(self.manager.cardAction(self.provider_id, "start"))
                self.settle()
                browser.assert_not_called()
                self.assertNotIn(SECRET, json.dumps(self.notices))
        for invalid in ({}, [{"key": "bad key", "label": "Invalid"}], [{"key": "start", "label": []}]):
            with self.subTest(actions=invalid):
                client.actions = invalid
                self.assertFalse(self.manager.cardAction(self.provider_id, "start"))
        client.message = {"token": SECRET}
        self.assertEqual(self.manager.rows[0]["cardStatus"], "")

    def test_notification_waits_for_action_and_stale_callbacks_are_ignored(self):
        client = self.activate()
        def action(_key):
            client.context.notify({"message": "Import complete", "refreshModels": True})
            return {"message": "Started"}
        client.card_action = action
        self.assertTrue(self.manager.cardAction(self.provider_id, "start"))
        self.settle()
        self.assertEqual(client.refreshes, [True])

    def test_notification_refresh_resumes_after_active_task_finishes(self):
        client = self.activate()
        self.host._models_busy = lambda _id=None: True
        client.context.notify({"message": "Imported", "refreshModels": True})
        self.app.processEvents()
        self.assertEqual(client.refreshes, [])
        self.host._models_busy = lambda _id=None: False
        self.host.changed.emit()
        self.settle()
        self.assertEqual(client.refreshes, [True])
        previous = self.manager.status.copy()
        client.context.notify({"message": SECRET, "refreshModels": "invalid"})
        self.app.processEvents()
        self.assertEqual(self.manager.status, previous)
        self.manager._invalidate(self.provider_id)
        self.assertTrue(client.context.cancelled.is_set())
        client.context.notify({"message": "stale", "refreshModels": True})
        self.app.processEvents()
        self.assertEqual(self.manager.status, previous)
        self.assertEqual(client.refreshes, [True])

    def test_bundle_selector_and_uninstall_use_existing_manager_transaction(self):
        self.manager.bundled.available = Mock(return_value=[{"id": "fixture", "name": "Fixture", "version": "1.0.0"}])
        self.manager.bundled.install = Mock(return_value=True)
        self.assertEqual(self.manager.availableBundles[0]["id"], "fixture")
        self.assertTrue(self.manager.installBundled("fixture"))
        self.manager.bundled.install.assert_called_once_with("fixture")
        destination = self.manager.root / "packages/fixture/1.0.0"
        destination.mkdir(parents=True)
        self.manager._forget_package = Mock()
        self.host.store.data["bundledProviders"] = {"installed": {"fixture": "1.0.0"}, "uninstalled": []}
        with patch.object(self.host.store, "save", side_effect=OSError("Synthetic save failure")):
            self.assertFalse(self.manager.uninstall("fixture", "1.0.0"))
        self.assertEqual(self.host.store.data["bundledProviders"], {"installed": {"fixture": "1.0.0"}, "uninstalled": []})
        self.assertTrue(destination.is_dir())
        self.assertTrue(self.manager.uninstall("fixture", "1.0.0"))
        self.assertEqual(self.host.store.data["bundledProviders"], {"installed": {}, "uninstalled": ["fixture"]})
        self.assertEqual(self.host.store.data["providers"], [])


class ProviderRequestScopeTests(unittest.TestCase):
    def context(self): return ProviderContext({}, Path("C:/UmekoTests"), Secrets())

    def test_fallback_and_nested_scopes_restore_their_previous_event(self):
        context = self.context()
        first, second = threading.Event(), threading.Event()
        self.assertIs(context.request_cancelled, context.cancelled)
        with request_scope(first) as supplied:
            self.assertIs(supplied, first)
            self.assertIs(context.request_cancelled, first)
            with request_scope(second):
                second.set()
                self.assertIs(context.request_cancelled, second)
                self.assertTrue(context.request_cancelled.is_set())
            self.assertIs(context.request_cancelled, first)
            self.assertFalse(first.is_set())
        self.assertIs(context.request_cancelled, context.cancelled)
        self.assertFalse(context.cancelled.is_set())

    def test_parallel_requests_on_same_provider_do_not_cross_cancel(self):
        context = self.context()
        events = [threading.Event(), threading.Event()]
        entered, observe = threading.Barrier(3), threading.Barrier(3)
        results = {}
        def worker(index):
            with request_scope(events[index]):
                captured = context.request_cancelled
                entered.wait(timeout=3)
                observe.wait(timeout=3)
                results[index] = (captured is events[index], captured.is_set(), context.cancelled.is_set())
            results[(index, "restored")] = context.request_cancelled is context.cancelled
        workers = [threading.Thread(target=worker, args=(index,)) for index in range(2)]
        for worker in workers: worker.start()
        entered.wait(timeout=3)
        events[0].set()
        observe.wait(timeout=3)
        for worker in workers: worker.join(timeout=3)
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(results[0], (True, True, False))
        self.assertEqual(results[1], (True, False, False))
        self.assertTrue(results[(0, "restored")])
        self.assertTrue(results[(1, "restored")])
        self.assertIs(context.request_cancelled, context.cancelled)

    def test_exception_resets_scope_and_new_thread_needs_explicit_event(self):
        context, event = self.context(), threading.Event()
        observed = []
        with self.assertRaisesRegex(RuntimeError, "synthetic"):
            with request_scope(event):
                worker = threading.Thread(target=lambda: observed.append(context.request_cancelled))
                worker.start()
                worker.join(timeout=3)
                self.assertFalse(worker.is_alive())
                raise RuntimeError("synthetic")
        self.assertEqual(observed, [context.cancelled])
        self.assertIs(context.request_cancelled, context.cancelled)
