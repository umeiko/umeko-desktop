"""Package history, UI-only permission, and native local-package removal."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import QCoreApplication, QObject, Signal
from app.package_records import PackageRecords
from app.pi_install import install_package, remove_package
from app.pi_management import PiManagement
from app.storage import DEFAULTS
from app.umeko_control import UmekoControl

ROOT = Path(__file__).resolve().parents[1]
APP = QCoreApplication.instance() or QCoreApplication([])


class Backend(QObject):
    jobDone = Signal(str, object)
    changed = Signal()
    toast = Signal(str)

    def __init__(self, directory):
        super().__init__()
        self.root = ROOT
        self.store = SimpleNamespace(directory=Path(directory), data={"agent": {"installPermission": "ask"}, "workspace": "", "projects": []}, save=Mock())
        self._view = SimpleNamespace(workspace="", id="fixture-session")
        self._pool = SimpleNamespace(records={"one": SimpleNamespace(ready=True)}, write=Mock())
        self.kernelBusy = False
        self._release = ROOT / "runtime"
        self._job = Mock()
        self._sessions = []

    @property
    def config(self):
        return {"providers": []}


class MarketplaceTests(unittest.TestCase):
    def test_records_survive_reload_and_keep_only_package_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            records = PackageRecords(temp)
            records.installed({"package": "fixture", "source": "npm:fixture", "version": "1.0.0", "installedBy": "agent",
                "reason": "needed for requested task", "audit": {"summary": "reviewed", "requestBody": "PRIVATE"}, "requestBody": "PRIVATE"})
            records.used({"package": "fixture", "source": "npm:fixture", "time": "2026-10-28T12:00:00Z", "arguments": "PRIVATE"})
            records.installed({"package": "fixture", "source": "npm:fixture", "version": "1.0.1", "installedBy": "user"})
            saved = PackageRecords(temp)
            row = saved.metadata("npm:fixture", "fixture")
            self.assertEqual((row["useCount"], row["lastUsed"], row["installedBy"], len(row["installations"])),
                (1, "2026-10-28T12:00:00Z", "user", 2))
            self.assertNotIn("PRIVATE", saved.path.read_text())

    def test_permission_is_user_only_and_reaches_live_bridge_without_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            backend = Backend(temp)
            manager = PiManagement(backend)
            backend.piManagement = manager
            self.assertEqual(DEFAULTS["agent"]["installPermission"], "ask")
            self.assertFalse(manager.setInstallPermission("anything"))
            backend._pool.records["one"].ready = False  # Starting bridges also receive revocations.
            self.assertTrue(manager.setInstallPermission("automatic"))
            self.assertEqual(manager.installPermission, "automatic")
            backend._pool.write.assert_called_once_with(backend._pool.records["one"], {"type": "install_permission", "value": "automatic"})
            control = UmekoControl(backend)
            rejected = control.execute({"operation": "agent.save", "arguments": {"config": {"installPermission": "automatic"}}})
            self.assertFalse(rejected["ok"])
            self.assertIn("Unknown Agent setting", rejected["error"])
            for request in ({"operation": "extensions.install", "arguments": {"command": "npm:fixture"}},
                            {"operation": "batch", "arguments": {"operations": [{"operation": "extensions.install", "arguments": {"command": "npm:fixture"}}]}}):
                self.assertFalse(control.execute(request)["ok"])
            backend._job.assert_not_called()

    def test_runtime_events_update_grouped_rows_and_progress(self):
        with tempfile.TemporaryDirectory() as temp:
            backend = Backend(temp)
            manager = PiManagement(backend)
            manager._extensions = [{"id": "one", "name": "fixture", "version": "1.2.0", "source": "npm:fixture", "scope": "global", "path": "/fixture/a.ts", "enabled": True},
                                   {"id": "two", "name": "fixture", "source": "npm:fixture", "scope": "global", "path": "/fixture/b.ts", "enabled": False}]
            with patch.object(manager, "scan"):
                manager.handleRuntimeEvent({"type": "package_install", "package": "fixture", "source": "npm:fixture", "installedBy": "agent", "reason": "task", "audit": "reviewed"}, backend._view)
            manager.handleRuntimeEvent({"type": "package_usage", "package": "fixture", "source": "npm:fixture"}, backend._view)
            manager.handleRuntimeEvent({"type": "marketplace_progress", "operation": "search", "state": "running", "message": "Searching packages"}, backend._view)
            rows = manager.packages
            self.assertEqual(len(rows), 1)
            self.assertEqual((rows[0]["installedBy"], rows[0]["useCount"], len(rows[0]["extensions"])), ("agent", 1, 2))
            self.assertEqual(manager.marketplaceProgress["message"], "Searching packages")

    def test_native_remove_resolves_relative_registered_sources_for_both_scopes(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            cwd, agent, package = base / "workspace", base / "agent", base / "local-package"
            cwd.mkdir(); agent.mkdir(); (package / "extensions").mkdir(parents=True)
            (package / "extensions/example.ts").write_text("throw new Error('must not execute')")
            (package / "package.json").write_text(json.dumps({"name": "fixture-local", "version": "1.0.0", "pi": {"extensions": ["extensions/example.ts"]}}))
            for local in (False, True):
                install_package(ROOT / "runtime", cwd, agent, str(package), local)
                settings = cwd / ".pi/settings.json" if local else agent / "settings.json"
                registered = json.loads(settings.read_text())["packages"][0]
                source = registered if isinstance(registered, str) else registered["source"]
                self.assertFalse(Path(source).is_absolute())
                remove_package(ROOT / "runtime", cwd, agent, source, local, package_root=package)
                self.assertEqual(json.loads(settings.read_text())["packages"], [])
            self.assertTrue(package.is_dir(), "Unregistering a local source preserves user package files")

    def test_package_only_resources_are_listed_without_an_extension_toggle(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = PiManagement(Backend(temp))
            manager._extensions = [{"id": "skill", "name": "a-skills", "version": "1.0", "source": "npm:a-skills", "scope": "global", "path": "/skills", "enabled": True, "origin": "package", "resourceKind": "package"},
                                   {"id": "tool", "name": "z-tools", "source": "npm:z-tools", "scope": "global", "path": "/tool.ts", "enabled": True},
                                   {"id": "builtin", "name": "mcp", "source": "builtin", "scope": "global", "path": "builtin:mcp", "enabled": True}]
            manager._package_records.used({"source": "npm:z-tools", "package": "z-tools"})
            rows = manager.packages
            self.assertEqual(rows[0]["name"], "z-tools")
            package = next(row for row in rows if row["id"] == "skill")
            self.assertTrue(package["removable"])
            self.assertEqual(package["extensions"], [])
            self.assertFalse(next(row for row in rows if row["id"] == "builtin")["removable"])

    def test_usage_count_and_last_used_continue_across_package_versions(self):
        with tempfile.TemporaryDirectory() as temp:
            records = PackageRecords(temp)
            records.used({"package": "fixture", "source": "npm:fixture@1.0.0", "time": "2026-10-28T10:00:00Z"})
            records.used({"package": "fixture", "source": "npm:fixture@2.0.0", "time": "2026-10-28T11:00:00Z"})
            row = PackageRecords(temp).metadata("npm:fixture@2.0.0", "fixture")
            self.assertEqual((row["useCount"], row["lastUsed"]), (2, "2026-10-28T11:00:00Z"))
            self.assertEqual(records.data["usage"]["fixture"]["source"], "npm:fixture@2.0.0")


if __name__ == "__main__": unittest.main()
