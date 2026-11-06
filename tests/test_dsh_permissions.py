"""Global permission settings reach isolated DSH profiles and live sessions.

Only the existing local Store/controller fixture is used; no child process,
provider request, personal profile or visible window is involved.
"""
import json
import time
import unittest
from pathlib import Path

from PySide6.QtTest import QTest

try:
    from . import test_dsh_backend as backend_fixture
except ImportError:
    import test_dsh_backend as backend_fixture


class DshPermissionsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = backend_fixture.DshBackendTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    def profile_patch(self, process):
        path = Path(process.start["home"]) / "profiles/acp/cordis.patch.yml"
        return json.loads(path.read_text(encoding="utf-8"))

    def assert_profile_policy(self, process, mode):
        patch = self.profile_patch(process)
        rows = {row["id"]: row["config"] for row in patch if "id" in row and "config" in row}
        self.assertEqual(rows["sandbox-policy"], {"mode": "workspace-write", "additionalWritableRoots": []})
        self.assertEqual(rows["approval"], {"policy": "ask"})
        self.assertEqual(rows["permission"], {"defaultPreset": "workspace-write", "presets": {
            "read-only": {"sandbox": "read-only", "approval": "ask"},
            "workspace-write": {"sandbox": "workspace-write", "approval": "ask"},
            "danger-full-access": {"sandbox": "danger-full-access", "approval": "never"},
        }})
        plugins = [plugin for row in patch for plugin in row.get("insert", [])]
        permission_plugin = next(plugin for plugin in plugins if plugin["id"] == "umeko-tool-permissions")
        self.assertEqual(permission_plugin["name"], (backend_fixture.ROOT / "runtime/dsh-permissions.mjs").resolve().as_uri())
        self.assertEqual(permission_plugin["inject"], ["tools", "approval", "sandboxPolicy", "permissionPresets"])
        self.assertEqual(permission_plugin["config"], {"mode": mode})
        self.assertEqual(process.start["permissionMode"], mode)

    def test_profile_uses_global_mode_and_persisted_change_applies_on_resume(self):
        fixture = self.fixture
        controller = fixture.controller
        self.assertEqual(controller.store.data["agent"]["toolPermissionMode"], "auto")
        record, process = fixture.start_dsh("保存当前会话。")
        self.assert_profile_policy(process, "auto")
        fixture.event("delta", text="当前会话已准备好。")
        fixture.event("dsh_done", stopReason="end_turn")
        controller.setToolPermissionMode("ask")
        session_id = record.id
        controller.close()
        fixture.controllers.remove(controller)

        restored = fixture.make_controller()
        self.assertEqual(restored.store.data["agent"]["toolPermissionMode"], "ask")
        restored.openSession(session_id)
        deadline = time.monotonic() + 3
        while len(fixture.launches) < 2 and time.monotonic() < deadline:
            QTest.qWait(5)
        self.assertEqual(len(fixture.launches), 2)
        resumed = fixture.launches[-1]
        self.assertEqual(resumed.start["action"], "open")
        self.assertEqual(resumed.start["sessionId"], record.acp_session_id)
        self.assertEqual(resumed.start["home"], process.start["home"])
        self.assert_profile_policy(resumed, "ask")

    def test_global_setter_hot_updates_current_and_background_dsh_without_acp_config(self):
        fixture = self.fixture
        controller = fixture.controller
        first_record, background_process = fixture.start_dsh("后台会话请求。")
        fixture.event("dsh_done", stopReason="end_turn")
        controller.newSession()
        self.assertTrue(controller.setSessionBackend("dsh"))
        self.assertTrue(controller.send("当前会话请求。"))
        current_process = fixture.launches[-1]
        fixture.event("dsh_ready")
        self.assertIsNot(controller._view, first_record)
        self.assertTrue(controller._view.busy)
        self.assertIsNotNone(first_record.process)

        for mode in ("ask", "auto"):
            controller.setToolPermissionMode(mode)
            self.assertEqual(controller.store.data["agent"]["toolPermissionMode"], mode)
            for process in (background_process, current_process):
                self.assertEqual(process.writes[-1]["type"], "tool_permission_mode")
                self.assertEqual(process.writes[-1]["mode"], mode)

        for process in (background_process, current_process):
            updates = [row for row in process.writes if row.get("type") == "tool_permission_mode"]
            self.assertEqual([row["mode"] for row in updates], ["ask", "auto"])
            self.assertFalse(any(row.get("type") == "set_config" for row in process.writes),
                             "Permission changes use the private bridge command, not advertised ACP config IDs")


if __name__ == "__main__":
    unittest.main()
