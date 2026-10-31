"""Permission preferences and UI-only updates, without services or model calls."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import QObject

from app.controller import Controller
from app.storage import Store
from app.umeko_control import UmekoControl


ROOT = Path(__file__).resolve().parents[1]


class ToolPermissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def controller(self):
        # Exercise the real Qt slot with only its local dependencies initialized.
        backend = Controller.__new__(Controller)
        QObject.__init__(backend)
        backend.root = ROOT
        backend.store = Store(self.directory / "profile")
        backend.store.data["ui"]["language"] = "en"
        backend.adapter = object()
        backend._view = SimpleNamespace(key="current", busy=True, process=object(), global_agent="")
        background = SimpleNamespace(key="background", busy=True, process=object())
        unloaded = SimpleNamespace(key="unloaded", busy=False, process=None)
        backend._pool = SimpleNamespace(records={r.key: r for r in (backend._view, background, unloaded)},
                                        write=Mock(), start=Mock())
        backend._restart_pi = Mock()
        backend._sessions = []
        backend._provider_plugins = SimpleNamespace()
        backend._pi_management = SimpleNamespace(busy=False)
        backend._app_about = SimpleNamespace()
        backend._kernel_busy = False
        return backend

    def test_default_legacy_profile_and_reload(self):
        store = Store(self.directory)
        self.assertEqual(store.data["agent"]["toolPermissionMode"], "auto")
        store.data["agent"]["toolPermissionMode"] = "ask"
        store.save()
        self.assertEqual(Store(self.directory).data["agent"]["toolPermissionMode"], "ask")
        legacy = self.directory / "legacy"
        legacy.mkdir()
        (legacy / "settings.json").write_text(json.dumps({"agent": {"instructions": "legacy"},
                                                          "server": {"keys": []}}), encoding="utf-8")
        loaded = Store(legacy)
        self.assertEqual(loaded.data["agent"]["toolPermissionMode"], "auto")
        self.assertEqual(loaded.data["agent"]["instructions"], "legacy")

    def test_live_ui_change_persists_and_broadcasts_to_busy_background(self):
        backend = self.controller()
        changes = Mock()
        backend.changed.connect(changes)
        backend.setToolPermissionMode("ask")
        self.assertEqual(Store(backend.store.directory).data["agent"]["toolPermissionMode"], "ask")
        changes.assert_called_once_with()
        payload = {"type": "tool_permission_mode", "mode": "ask", "language": "en",
                   "dataDir": str(backend.store.directory)}
        self.assertEqual(backend._pool.write.call_args_list,
                         [unittest.mock.call(backend._view, payload),
                          unittest.mock.call(backend._pool.records["background"], payload)])
        backend._restart_pi.assert_not_called()

    def test_invalid_mode_does_not_save_or_broadcast(self):
        backend = self.controller()
        messages = []
        backend.toast.connect(messages.append)
        with patch.object(backend.store, "save") as save:
            backend.setToolPermissionMode("unsafe")
        save.assert_not_called()
        backend._pool.write.assert_not_called()
        self.assertEqual(backend.store.data["agent"]["toolPermissionMode"], "auto")
        self.assertEqual(messages, ["工具执行权限模式无效"])

    def test_failed_save_keeps_current_mode_and_runtime(self):
        backend = self.controller()
        with patch.object(backend.store, "save", side_effect=OSError("fixture")):
            backend.setToolPermissionMode("ask")
        self.assertEqual(backend.store.data["agent"]["toolPermissionMode"], "auto")
        backend._pool.write.assert_not_called()
        backend._restart_pi.assert_not_called()

    def test_agent_api_cannot_change_mode_but_other_settings_preserve_it(self):
        backend = self.controller()
        backend._view.busy = False
        backend.store.data["agent"]["toolPermissionMode"] = "ask"
        control = UmekoControl.__new__(UmekoControl)
        QObject.__init__(control)
        control.b = backend
        control.operations = json.loads((ROOT / "runtime/umeko-operations.json").read_text(encoding="utf-8"))["operations"]
        control._dispatching = None
        denied = control.execute({"operation": "agent.save", "arguments": {"config": {"toolPermissionMode": "auto"}}})
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["error"], "Unknown Agent setting")
        for operation in ("agent.toolPermissionMode", "setToolPermissionMode", "agent.permissions"):
            result = control.execute({"operation": operation, "arguments": {"mode": "auto"}})
            self.assertFalse(result["ok"])
            self.assertIn("Unknown Umeko operation", result["error"])
        applied = control.execute({"operation": "agent.save", "arguments": {"config": {"instructions": "new"}}})
        self.assertTrue(applied["ok"], applied)
        self.assertEqual(backend.store.data["agent"]["toolPermissionMode"], "ask")
        self.assertEqual(backend.store.data["agent"]["instructions"], "new")

    def test_native_start_receives_current_permission_context(self):
        backend = self.controller()
        backend.store.data["agent"]["toolPermissionMode"] = "ask"
        record = backend._view
        record.busy, record.stale, record.process = False, False, None
        record.model, record.reasoning_effort = "", "off"
        record.workspace, record.file, record.history = "", "", []
        record.extension_modes = {"builtin:mcp":"disabled"}
        record.blocked_tools = ["write"]
        backend._release = self.directory / "release"
        backend._release.mkdir()
        (backend._release / "bridge.mjs").write_text("// fixture", encoding="utf-8")
        backend.private_server = SimpleNamespace(port=1)
        backend.private_token = "fixture"
        backend.gateway = SimpleNamespace(models=Mock(return_value=[]))
        backend._mcp_environment = Mock(return_value={})
        with patch("app.controller_runtime.node_executable", return_value="node"), \
                patch("app.controller_runtime.webview_configuration", return_value={}):
            self.assertTrue(backend._command_pi("inspect"))
        payload = backend._pool.start.call_args.args[3]
        self.assertEqual(payload["sessionExtensions"], {"builtin:mcp":False})
        self.assertEqual(payload["blockedTools"], ["write"])
        self.assertEqual(payload["permissionMode"], "ask")
        self.assertEqual(payload["language"], "en")
        self.assertEqual(payload["dataDir"], str(backend.store.directory))
        self.assertFalse(payload.get("globalCoordinator", False))

    def test_factory_restore_preserves_user_permission_mode(self):
        from app.pi_management import PiManagement
        backend = self.controller()
        backend.store.data["agent"].update(toolPermissionMode="ask", instructions="reset this")
        kernels = backend.store.directory / "kernels"
        kernels.mkdir()
        pointer = kernels / "active.json"
        pointer.write_text(json.dumps({"version": "old", "directory": "old"}), encoding="utf-8")
        manager = PiManagement.__new__(PiManagement)
        QObject.__init__(manager)
        manager.controller = backend
        value = {"agentDir": str(self.directory / "factory-agent"),
                 "release": str(kernels / "factory-fixture"), "backup": "fixture-backup"}
        with patch("app.pi_management.installed_version", return_value="1.3.0"):
            manager._apply_factory(value)
        self.assertEqual(Store(backend.store.directory).data["agent"]["toolPermissionMode"], "ask")
        self.assertEqual(backend.store.data["agent"]["instructions"], "")
        self.assertTrue(backend.store.data["agent"]["safeMode"])
        self.assertEqual(json.loads(pointer.read_text(encoding="utf-8")),
                         {"version": "1.3.0", "directory": "factory-fixture"})
        backend._restart_pi.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
