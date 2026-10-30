"""Typed compaction transitions remain one local row in live and paged history."""
import json
import tempfile
import unittest
from pathlib import Path

from app.chat_model import ChatModel
from app.transcript_index import PAGE_ROWS, TranscriptRepository
from app.transcripts import compaction_view, present

EVENT = "01da3365-8d24-46cc-bdb1-ed1999a7231a"


def transition(entry_id, parent, state, **changes):
    data = {"version": 2, "eventId": EVENT, "state": state, "mode": "manual",
            "before": 22000, "after": None, "afterEstimated": True, "summary": "", "error": ""}
    data.update(changes)
    return {"type": "custom", "customType": "umeko-compaction", "id": entry_id, "parentId": parent,
            "timestamp": "2026-10-29T01:00:00Z" if state == "running" else "2026-10-29T01:01:00Z", "data": data}


def message(entry_id, parent, text="ordinary row", role="user"):
    return {"type": "message", "id": entry_id, "parentId": parent,
            "message": {"role": role, "content": [{"type": "text", "text": text}]}}


class CompactionTranscriptTests(unittest.TestCase):
    def test_latest_transition_keeps_original_position_identity_and_no_assistant_activity(self):
        start = transition("start", "before", "running")
        finish = transition("finish", "between", "success", after=8000, summary="Retain current task")
        entries = [message("before", None, role="assistant"), start,
                   message("between", "start", role="assistant"), finish]
        rows = ChatModel.project(present(entries, ".")[0])
        self.assertEqual(len(rows), 3)
        row = rows[1]
        self.assertEqual(row["entryId"], "start")
        self.assertEqual(row["timestamp"], start["timestamp"])
        self.assertEqual(row["compaction"], finish["data"])
        self.assertEqual(row["text"], "")
        self.assertNotIn("activity", row)
        self.assertEqual(rows[2]["text"], "ordinary row")

    def test_live_dirty_tail_updates_first_row_without_inserting_a_duplicate(self):
        messages = [compaction_view(transition("start", None, "running"))]
        messages.extend({"role": "user", "text": str(i)} for i in range(PAGE_ROWS * 3))
        model = ChatModel()
        try:
            model.update(messages)
            count = model.rowCount()
            messages.append(compaction_view(transition("finish", "tail", "failure", error="Retry later")))
            model.update(messages, dirty_from=len(messages) - 1)
            self.assertEqual(model.rowCount(), count)
            self.assertEqual(model.message(0)["entryId"], "start")
            self.assertEqual(model.message(0)["compaction"]["state"], "failure")
            self.assertEqual(model.message(0)["compaction"]["error"], "Retry later")
            self.assertEqual(model.message(count - 1)["text"], str(PAGE_ROWS * 3 - 1))
        finally:
            model.close()

    def test_late_result_reopens_across_pages_and_branch_without_moving_the_start(self):
        with tempfile.TemporaryDirectory(prefix="umeko-compaction-index-") as temp:
            root = Path(temp)
            file = root / "session.jsonl"
            start = transition("start", "before", "running")
            entries = [{"type": "session", "id": "fixture", "cwd": str(root)},
                       message("before", None), start]
            parent = "start"
            for i in range(PAGE_ROWS * 3):
                entry = message("work-" + str(i), parent, "work " + str(i))
                entries.append(entry); parent = entry["id"]
            def write():
                file.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8")
            write()
            repository = TranscriptRepository(root / "cache")
            initial = repository.open(file)
            self.assertEqual(initial.row(1)["compaction"]["state"], "running")
            entries.append(transition("finish", parent, "success", after=8000, summary="Preserve decisions"))
            write()
            updated = repository.open(file)
            self.assertEqual(updated.count, initial.count)
            row = updated.row(1)
            self.assertEqual(row["entryId"], "start")
            self.assertEqual(row["timestamp"], start["timestamp"])
            self.assertEqual(row["compaction"]["summary"], "Preserve decisions")
            self.assertEqual(updated.row(updated.count - 1)["text"], "work " + str(PAGE_ROWS * 3 - 1))
            cold = TranscriptRepository(root / "cold-cache").open(file)
            self.assertEqual(cold.row(1), row)
            earlier_branch = repository.open(file, leaf=parent)
            self.assertEqual(earlier_branch.row(1)["compaction"]["state"], "running")
            self.assertEqual(earlier_branch.count, updated.count)

    def test_invalid_typed_transitions_are_ignored(self):
        for changes in ({"eventId": "not-a-uuid"}, {"state": "done"}, {"mode": "other"},
                        {"before": -1}, {"after": True}, {"before": float("inf")},
                        {"afterEstimated": False}, {"summary": None}, {"error": {}}):
            with self.subTest(changes=changes):
                state = changes.get("state", "running")
                other = {key: value for key, value in changes.items() if key != "state"}
                entry = transition("invalid", None, state, **other)
                self.assertIsNone(compaction_view(entry))
                self.assertEqual(present([entry], ".")[0], [])

    def test_legacy_numeric_receipt_remains_compatible(self):
        entry = {"type": "custom", "customType": "umeko-compaction", "id": "legacy", "parentId": None,
                 "data": {"version": 1, "mode": "manual", "before": 22000, "after": 8000}}
        row = ChatModel.project(present([entry], ".")[0])[0]
        self.assertEqual(row["text"], "已压缩：22000 → 8000 tokens")
        self.assertNotIn("activity", row)
