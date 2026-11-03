"""Conversation metadata lifecycle; tool commands and file deletion are stubbed."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import QObject

from app.controller import Controller
from app.pi_sessions import SessionState
from app.storage import Store


class SessionDangerGrantTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="umeko-danger-grants-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.backend = self.controller()

    def controller(self):
        backend = Controller.__new__(Controller)
        QObject.__init__(backend)
        backend.store = Store(self.path)
        backend._view = SessionState(key="view", id="chat-a")
        backend._view.process = object()
        backend._pool = SimpleNamespace(records={"view": backend._view}, write=Mock(),
            find=lambda identifier: next((r for r in backend._pool.records.values() if r.id == identifier), None),
            protected=lambda record: False, _clear_body=Mock())
        backend._sessions = [{"id": "chat-a", "title": "A", "file": "", "workspace": ""}]
        backend._management_jobs = set()
        backend._conversation_views = SimpleNamespace(discard=Mock())
        backend._closing = False
        backend._clear_current = Mock()
        backend.newSession = Mock()
        return backend

    def approval(self, category=1):
        self.backend._view.approval = {"id": "approval", "method": "confirm", "dangerCategory": category}

    def grant(self, category=1):
        self.approval(category)
        self.backend.grantDangerousApproval()

    def test_explicit_grant_persists_before_one_time_response_and_keeps_mode(self):
        self.backend.store.data["agent"]["toolPermissionMode"] = "ask"
        self.grant()
        self.assertEqual(self.backend._pool.write.call_args_list, [
            unittest.mock.call(self.backend._view, {"type": "dangerous_grants", "categories": [1]}),
            unittest.mock.call(self.backend._view, {"type": "ui_response", "id": "approval", "value": True})])
        self.assertEqual(Store(self.path).data["sessionMeta"]["chat-a"]["dangerousGrants"], [1])
        self.assertEqual(self.backend.store.data["agent"]["toolPermissionMode"], "ask")
        self.assertEqual(self.backend._view.approval, {})

    def test_categories_are_independent_and_other_or_new_chat_has_none(self):
        self.grant(1)
        self.grant(7)
        self.assertEqual([g["category"] for g in self.backend.dangerousGrants], [1, 7])
        for identifier in ("chat-b", ""):
            record = SessionState(key="other", id=identifier)
            self.assertEqual(self.backend._dangerous_grants(record), [])

    def test_same_chat_controller_restart_loads_grants_and_revoke_persists(self):
        self.grant(1)
        self.grant(7)
        restarted = self.controller()
        self.assertEqual(restarted._dangerous_grants(restarted._view), [1, 7])
        restarted.revokeDangerousGrant(1)
        self.assertEqual(Store(self.path).data["sessionMeta"]["chat-a"]["dangerousGrants"], [7])
        restarted.revokeDangerousGrant(0)
        self.assertNotIn("dangerousGrants", Store(self.path).data["sessionMeta"]["chat-a"])
        restarted._pool.write.assert_called_with(restarted._view, {"type": "dangerous_grants", "categories": []})

    def test_normal_approve_deny_and_generic_dialog_never_grant(self):
        for allowed in (True, False):
            self.approval()
            self.backend.respondApproval(allowed)
            self.assertEqual(self.backend.dangerousGrants, [])
        self.backend._view.approval = {"id": "generic", "method": "confirm"}
        self.backend.grantDangerousApproval()
        self.assertEqual(self.backend.dangerousGrants, [])

    def test_invalid_categories_and_coordinator_cannot_grant(self):
        for category in (0, 8, True, "1", None):
            self.approval(category)
            self.backend.grantDangerousApproval()
            self.assertEqual(self.backend.dangerousGrants, [])
        self.backend._view.global_agent = "coordinator"
        self.grant()
        self.assertEqual(self.backend.dangerousGrants, [])

    def test_failed_save_does_not_approve_or_change_live_policy(self):
        self.approval()
        with patch.object(self.backend.store, "save", side_effect=OSError("fixture")):
            self.backend.grantDangerousApproval()
        self.backend._pool.write.assert_not_called()
        self.assertEqual(self.backend.dangerousGrants, [])
        self.assertTrue(self.backend.pendingApproval)

    def test_archive_and_unarchive_never_restore_grants(self):
        self.grant()
        self.backend.archiveSession("chat-a", True)
        self.assertNotIn("dangerousGrants", Store(self.path).data["sessionMeta"]["chat-a"])
        self.backend.archiveSession("chat-a", False)
        self.assertEqual(self.backend.dangerousGrants, [])

    def test_archive_project_clears_each_chat(self):
        project = self.path / "project"
        project.mkdir()
        self.backend.store.data["projects"] = [{"id": "project", "path": str(project)}]
        self.backend._sessions[0]["workspace"] = str(project)
        self.grant()
        self.backend.archiveProject("project", True)
        self.assertNotIn("dangerousGrants", Store(self.path).data["sessionMeta"]["chat-a"])

    def test_delete_clears_session_metadata_without_touching_real_files(self):
        self.grant()
        with patch("app.controller.shutil.rmtree") as remove:
            self.backend.deleteSession("chat-a")
        remove.assert_not_called()
        self.assertNotIn("chat-a", Store(self.path).data["sessionMeta"])

    def test_native_branch_event_clears_owning_chat_only(self):
        self.grant()
        self.backend.store.data["sessionMeta"]["chat-b"] = {"dangerousGrants": [7]}
        self.backend._handle_pi_event(self.backend._view, {"type": "dangerous_grants_cleared"})
        self.assertEqual(self.backend.dangerousGrants, [])
        self.assertEqual(Store(self.path).data["sessionMeta"]["chat-b"]["dangerousGrants"], [7])

    def test_fork_starts_fresh_record_and_does_not_copy_grants(self):
        self.grant()
        backend = self.backend
        backend.store.data["workspace"] = ""
        backend._new_view = Mock(return_value=SessionState(key="fork"))
        backend._activate = Mock()
        backend._command_pi = Mock()
        backend.forkSessionById("chat-a")
        fork = backend._activate.call_args.args[0]
        self.assertEqual(backend._dangerous_grants(fork), [])
        self.assertEqual(backend._dangerous_grants(backend._view), [1])
        backend._command_pi.assert_called_once_with("fork", targetFile="")


if __name__ == "__main__":
    unittest.main()
