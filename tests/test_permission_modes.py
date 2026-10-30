"""Install and tool permissions coexist without changing one another."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtCore import QObject
from app.pi_management import PiManagement
from app.storage import Store
from app.umeko_control import UmekoControl
from tests import test_tool_permissions as fixtures

ROOT = fixtures.ROOT


class PermissionModesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        fixture = fixtures.ToolPermissionTests()
        fixture.directory = Path(self.temp.name)
        self.backend = fixture.controller()

    def test_distinct_defaults_and_all_combinations_survive_reload(self):
        directory = self.backend.store.directory
        agent = Store(directory).data["agent"]
        self.assertEqual((agent["installPermission"], agent["toolPermissionMode"]), ("ask", "auto"))
        for install in ("ask", "automatic"):
            for tool in ("ask", "auto"):
                store = Store(directory)
                store.data["agent"].update(installPermission=install, toolPermissionMode=tool)
                store.save()
                saved = Store(directory).data["agent"]
                self.assertEqual((saved["installPermission"], saved["toolPermissionMode"]), (install, tool))

    def test_user_slots_preserve_other_mode_and_resource_rows(self):
        backend = self.backend
        backend._view.workspace = ""
        backend._release = ROOT / "runtime"
        manager = PiManagement.__new__(PiManagement)
        QObject.__init__(manager)
        manager.controller = backend
        backend._pi_management = manager
        manager._extensions = [{"id": "existing"}]
        manager._marketplace_progress = {"state": "done"}
        manager._scan_pending = manager._busy = False
        manager._visible_context = manager._resource_key()
        manager.scan = Mock()
        backend.changed.connect(manager._sync_context)
        self.assertTrue(manager.setInstallPermission("automatic"))
        backend.setToolPermissionMode("ask")
        saved = Store(backend.store.directory).data["agent"]
        self.assertEqual((saved["installPermission"], saved["toolPermissionMode"]), ("automatic", "ask"))
        self.assertTrue(manager.setInstallPermission("ask"))
        self.assertEqual(backend.store.data["agent"]["toolPermissionMode"], "ask")
        backend.setToolPermissionMode("auto")
        self.assertEqual(backend.store.data["agent"]["installPermission"], "ask")
        manager.scan.assert_not_called()
        self.assertEqual(manager._extensions, [{"id": "existing"}])
        self.assertEqual(manager._marketplace_progress, {"state": "done"})

    def test_agent_cannot_change_either_mode_and_start_carries_both(self):
        backend = self.backend
        backend._view.busy = False
        backend.store.data["agent"].update(installPermission="automatic", toolPermissionMode="ask")
        control = UmekoControl.__new__(UmekoControl)
        QObject.__init__(control)
        control.b = backend
        control.operations = json.loads((ROOT / "runtime/umeko-operations.json").read_text(encoding="utf-8"))["operations"]
        control._dispatching = None
        for config in ({"installPermission": "ask"}, {"toolPermissionMode": "auto"},
                       {"installPermission": "ask", "toolPermissionMode": "auto"}):
            denied = control.execute({"operation": "agent.save", "arguments": {"config": config}})
            self.assertFalse(denied["ok"], denied)
            self.assertEqual(denied["error"], "Unknown Agent setting")
        result = control.execute({"operation": "agent.save", "arguments": {"config": {"instructions": "updated"}}})
        self.assertTrue(result["ok"], result)
        record = backend._view
        record.busy, record.stale, record.process = False, False, None
        record.model, record.reasoning_effort = "", "off"
        record.workspace, record.file, record.history = "", "", []
        backend._release = Path(self.temp.name) / "release"
        backend._release.mkdir()
        (backend._release / "bridge.mjs").write_text("// fixture", encoding="utf-8")
        from types import SimpleNamespace
        backend.private_server = SimpleNamespace(port=1)
        backend.private_token = "fixture"
        backend.gateway = SimpleNamespace(models=Mock(return_value=[]))
        backend._mcp_environment = Mock(return_value={})
        with patch("app.controller_runtime.node_executable", return_value="node"), \
                patch("app.controller_runtime.webview_configuration", return_value={}):
            self.assertTrue(backend._command_pi("inspect"))
        payload = backend._pool.start.call_args.args[3]
        self.assertEqual(payload["agent"]["installPermission"], "automatic")
        self.assertEqual(payload["permissionMode"], "ask")
        self.assertEqual(payload["agent"]["toolPermissionMode"], "ask")


if __name__ == "__main__":
    unittest.main()
