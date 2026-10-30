"""Optional CodeArts distribution uses the generic host ZIP lifecycle offline."""
from __future__ import annotations

import copy
import importlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices

from app.provider_plugins import ProviderPlugins
from app.storage import Store
from umeko_provider_sdk.packages import pack_package

ROOT = Path(__file__).resolve().parents[1]
AK, SK = "FAKE_DISTRIBUTION_AK", "FAKE_DISTRIBUTION_SK"
MODEL = "huaweicloud/fake-distribution-model"


class Host(QObject):
    changed = Signal()
    toast = Signal(str)

    def __init__(self, root, profile):
        super().__init__()
        self.root, self.store, self.language = root, Store(profile), "en"
        self.restarts = 0

    def _models_busy(self, provider_id):
        return False

    def _restart_pi(self):
        # A unit fixture records the host notification without starting Pi.
        self.restarts += 1


class FakeSecrets:
    """Private fake vault, so Linux CI never accesses a user's OS keyring."""
    values = {}

    def __init__(self, path):
        self.path = Path(path)

    def _read(self):
        return copy.deepcopy(self.values.get(self.path, {}))

    def get(self, name, default=None):
        return self._read().get(name, default)

    def set(self, name, value):
        self.values.setdefault(self.path, {})[name] = copy.deepcopy(value)

    def clear(self, keep_credentials=False):
        credentials = self.get("credentials") if keep_credentials else None
        self.values[self.path] = {"credentials": credentials} if credentials else {}


class FakeLegacy:
    def __init__(self, profile):
        self.profile = str(profile.resolve())

    def get_password(self, service, username):
        if username != self.profile:
            raise AssertionError("Legacy lookup left the disposable profile")
        return None

    def delete_password(self, service, username):
        raise AssertionError("An empty fake legacy vault must not be modified")


class CodeartsDistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def wait(self, manager, provider_id):
        deadline = time.monotonic() + 5
        while provider_id in manager.busy and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.app.processEvents()
        self.assertNotIn(provider_id, manager.busy, "Offline management operation timed out")

    def test_explicit_zip_login_csv_catalog_uninstall_and_reimport(self):
        base = Path("C:/UmekoTests") if os.name == "nt" else Path(tempfile.gettempdir()) / "UmekoTests"
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="codearts-distribution-", dir=base) as temporary:
            work = Path(temporary)
            resources = work / "application/provider-resources"
            resources.mkdir(parents=True)
            (resources / "bundled-providers.json").write_text(
                json.dumps({"schemaVersion": 1, "providers": []}), encoding="utf-8")
            downloads = work / "Downloads"
            downloads.mkdir()
            archive = work / "codearts.zip"
            pack_package(ROOT / "provider_dev/plugins/codearts", archive)
            host = Host(resources.parent, work / "profile")
            notices, calls, guards = [], [], []
            host.toast.connect(notices.append)
            legacy = FakeLegacy(host.store.directory)
            original_import = importlib.import_module
            patched = set()

            def import_guard(name, package=None):
                module = original_import(name, package)
                account_class = getattr(module, "CodeartsAccount", None)
                if account_class is not None and account_class not in patched:
                    patched.add(account_class)

                    def ensure_cli(account):
                        account._cli = work / "fake-codearts.exe"
                        return True

                    def fake_run(account, command, *, env, cwd, timeout):
                        self.assertEqual(command[-1], "models")
                        self.assertEqual((env["CODEARTS_CLI_AK"], env["CODEARTS_CLI_SK"]), (AK, SK))
                        self.assertTrue(Path(cwd).resolve().is_relative_to(work.resolve()))
                        calls.append("models")
                        return subprocess.CompletedProcess(command, 0, (MODEL + "\n").encode(), b"")

                    for attribute, replacement in (("_legacy", lambda account: legacy),
                                                   ("_ensure_cli", ensure_cli), ("_run", fake_run)):
                        guard = patch.object(account_class, attribute, replacement)
                        guard.start()
                        guards.append(guard)
                return module

            manager = None
            try:
                with patch.dict(os.environ, {"CODEARTS_CLI_AK": "", "CODEARTS_CLI_SK": "",
                                             "TEMP": str(work), "TMP": str(work)}), \
                     patch("app.provider_plugins.ProtectedSecrets", FakeSecrets), \
                     patch("app.provider_plugins.QStandardPaths.writableLocation", return_value=str(downloads)), \
                     patch.object(QDesktopServices, "openUrl", side_effect=AssertionError("Unexpected browser")), \
                     patch("subprocess.Popen", side_effect=AssertionError("Unexpected external CLI")), \
                     patch("urllib.request.urlopen", side_effect=AssertionError("Unexpected network")):
                    manager = ProviderPlugins(host)
                    self.assertEqual((manager.rows, manager.packages, manager.availableBundles), ([], [], []))
                    self.assertEqual(host.store.data["providers"], [])
                    url = QUrl.fromLocalFile(str(archive)).toString()
                    self.assertTrue(manager.importZip(url), notices)
                    self.assertEqual(len(manager.packages), 1)
                    self.assertEqual(len(manager.rows), 1)
                    self.assertEqual(manager.clients, {}, "Import activated executable plugin code")
                    self.assertFalse(patched)
                    provider_id = manager.rows[0]["id"]
                    with patch("app.provider_plugins.importlib.import_module", side_effect=import_guard):
                        self.assertTrue(manager.login(provider_id, "{}"), notices)
                        self.wait(manager, provider_id)
                    self.assertTrue(patched, "Login bypassed the package's real account factory")
                    self.assertIn(provider_id, manager.clients)
                    self.assertEqual(manager.rows[0]["models"], [])
                    self.assertEqual(manager.rows[0]["cardFields"][0]["key"], "credentials")
                    csv = f"Access Key Id,Secret Access Key\n{AK},{SK}\n"
                    self.assertTrue(manager.saveCardSecret(provider_id, "credentials", csv), notices)
                    self.wait(manager, provider_id)
                    row = manager.rows[0]
                    self.assertEqual(row["models"][0]["upstream"], MODEL)
                    self.assertEqual(calls, ["models"])
                    secrets = manager._secrets(provider_id)
                    self.assertEqual(secrets.get("account"), {"ak": AK, "sk": SK})
                    public = json.dumps([row, host.store.data], ensure_ascii=False)
                    self.assertNotIn(AK, public)
                    self.assertNotIn(SK, public)
                    self.assertEqual(host.store.data["selectedProvider"], provider_id)
                    self.assertTrue(manager.uninstall("codearts", "0.1.0"), notices)
                    self.assertEqual((manager.rows, manager.packages, manager.clients), ([], [], {}))
                    self.assertIsNone(secrets.get("account"))
                    self.assertTrue(manager.importZip(url), notices)
                    self.assertEqual(len(manager.packages), 1)
                    self.assertEqual(len(manager.rows), 1)
                    self.assertNotEqual(manager.rows[0]["id"], provider_id)
                    self.assertEqual(manager.clients, {})
            finally:
                if manager is not None:
                    manager.close()
                for guard in reversed(guards):
                    guard.stop()
                FakeSecrets.values.clear()


if __name__ == "__main__":
    unittest.main()
