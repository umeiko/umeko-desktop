"""Real concurrent Pi processes, bounded local fixtures, no external suppliers."""
import json
import os
import tempfile
import threading
import time
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
        self.started = {name: threading.Event() for name in ("A", "B")}
        self.gates = {name: threading.Event() for name in ("A", "B")}
        self.requests = []
        owner = self
        class Fixture:
            def complete(self, model, messages, tools, max_tokens):
                owner.requests.append(messages)
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
        self.controller.setWorkspace(QUrl.fromLocalFile(str(self.path)).toString())

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

    def test_skill_widget_toggle_rebuilds_native_prompt_without_interrupting_busy_chat(self):
        c = self.controller
        folder = self.path / 'agent/skills/gate-guide'
        folder.mkdir(parents=True)
        (folder / 'SKILL.md').write_text('---\nname: gate-guide\ndescription: UNIQUE_SKILL_ROUTING_MARKER\n---\nRead me only when needed.\n')
        def advertised():
            return 'UNIQUE_SKILL_ROUTING_MARKER' in str([m for m in self.requests[-1] if m['role'] == 'system'])
        self.assertTrue(c.send('TASK A'))
        self.wait_for(lambda: self.started['A'].is_set(), 'enabled skill prompt')
        self.assertTrue(advertised())
        record = c._view
        process = record.process
        c.desktopPlugins.setSessionEnabled('skill-manager', False)
        self.assertIs(record.process, process)
        self.assertTrue(record.busy and record.stale)
        self.gates['A'].set()
        self.wait_for(lambda: not record.busy, 'current task completes normally')
        self.assertFalse(record.cancelled)
        self.assertTrue(c.send('TASK C'))
        self.wait_for(lambda: not record.busy, 'disabled skill prompt')
        self.assertFalse(advertised())
        c.desktopPlugins.setSessionEnabled('skill-manager', True)
        self.assertTrue(c.send('TASK D'))
        self.wait_for(lambda: not record.busy, 'restored skill prompt')
        self.assertTrue(advertised())
        self.assertIn('Read me only', (folder / 'SKILL.md').read_text())

    def test_widget_catalogs_reuse_the_streaming_chat_process(self):
        c = self.controller
        folder = self.path / 'agent/skills/live-guide'
        folder.mkdir(parents=True)
        (folder / 'SKILL.md').write_text('---\nname: live-guide\ndescription: Live catalog fixture.\n---\nInstructions.', encoding='utf-8')
        self.assertTrue(c.send('TASK A'))
        record = c._view
        self.wait_for(self.started['A'].is_set, 'streaming fixture did not start')
        pid, transcript = record.process.processId(), record.messages
        with patch('app.pi_management.resource_command', side_effect=AssertionError('Started another Node process')):
            c.piManagement.scan()
            self.wait_for(lambda: not c.piManagement.busy, 'live extension catalog')
            self.assertTrue(c.piManagement.extensionsCurrent)
            self.assertTrue(any(row['path']=='builtin:codemode' for row in c.piManagement.extensions))
        replies = []
        self.assertTrue(c._pool.query_catalog(record, 'skills', replies.append))
        self.wait_for(lambda:bool(replies), 'live Skill catalog')
        self.assertTrue(replies[0]['ok'], replies)
        self.assertTrue(any(row['name']=='live-guide' for row in replies[0]['value']['skills']))
        self.assertEqual(record.process.processId(), pid)
        self.assertIs(record.messages, transcript, 'A directory read rebuilt the chat')
        self.assertTrue(record.busy, 'A directory read ended the active task')
        self.gates['A'].set()
        self.wait_for(lambda:not record.busy, 'streaming task completion')

    def test_concurrent_switching_lru_history_unread_and_drafts(self):
        c = self.controller
        c._pool.limit = 2
        self.assertTrue(c.send("TASK A"))
        a = c._view
        self.assertTrue(c.loading)
        self.assertTrue(c.running)
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
        self.assertFalse(c.loading, "Browsing a cached transcript started Pi")
        self.assertIsNone(b.process)
        self.assertFalse(c.running)
        self.gates["A"].set()
        self.wait_for(lambda: not a.busy, "first background completion")
        self.assertTrue(c._session_flags(a_id)["unread"])
        self.assertEqual(Store(c.store.directory).data["sessionMeta"][a_id]["unread"], True)
        c.openSession(a_id)
        self.assertEqual(c.messages[-1]["text"], "RESULT A")
        self.assertFalse(c._session_flags(a_id)["unread"])
        self.assertTrue(any(s["id"] == b_id for s in c.sessions), "parallel index update lost another session")

    def test_completion_timing_belongs_to_each_prompt_across_chat_switches(self):
        c, events = self.controller, []
        c.taskFinished.connect(lambda *args: events.append(args))
        self.assertTrue(c.send('TASK A'))
        first = c._view
        self.assertIsNotNone(first.prompt_started)
        self.wait_for(lambda: self.started['A'].is_set(), timeout=20000)
        c.newSession()
        self.assertTrue(c.send('TASK B'))
        second = c._view
        self.wait_for(lambda: self.started['B'].is_set(), timeout=20000)
        second_start = second.prompt_started
        first.prompt_started = time.monotonic() - 181
        self.gates['A'].set()
        self.wait_for(lambda: not first.busy)
        self.assertEqual(events, [(first.id, first.title, True, True)])
        self.assertIsNone(first.prompt_started)
        self.assertEqual(second.prompt_started, second_start)
        second.prompt_started = time.monotonic() - 179
        self.gates['B'].set()
        self.wait_for(lambda: not second.busy)
        self.assertEqual(events[-1], (second.id, second.title, True, False))
        self.assertIsNone(second.prompt_started)
        c._handle_pi_event(first, {'type': 'done'})
        self.assertEqual(len(events), 2)

    def prepare_live_turn(self, session_id="turn-status", phase="running"):
        """Exercise lifecycle events without starting a native Pi process."""
        c, record = self.controller, self.controller._view
        record.id, record.title = session_id, "Status fixture"
        record.action, record.phase, record.ready = "prompt", phase, True
        record.failed, record.cancelled = False, False
        record.prompt_started = 100.0
        record.messages = [{"role": "user", "text": "fixture task"},
            {"role": "assistant", "text": "", "error": False}]
        c._pool.touch(record, current=True)
        c._index_record(record)
        return record

    def test_turn_status_counts_prompt_startup_and_finishes_with_elapsed(self):
        c = self.controller
        record = self.prepare_live_turn(phase="loading")
        with patch("app.controller_runtime.time.monotonic", return_value=112.5):
            status = c.turnStatus
            self.assertTrue(c.running)
            self.assertTrue(c._session_flags(record.id)["running"])
            self.assertEqual(status["state"], "running")
            self.assertAlmostEqual(status["elapsed"], 12.5)
            self.assertAlmostEqual(status["startedAt"], (time.time() - 12.5) * 1000, delta=1000)
            record.phase = "running"
            c._handle_pi_event(record, {"type": "done"})
        self.assertFalse(c.running)
        self.assertEqual(c.turnStatus["state"], "finished")
        self.assertAlmostEqual(c.turnStatus["elapsed"], 12.5)
        self.assertEqual(c._session_flags(record.id)["outcome"], "finished")
        self.assertEqual(c.store.data["sessionMeta"][record.id]["lastTurn"],
            {"state": "finished", "elapsed": 12.5})

    def test_turn_status_marks_provider_errors_and_unexpected_exit_failed(self):
        c = self.controller
        for label, event, terminal in (
            ("error-event", {"type": "error", "message": "fixture failure"}, "done"),
            ("assistant-error", {"type": "message", "role": "assistant", "text": "failed", "stopReason": "error"}, "done"),
            ("unexpected-exit", None, "exit"),
        ):
            with self.subTest(case=label):
                record = self.prepare_live_turn(label)
                with patch("app.controller_runtime.time.monotonic", return_value=112.5):
                    self.assertEqual(c.turnStatus["state"], "running")
                    if event:
                        c._handle_pi_event(record, event)
                    c._handle_pi_event(record, {"type": terminal})
                self.assertFalse(c.running)
                self.assertEqual(c.turnStatus["state"], "failed")
                self.assertAlmostEqual(c.turnStatus["elapsed"], 12.5)
                self.assertEqual(c._session_flags(record.id)["outcome"], "failed")
                self.assertEqual(c.store.data["sessionMeta"][record.id]["lastTurn"]["state"], "failed")

    def test_turn_status_user_stop_is_stopping_then_stopped(self):
        c = self.controller
        record = self.prepare_live_turn()
        with patch("app.controller_runtime.time.monotonic", return_value=112.5):
            c.stop()
            self.assertTrue(record.cancelled)
            self.assertEqual(c.turnStatus["state"], "stopping")
            c._handle_pi_event(record, {"type": "done"})
        self.assertFalse(c.running)
        self.assertEqual(c.turnStatus["state"], "stopped")
        self.assertAlmostEqual(c.turnStatus["elapsed"], 12.5)
        self.assertEqual(c._session_flags(record.id)["outcome"], "stopped")
        self.assertEqual(c.store.data["sessionMeta"][record.id]["lastTurn"]["state"], "stopped")
        self.assertFalse(c._session_flags(record.id)["unread"])

    def test_background_turn_finishes_unread_without_changing_current_status(self):
        c = self.controller
        background = self.prepare_live_turn("background-turn")
        c._activate(c._new_view())
        with patch("app.controller_runtime.time.monotonic", return_value=112.5):
            c._handle_pi_event(background, {"type": "done"})
        self.assertEqual(c.turnStatus["state"], "")
        self.assertFalse(c.running)
        flags = c._session_flags(background.id)
        self.assertFalse(flags["running"])
        self.assertTrue(flags["unread"])
        self.assertEqual(flags["outcome"], "finished")

    def test_finished_turn_survives_store_reload_and_history_reopen(self):
        c = self.controller
        record = self.prepare_live_turn("saved-turn")
        with patch("app.controller_runtime.time.monotonic", return_value=112.5):
            c._handle_pi_event(record, {"type": "done"})
        c._activate(c._new_view())
        c._pool.records.pop(record.key)
        c.store = Store(c.store.directory)
        with patch.object(c, "_command_pi", return_value=True):
            c.openSession("saved-turn")
        self.assertIsNot(c._view, record)
        self.assertEqual(c._view.id, "saved-turn")
        self.assertFalse(c.running)
        self.assertEqual(c.turnStatus["state"], "finished")
        self.assertAlmostEqual(c.turnStatus["elapsed"], 12.5)
        self.assertEqual(c._session_flags("saved-turn")["outcome"], "finished")

    def test_history_visit_does_not_invent_completion_but_keeps_failure_and_stop(self):
        c = self.controller
        for reason, outcome in (("stop", ""), ("error", "failed"), ("aborted", "stopped")):
            with self.subTest(stop_reason=reason):
                session_id = "history-" + reason
                c._sessions.append({"id": session_id, "title": "Historical turn", "file": "",
                    "messages": [{"role": "assistant", "text": "historical reply", "stopReason": reason}]})
                with patch.object(c, "_command_pi", return_value=True) as command:
                    c.openSession(session_id)
                    # A visit and a duplicate readiness event cannot complete a task.
                    c._handle_pi_event(c._view, {"type": "done"})
                    command.assert_not_called()
                self.assertFalse(c.running)
                self.assertEqual(c.turnStatus["state"], outcome)
                self.assertEqual(c._session_flags(session_id)["outcome"], outcome)
                self.assertNotIn("lastTurn", c.store.data["sessionMeta"].get(session_id, {}))
                self.assertIsNone(c._view.process)

    def test_sidebar_bindings_reuse_rows_and_canonicalize_each_workspace_once(self):
        c = self.controller
        workspaces = [str(self.path / ('project-' + str(i))) for i in range(3)]
        for workspace in workspaces: c._ensure_project(workspace, reopen=True)
        c._sessions = [{"id": str(i), "title": "History", "workspace": workspaces[i % 3]} for i in range(11)]
        c._project_workspace_keys.clear()
        c._last_sidebar_rows = None
        resolved = []
        original = Path.resolve
        def resolve(path, *args, **kwargs):
            resolved.append(str(path))
            return original(path, *args, **kwargs)
        with patch.object(Path, 'resolve', resolve):
            c._refresh_sidebar()
            self.assertEqual(len(resolved), 3)
            expected = c.projectRows
            for _ in range(20): self.assertIs(c.projectRows, expected)
            self.assertEqual(len(resolved), 3)
            c._view.id = '4'
            c._refresh_sidebar()
            self.assertEqual(len(resolved), 3)
            self.assertTrue(next(row for row in c.projectRows if row['id'] == '4')['selected'])
            self.assertEqual(sum(row['kind'] == 'session' for row in c.projectRows), 11)

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

    def test_paged_checkpoint_coalesces_without_losing_new_tail_or_draft(self):
        c, gate = self.controller, threading.Event()
        record = c._view
        file = self.path/'checkpoint.jsonl'
        entries = [{'type':'session','id':'checkpoint','cwd':str(self.path)}]
        for i in range(400):
            entries.append({'type':'message','id':str(i),'parentId':str(i-1) if i else None,'message':{'role':'user' if i%2==0 else 'assistant','content':'message '+str(i)}})
        file.write_text(''.join(json.dumps(row)+'\n' for row in entries),encoding='utf-8')
        record.id,record.file,record.draft = 'checkpoint',str(file),'keep this draft'
        record.messages = preview(file)[0]
        c.chatChanged.emit()
        original = c.transcripts.open
        def blocked(*args,**kwargs):
            if not gate.wait(5): raise RuntimeError('checkpoint fixture timed out')
            return original(*args,**kwargs)
        with patch.object(c.transcripts,'open',side_effect=blocked):
            c._queue_transcript_index(record,'399')
            c._queue_transcript_index(record,'399',True)
            record.messages.extend([{'role':'user','text':'new live task'},{'role':'assistant','text':'still streaming'}])
            gate.set()
            deadline=time.monotonic()+10
            while (record.index_running or record.index_pending) and time.monotonic()<deadline:
                QTest.qWait(10);time.sleep(.001)
        self.assertFalse(record.index_running)
        self.assertIsNotNone(record.transcript)
        self.assertEqual([m['text'] for m in record.messages],['new live task','still streaming'])
        self.assertEqual(record.draft,'keep this draft')
        self.assertEqual(c.messageModel.rowCount(),402)

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
