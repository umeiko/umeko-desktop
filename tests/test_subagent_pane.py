import copy
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication

from app.chat_model import ChatModel
from app.pi_sessions import SessionState
from app.subagents import Subagents
from app.transcript_index import TranscriptRepository


class Host(QObject):
    viewChanged = Signal()
    toast = Signal(str)

    def __init__(self, directory):
        super().__init__()
        self._view = SessionState(id="parent", ready=True, process=object())
        self.store = SimpleNamespace(data={"sessionMeta": {}}, save=Mock())
        self.transcripts = TranscriptRepository(Path(directory) / "index")
        self._closing = False
        self._write_pi = Mock()
        self._command_pi = Mock(return_value=True)


class SubagentPaneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.host = Host(self.directory.name)
        self.hub = Subagents(self.host)

    def tearDown(self):
        self.hub.close()
        self.directory.cleanup()

    def test_cards_leave_tool_history_and_preserve_surrounding_tool_order(self):
        rows = ChatModel.project([{"role": "assistant", "text": "Delegating", "tools": [
            {"id": "read", "name": "read"},
            {"id": "subagent:a", "name": "subagent", "subagent": {"id": "a", "task": "Inspect"}},
            {"id": "bash", "name": "bash"}]}])
        self.assertEqual([step["kind"] for step in rows[0]["activity"]], ["text", "tools", "subagents", "tools"])
        self.assertEqual(rows[0]["activity"][2]["agents"][0]["id"], "a")
        self.assertEqual([tool["id"] for step in rows[0]["activity"] if step["kind"] == "tools" for tool in step["tools"]], ["read", "bash"])

    def test_four_slots_and_session_isolation_and_stale_status(self):
        record = self.host._view
        for i in range(4):
            self.hub.merge(record, {"id": str(i), "status": "running", "task": "Work"})
        self.assertEqual(self.hub.activeCount, 4)
        self.assertEqual(len({agent["avatarSlot"] for agent in self.hub.activeAgents}), 4)
        record.process = None
        self.hub.open("0")
        self.hub.loading = False
        self.hub.merge(record, {"id": "historical", "status": "completed", "outputFile": "/old.jsonl"})
        self.hub.selected_id = "historical"
        self.assertFalse(self.hub.send("Resume when full"))
        self.host._view = SessionState(id="other")
        self.host.viewChanged.emit()
        self.assertEqual(self.hub.activeCount, 0)
        self.assertEqual(self.hub.selected, {})
        cold = SessionState(id="parent")
        self.host._view = cold
        self.host.viewChanged.emit()
        self.assertEqual(self.hub.activeCount, 0)
        self.assertEqual(len(self.hub.agents), 5)
        self.assertTrue(all(agent["status"] != "running" for agent in self.hub.agents))

    def test_steering_ack_retains_failed_draft_and_never_enters_parent(self):
        record = self.host._view
        self.hub.merge(record, {"id": "child", "status": "running", "avatarSlot": 2})
        self.hub.open("child")
        self.hub.handle(record, {"type": "subagent_context", "id": "child", "messages": [{"role": "user", "text": "Original task"}]})
        self.assertTrue(self.hub.send("Only inspect alpha"))
        payload, routed = self.host._write_pi.call_args.args
        self.assertIs(routed, record)
        self.assertEqual((payload["type"], payload["action"], payload["id"]), ("subagent-command", "send", "child"))
        self.assertEqual(record.messages, [])
        self.hub.handle(record, {"type": "subagent_command", "id": "child", "requestId": payload["requestId"], "ok": False, "message": "Stopped"})
        self.assertEqual(self.hub.context["draft"], "Only inspect alpha")
        self.assertFalse(self.hub.context["pending"])
        self.assertTrue(self.hub.send("Try again"))
        payload = self.host._write_pi.call_args.args[0]
        self.hub.handle(record, {"type": "subagent_command", "id": "child", "requestId": payload["requestId"], "ok": True})
        self.assertEqual(self.hub.context["draft"], "")

    def test_wrong_child_events_and_late_disk_reads_cannot_replace_selected_chat(self):
        record = self.host._view
        for child in ("a", "b"):
            self.hub.merge(record, {"id": child, "status": "running"})
        self.hub.open("a")
        self.hub.handle(record, {"type": "subagent_context", "id": "a", "messages": [{"role": "assistant", "text": "A"}]})
        generation = self.hub._generation
        self.hub.open("b")
        self.hub.handle(record, {"type": "subagent_context", "id": "b", "messages": [{"role": "assistant", "text": "B"}]})
        self.hub.handle(record, {"type": "subagent_event", "id": "a", "event": {"type": "delta", "text": "wrong"}})
        self.hub._loaded({"generation": generation, "messages": [{"role": "assistant", "text": "Old disk result"}]})
        self.assertEqual(self.hub.messages[-1]["text"], "B")
        self.hub.handle(record, {"type": "subagent_event", "id": "b", "event": {"type": "delta", "text": " updated"}})
        self.assertEqual(self.hub.messages[-1]["text"], "B updated")

    def test_live_message_and_row_limits_bound_ui_memory(self):
        record = self.host._view
        self.hub.merge(record, {"id": "a", "status": "running"})
        self.hub.open("a")
        for i in range(240):
            self.hub.handle(record, {"type": "subagent_event", "id": "a", "event": {"type": "user_start", "text": str(i)}})
        self.hub.handle(record, {"type": "subagent_event", "id": "a", "event": {"type": "delta", "text": "x" * 300000}})
        self.assertLessEqual(len(self.hub.messages), 200)
        self.assertLessEqual(len(self.hub.messages[-1]["text"]), 131072)
        self.assertTrue(self.hub.truncated)

    def test_open_during_kernel_start_defers_latest_watch_until_ready(self):
        record = self.host._view
        record.ready = False
        record.phase = "loading"
        record.action = "open"
        self.hub.merge(record, {"id": "a", "status": "completed"})
        self.hub.merge(record, {"id": "b", "status": "completed"})
        self.assertEqual([row["avatarSlot"] for row in self.hub.agents], [0, 1])
        self.hub.open("a")
        self.assertTrue(self.hub.loading)
        self.assertEqual(self.hub.error, "")
        self.hub.open("b")
        self.host._write_pi.reset_mock()
        record.ready = True
        self.hub.process_ready(record)
        self.assertFalse(self.host._write_pi.called)
        record.phase = "idle"
        self.hub.process_ready(record)
        calls = self.host._write_pi.call_args_list
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args[0]["id"], "b")

    def test_disk_history_during_start_still_subscribes_before_resume(self):
        record = self.host._view
        record.ready, record.phase, record.action = False, "loading", "open"
        self.hub.merge(record, {"id": "child", "status": "completed", "outputFile": "/old.jsonl"})
        self.hub._load_file = Mock()
        self.hub.open("child")
        self.hub._load_file.assert_called_once_with("/old.jsonl")
        self.hub.loading = False
        self.assertTrue(self.hub.send("Continue here"))
        record.ready, record.phase = True, "idle"
        self.hub.process_ready(record)
        commands = [call.args[0] for call in self.host._write_pi.call_args_list if call.args[0].get("action") != "unwatch"]
        self.assertEqual([command["action"] for command in commands], ["watch", "send"])


if __name__ == "__main__":
    unittest.main()
