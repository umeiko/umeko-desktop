"""ID diagnostics do not load provider code or touch account credentials."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import QCoreApplication, QObject, Signal

from app.provider_plugins import ProviderPlugins
from umeko_provider_sdk import ProviderError


class FixtureController(QObject):
    toast = Signal(str)
    changed = Signal()

    def __init__(self, directory):
        super().__init__()
        self.root = directory
        self.store = SimpleNamespace(directory=directory, data={"providers": [
            {"id": "account-123", "api": "plugin", "pluginId": "echo-provider", "pluginVersion": "1.0.0"}
        ]})


class ProviderIdDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.controller = FixtureController(Path(self.temp.name))
        self.manager = ProviderPlugins(self.controller)
        self.notices = []
        self.controller.toast.connect(self.notices.append)
        self.package = self.manager.root / "packages" / "echo-provider" / "1.0.0"
        self.package.mkdir(parents=True)

    def test_package_id_for_account_names_id_and_list_fields(self):
        with self.assertRaises(ProviderError) as raised:
            self.manager._record("echo-provider")
        message = str(raised.exception)
        for expected in ("参数 id", "provider/account ID", "包操作使用 plugin", "plugins.list", "accounts[].id"):
            self.assertIn(expected, message)
        self.assertIs(self.manager._record("account-123"), self.controller.store.data["providers"][0])

    def test_wrong_package_arguments_fail_before_account_or_package_changes(self):
        original = list(self.controller.store.data["providers"])
        for operation in (self.manager.addAccount, self.manager.uninstall):
            for identifier, version in (("account-123", "1.0.0"), ("echo.zip", "1.0.0"),
                                        ("missing-package", "1.0.0"), ("echo-provider", "9.9.9")):
                with self.subTest(operation=operation.__name__, plugin=identifier, version=version):
                    self.assertFalse(operation(identifier, version))
                    message = self.notices[-1]
                    for expected in ("参数 plugin", "package ID", "参数 version", "plugins.list", "packages[].id", "accounts[].id"):
                        self.assertIn(expected, message)
                    self.assertNotIn(str(self.manager.root), message)
                    self.assertEqual(self.controller.store.data["providers"], original)
                    self.assertTrue(self.package.is_dir())

    def test_installed_package_id_and_version_resolve(self):
        self.assertEqual(self.manager.require_package("echo-provider", "1.0.0"), self.package)

    def test_login_and_refresh_report_whether_work_was_submitted(self):
        with patch.object(self.manager, "_package", side_effect=ProviderError("safe package error")), \
                patch.object(self.manager, "_submit") as submit:
            self.assertFalse(self.manager.login("account-123", "{}"))
            submit.assert_not_called()
            self.assertEqual(self.notices[-1], "safe package error")
        with patch.object(self.manager, "_submit", side_effect=ProviderError("safe refresh error")):
            self.assertFalse(self.manager.refreshModels("account-123"))
            self.assertEqual(self.notices[-1], "safe refresh error")
        with patch.object(self.manager, "_package", return_value=(None, ({"auth": {"fields": []}}, {}, {}))), \
                patch.object(self.manager, "_secrets", return_value=Mock(get=Mock(return_value={}))), \
                patch.object(self.manager, "_submit") as submit:
            self.assertTrue(self.manager.login("account-123", "{}"))
            self.assertEqual(submit.call_args.args[:2], ("account-123", "login"))
            self.assertTrue(self.manager.refreshModels("account-123"))
            self.assertEqual(submit.call_args.args[:2], ("account-123", "refresh"))

    def test_finished_apply_failure_reaches_later_signal_listener(self):
        observed = []
        self.manager.finished.connect(lambda provider_id, payload: observed.append((provider_id, payload)))
        self.manager.busy.add("account-123")
        with patch.object(self.manager, "_models", side_effect=ProviderError("safe model apply error")):
            self.manager.finished.emit("account-123", {"action": "refresh", "result": {"models": []}})
        self.assertEqual(observed[0][0], "account-123")
        self.assertEqual(observed[0][1]["error"], "safe model apply error")
        self.assertEqual(self.manager.status["account-123"], "safe model apply error")
        self.assertEqual(self.notices[-1], "safe model apply error")
        self.assertNotIn("account-123", self.manager.busy)

    def test_finished_keeps_account_label_without_untranslated_model_count(self):
        with patch.object(self.manager, "_models", return_value=[]), \
                patch.object(self.manager, "repair_selection"), \
                patch.object(self.manager, "_notify"):
            self.manager._finished("account-123", {"action": "refresh", "result": {
                "models": [], "label": "Connected.",
            }})
        self.assertEqual(self.manager.status["account-123"], "Connected.")
        self.assertEqual(self.notices[-1], "可用模型已更新")


if __name__ == "__main__":
    unittest.main()
