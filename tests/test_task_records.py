import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from app.task_records import TaskStore, versions_of


class TaskRecordsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.store = TaskStore(self.root / "tasks.sqlite3")
        self.task = self.store.create("Deliver a report", "Read inputs and write report.txt", str(self.root))

    def test_attempts_reopen_and_preserve_acceptance_after_replacement(self):
        session = self.root / "session.jsonl"
        session.write_text(json.dumps({"type": "session", "id": "pi-a"}) + "\n")
        output = self.root / "report.txt"
        output.write_text("original")
        files = versions_of([{"path": str(output)}])
        first = self.store.begin(self.task, str(self.root), "pi-a", str(session), files)
        self.store.step(first, "message", "pi-a/entry1", "assistant")
        self.store.files(first, "submitted", "call-1", files)
        self.store.finish(first, "finished", "")
        details = self.store.details(self.task, first)
        self.assertEqual(details["session_state"], "available")
        self.assertEqual([row["key"] for row in details["steps"]], ["pi-a", "pi-a/entry1"])
        self.assertEqual([row["source"] for row in details["files"]], ["input", "submitted"])
        self.assertEqual(self.store.tasks()[0]["state"], "finished")
        self.store.save_checks(first, details["files"])
        self.store.accept(self.task, first)
        self.assertEqual(self.store.tasks()[0]["state"], "accepted")

        replacement = self.root / "replacement.txt"
        replacement.write_text("original")
        old_stat = output.stat()
        os.utime(replacement, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
        replacement.replace(output)
        session.unlink()
        restored = TaskStore(self.store.path)
        details = restored.details(self.task, first)
        self.assertEqual(details["session_state"], "missing")
        self.assertEqual(details["files"][1]["state"], "changed")
        self.assertEqual(details["files"][1]["check_result"], "available")
        self.assertTrue(details["accepted"])
        second = restored.begin(self.task, str(self.root), "pi-b", "", [])
        self.assertNotEqual(first, second)
        self.assertEqual([row["session_id"] for row in restored.attempts(self.task)], ["pi-b", "pi-a"])
        self.assertFalse(restored.delete(self.task))
        restored.finish(second, "failed", "Provider request failed")
        self.assertEqual(restored.tasks()[0]["id"], self.task)
        session.write_text("preserved")
        self.assertTrue(restored.delete(self.task))
        self.assertTrue(output.is_file())
        self.assertTrue(session.is_file())
        self.assertEqual(restored.attempts(self.task), [])

    def test_crash_rolls_back_partial_write_and_leaves_pending_attempt(self):
        attempt = self.store.begin(self.task, str(self.root), "", "", [])
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.begin(self.task, str(self.root), "", "", [])
        child = subprocess.run([sys.executable, "-c", """
import os
import sqlite3
import sys
db = sqlite3.connect(sys.argv[1])
db.execute("UPDATE attempts SET state = 'finished'")
db.execute("UPDATE tasks SET objective = 'partial write'")
os._exit(23)
""", str(self.store.path)], timeout=15)
        self.assertEqual(child.returncode, 23)
        reopened = TaskStore(self.store.path)
        reopened.recover("App restarted")
        self.assertEqual(reopened.tasks()[0]["objective"], "Deliver a report")
        self.assertEqual(reopened.tasks()[0]["state"], "pending")
        self.assertEqual(reopened.details(self.task, attempt)["reason"], "App restarted")
        reopened.accept(self.task, attempt)
        self.assertIsNone(reopened.details(self.task, attempt)["accepted"])

    def test_partial_delivery_keeps_successful_files_and_cannot_be_accepted(self):
        path = self.root / "report.txt"
        path.write_text("delivered")
        attempt = self.store.begin(self.task, str(self.root), "", "", [])
        self.store.files(attempt, "submitted", "delivery", versions_of([{"path": str(path)}]), failed=1)
        self.store.finish(attempt, "finished", "")
        self.store.accept(self.task, attempt)
        detail = self.store.details(self.task, attempt)
        self.assertEqual(detail["state"], "failed")
        self.assertEqual(detail["files"][0]["path"], str(path))
        self.assertEqual(detail["steps"][0]["kind"], "delivery_error")
        self.assertIsNone(detail["accepted"])
