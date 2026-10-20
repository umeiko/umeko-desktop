"""Real concurrent Pi processes, bounded local fixtures, no external suppliers."""
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtTest import QTest

from app.controller import Controller, GREETINGS
from app.integration import Completion
from app.storage import Store
from app.transcripts import preview

ROOT = Path(__file__).resolve().parents[1]


class SessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {"UMEKO_DATA_DIR": str(self.path / "data")})
        self.environment.start()
        seed = Store()
        seed.data.update(selectedProvider="internal", selectedModel="umeko-default", providers=[{"id":"internal", "name":"Fixture", "api":"internal", "baseUrl":"", "key":"", "models":[{"upstream":"default", "alias":"umeko-default"}]}])
        seed.save()
        self.controller = Controller(ROOT)
        self.controller.store.data["agent"]["agentDir"] = str(self.path / "agent")
        self.controller.setWorkspace(QUrl.fromLocalFile(str(self.path)).toString())
        self.started = {name: threading.Event() for name in ("A", "B")}
        self.gates = {name: threading.Event() for name in ("A", "B")}
        owner = self
        class Fixture:
            def complete(self, model, messages, tools, max_tokens):
                content = next(message["content"] for message in reversed(messages) if message["role"] == "user")
                if isinstance(content, list):
                    content = " ".join(block.get("text", "") for block in content)
                name = content.rsplit(" ", 1)[-1]
                if name in owner.gates:
                    owner.started[name].set()
                    if not owner.gates[name].wait(20):
                        raise RuntimeError("fixture gate timed out")
                return Completion("RESULT " + name)
        self.controller.gateway.adapter = Fixture()

    def wait_for(self, predicate, message="condition", timeout=10000):
        for _ in range(timeout // 25):
            QTest.qWait(25)
            if predicate(): return
        self.fail("Timed out: " + message)

    def tearDown(self):
        for gate in self.gates.values(): gate.set()
        self.controller.close()
        QTest.qWait(100)
        self.environment.stop()
        self.temp.cleanup()

    def test_concurrent_switching_lru_history_unread_and_drafts(self):
        c = self.controller
        c._pool.limit = 2
        self.assertTrue(c.send("TASK A"))
        a = c._view
        self.assertTrue(c.loading)
        self.assertFalse(c.running)
        self.wait_for(lambda: self.started["A"].is_set(), "first request")
        a_id, a_pid = a.id, a.process.processId()
        c.setDraft("draft A")
        c.newSession()
        self.assertFalse(c.busy)
        self.assertTrue(c.send("TASK B"))
        b = c._view
        self.wait_for(lambda: self.started["B"].is_set(), "parallel request")
        self.assertEqual(c.runningCount, 2)
        b_id, b_pid = b.id, b.process.processId()
        c.openSession(a_id)
        self.assertIs(c._view, a)
        self.assertEqual(a.process.processId(), a_pid)
        self.assertEqual(c.messages[0]["text"], "TASK A")
        self.assertEqual(c._view.draft, "draft A")
        c.newSession()
        self.gates["B"].set()
        self.wait_for(lambda: not b.busy, "background completion")
        self.assertTrue(c._session_flags(b_id)["unread"])
        self.assertTrue(c._session_flags(a_id)["running"])
        self.assertEqual(a.process.processId(), a_pid)
        c.openSession(b_id)
        self.assertEqual(c.messages[-1]["text"], "RESULT B")
        self.assertFalse(c._session_flags(b_id)["unread"])
        self.assertEqual(b.process.processId(), b_pid)
        c.newSession()
        self.assertTrue(c.send("TASK C"))
        third = c._view
        self.wait_for(lambda: not third.busy, "third completion")
        self.assertIsNone(b.process, "least recently used idle Pi was not evicted")
        self.assertEqual(a.process.processId(), a_pid, "running Pi was evicted")
        self.assertTrue(Path(b.file).is_file())
        c.openSession(b_id)
        self.assertEqual(c.messages[-1]["text"], "RESULT B", "history waited for Pi")
        self.assertTrue(c.loading)
        self.assertFalse(c.running)
        self.wait_for(lambda: not b.busy, "cold Pi resume")
        self.gates["A"].set()
        self.wait_for(lambda: not a.busy, "first background completion")
        self.assertTrue(c._session_flags(a_id)["unread"])
        self.assertEqual(Store(c.store.directory).data["sessionMeta"][a_id]["unread"], True)
        c.openSession(a_id)
        self.assertEqual(c.messages[-1]["text"], "RESULT A")
        self.assertFalse(c._session_flags(a_id)["unread"])
        self.assertTrue(any(s["id"] == b_id for s in c.sessions), "parallel index update lost another session")

    def test_context_usage_follows_view_without_background_session_leaks(self):
        c = self.controller
        first, second = c._view, c._new_view()
        initial = {"model": first.model, "tokens": 33000, "contextWindow": 128000, "percent": 25.78125}
        c._handle_pi_event(first, {"type": "context_usage", "usage": initial})
        self.assertEqual(c.contextUsage, initial)
        c._activate(second)
        self.assertEqual(c.contextUsage, {})
        c._handle_pi_event(first, {"type": "context_usage", "usage": {**initial, "tokens": 100000, "percent": 78.125}})
        self.assertEqual(c.contextUsage, {})
        c._activate(first)
        self.assertEqual(c.contextUsage["tokens"], 100000)
        c.selectModel(first.provider, first.model)
        self.assertEqual(c.contextUsage["tokens"], 100000)
        c._handle_pi_event(first, {"type": "context_usage", "usage": {"model": "previous-model", "tokens": 5, "contextWindow": 100, "percent": 5}})
        self.assertEqual(c.contextUsage, {})
        c._handle_pi_event(first, {"type": "context_usage", "usage": {**initial, "tokens": None, "percent": None}})
        self.assertIsNone(c.contextUsage["percent"])

    def test_stop_only_selected_session_and_greeting_stays_stable(self):
        c = self.controller
        self.assertEqual(len(GREETINGS), 12)
        self.assertEqual(len(set(GREETINGS)), 12)
        greeting, portrait = c.greeting, c.portrait
        c.setDark(True)
        self.assertEqual((c.greeting, c.portrait), (greeting, portrait))
        c.send("TASK A")
        a = c._view
        self.wait_for(lambda: self.started["A"].is_set())
        c.newSession(); c.send("TASK B")
        b = c._view
        self.wait_for(lambda: self.started["B"].is_set())
        c.stop()
        self.wait_for(lambda: not b.busy, "selected stop")
        self.assertTrue(a.busy)
        self.assertTrue(b.cancelled)
        self.assertFalse(c._session_flags(b.id)["unread"])
        self.gates["A"].set()
        self.wait_for(lambda: not a.busy)

    def test_preview_uses_native_active_branch_without_starting_pi(self):
        file = self.path / "branch.jsonl"
        rows = [
            {"type": "session", "id": "session", "version": 3},
            {"type": "message", "id": "one", "parentId": None, "message": {"role": "user", "content": "first"}},
            {"type": "message", "id": "old", "parentId": "one", "message": {"role": "assistant", "content": [{"type": "text", "text": "old branch"}]}},
            {"type": "message", "id": "new", "parentId": "one", "message": {"role": "assistant", "content": [{"type": "text", "text": "new branch"}]}},
            {"type": "session_info", "id": "info", "parentId": "new", "name": "renamed"},
        ]
        file.write_text("\n".join(json.dumps(row) for row in rows) + '\n{"partial":', encoding="utf-8")
        messages, _ = preview(file)
        self.assertEqual([m["text"] for m in messages], ["first", "new branch"])


if __name__ == "__main__": unittest.main()
