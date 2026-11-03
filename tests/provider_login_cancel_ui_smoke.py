"""Offline sign-in cancellation through the real worker, signals and QML card."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QObject, Property, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest

from app.provider_plugins import ProviderPlugins
from umeko_provider_sdk import Provider, ProviderContext, ProviderError


class MemorySecrets:
    def __init__(self): self.data = {}
    def get(self, key, default=None): return self.data.get(key, default)
    def set(self, key, value): self.data[key] = value
    def _read(self): return self.data.copy()


class WaitingProvider(Provider):
    def __init__(self, context):
        super().__init__(context)
        self.started, self.release, self.exited = (threading.Event() for _ in range(3))
        self.request_event = None
        self.model_calls = 0

    def authenticate(self, credentials):
        self.request_event = self.context.request_cancelled
        if self.context.report_status:
            self.context.report_status("Waiting for authorization: " + credentials["token"])
        self.started.set()
        try:
            while not self.release.wait(.01):
                if self.request_event.is_set() or self.context.cancelled.is_set():
                    raise ProviderError("Sign-in interrupted: " + credentials["token"])
            return {"label": "Fixture account"}
        finally:
            self.exited.set()

    def list_models(self, refresh=False):
        self.model_calls += 1
        return [{"id": "fixture-model"}]


class Host(QObject):
    changed = Signal()
    toast = Signal(str)
    language = Property(str, lambda self: "en", constant=True)
    fontScale = Property(float, lambda self: 1., constant=True)
    lineSpacing = Property(str, lambda self: "standard", constant=True)
    themeStyle = Property("QVariantMap", lambda self: {"base": "light", "colors": {}}, constant=True)
    config = Property("QVariantMap", lambda self: self.store.data, notify=changed)
    providerPlugins = Property(QObject, lambda self: self.manager, constant=True)

    def __init__(self, directory):
        super().__init__()
        accounts = [{"id": key, "api": "plugin", "name": "Fixture " + key,
                     "pluginId": "fixture", "pluginVersion": "1.0.0", "models": []}
                    for key in ("first", "second")]
        self.store = SimpleNamespace(directory=directory, data={"providers": accounts,
            "selectedProvider": "", "selectedModel": "", "fontFamily": "", "theme": "light"}, save=lambda: None)
        self.manager = SyntheticManager(self)

    def _models_busy(self, _provider_id=None): return False
    def _restart_pi(self): pass


class SyntheticManager(ProviderPlugins):
    """Keep package import and persisted profiles outside this worker/UI test."""
    def __init__(self, host):
        QObject.__init__(self, host)
        self.c, self.root = host, host.store.directory
        self.lock = threading.RLock()
        self.clients, self.leases, self.busy, self.status = {}, {}, set(), {}
        self._client_tokens, self._pending_refresh, self._login_cancels = {}, {}, {}
        self._import_error, self.closed = {}, False
        self.bundled = SimpleNamespace(available=lambda: [])
        self.vaults = {key: MemorySecrets() for key in ("first", "second")}
        for key, vault in self.vaults.items():
            self.clients[key] = WaitingProvider(ProviderContext({}, self.root, vault))
        self.finished.connect(self._finished)
        self.progress.connect(self._progress)
        self.loginProgress.connect(self._login_progress)
        self.refreshReady.connect(self._drain_refresh)

    def _secrets(self, provider_id): return self.vaults[provider_id]
    def _package(self, record):
        return self.root, ({"auth": {"fields": [{"key": "token", "label": "Token", "secret": True}]}}, {}, {})


class ProviderLoginCancellationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="provider-sign-in-")
        self.host = Host(Path(self.temp.name))
        self.manager = self.host.manager
        self.providers = dict(self.manager.clients)
        self.notices = []
        self.host.toast.connect(self.notices.append)

    def tearDown(self):
        for provider in self.providers.values(): provider.release.set()
        self.manager.close()
        self.wait_until(lambda: all(not p.started.is_set() or p.exited.is_set() for p in self.providers.values()))
        self.temp.cleanup()

    def wait_until(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline: QTest.qWait(10)
        self.assertTrue(predicate(), "Synthetic sign-in timed out")

    def login(self, key="first"):
        self.assertTrue(self.manager.login(key, json.dumps({"token": "fixture-secret"})))
        self.wait_until(self.providers[key].started.is_set)

    def test_cancel_is_account_scoped_and_does_not_apply_login_results(self):
        self.login("first")
        self.login("second")
        self.wait_until(lambda: self.manager.status["first"] == "Waiting for authorization: ***")
        first, second = self.providers["first"], self.providers["second"]
        self.assertIsNot(first.request_event, second.request_event)
        self.assertTrue(self.manager.cancelLogin("first"))
        self.wait_until(lambda: "first" not in self.manager.busy)
        self.assertTrue(first.request_event.is_set())
        self.assertFalse(first.context.cancelled.is_set())
        self.assertFalse(second.request_event.is_set())
        self.assertIn("second", self.manager.busy)
        self.assertEqual(self.manager.status["first"], "登录已取消")
        self.assertEqual(first.model_calls, 0)
        self.assertEqual(self.manager.vaults["first"].data, {})
        self.assertEqual(self.notices, [])
        second.release.set()
        self.wait_until(lambda: not self.manager.busy)
        self.assertEqual(self.host.store.data["providers"][1]["accountLabel"], "Fixture account")
        self.assertIsNone(second.context.report_status)

    def test_provider_close_preserves_sanitized_reason_without_error_toast(self):
        self.login()
        self.providers["first"].context.cancelled.set()
        self.wait_until(lambda: not self.manager.busy)
        self.assertEqual(self.manager.status["first"], "Sign-in interrupted: ***")
        self.assertNotIn("first", self.manager.clients)
        self.assertEqual(self.notices, [])

    def test_other_management_operations_keep_their_existing_behavior(self):
        self.assertFalse(self.manager.cancelLogin("first"))
        self.assertTrue(self.manager.refreshModels("first"))
        self.wait_until(lambda: not self.manager.busy)
        self.assertEqual(self.host.store.data["providers"][0]["models"][0]["upstream"], "fixture-model")
        self.assertFalse(self.manager.rows[0]["loginCancellable"])

    def test_qml_cancel_button_and_event_loop_remain_responsive(self):
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty("backend", self.host)
        warnings = []
        engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
        engine.loadData(b'import QtQuick\nimport QtQuick.Controls\nWindow { visible: true; width: 1100; height: 900; ProviderPluginsSection { width: 1000 } }',
                        QUrl.fromLocalFile(str(ROOT / "app/qml/SignInFixture.qml")))
        self.assertTrue(engine.rootObjects(), warnings)
        window = engine.rootObjects()[0]

        def find(name):
            stack = [window.contentItem()]
            while stack:
                item = stack.pop()
                if item.objectName() == name: return item
                stack.extend(item.childItems())
            return None

        ticks = []
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: ticks.append(True))
        timer.start()
        try:
            self.login()
            self.wait_until(lambda: len(ticks) >= 3)
            cancel = find("cancelPluginLogin_first")
            self.assertIsNotNone(cancel)
            self.assertTrue(cancel.isVisible() and cancel.isEnabled())
            self.assertFalse(find("loginPlugin_first").isEnabled())
            point = cancel.mapToScene(cancel.boundingRect().center()).toPoint()
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
            self.wait_until(lambda: "first" not in self.manager.busy)
            self.assertEqual(self.manager.status["first"], "登录已取消")
            self.assertFalse(find("cancelPluginLogin_first").isVisible())
            self.assertTrue(find("loginPlugin_first").isEnabled())
            self.assertEqual(self.notices, [])
            self.assertFalse(warnings, "\n".join(warnings[:8]))
        finally:
            timer.stop()
            window.close()
            engine.deleteLater()
            self.app.processEvents()


if __name__ == "__main__": unittest.main()
