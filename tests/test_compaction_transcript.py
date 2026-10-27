"""Numeric compaction notices survive regular and paged transcript projection."""
import json
import tempfile
import unittest
from pathlib import Path

from app.chat_model import ChatModel
from app.transcript_index import TranscriptRepository
from app.transcripts import present


class CompactionTranscriptTests(unittest.TestCase):
    def test_notice_is_separate_summary_free_and_copyable_after_resume(self):
        entries = [
            {"type": "message", "id": "work", "parentId": None, "message": {"role": "assistant", "content": [
                {"type": "text", "text": "Read workspace"},
                {"type": "toolCall", "id": "tool", "name": "read", "arguments": {"path": "fixture.txt"}}], "stopReason": "stop"}},
            {"type": "compaction", "id": "summary", "parentId": "work", "summary": "PRIVATE SUMMARY NOT FOR DISPLAY"},
            {"type": "custom", "customType": "umeko-compaction", "id": "notice", "parentId": "summary",
             "data": {"version": 1, "mode": "manual", "before": 22000, "after": 8000}},
        ]
        messages, _ = present(entries, ".")
        rows = ChatModel.project(messages)
        self.assertEqual(len(rows), 2)
        notice = rows[-1]
        self.assertEqual(notice["customType"], "umeko-compaction")
        self.assertEqual(notice["text"], "已压缩：22000 → 8000 tokens")
        self.assertNotIn("activity", notice)
        self.assertNotIn("PRIVATE SUMMARY", json.dumps(rows))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "session.jsonl"
            source.write_text("\n".join(json.dumps(row) for row in [{"type": "session", "id": "fixture", "cwd": str(root)}, *entries]) + "\n", encoding="utf-8")
            snapshot = TranscriptRepository(root / "cache").open(source)
            self.assertEqual(snapshot.count, 2)
            self.assertEqual(snapshot.row(1)["text"], notice["text"])
            self.assertEqual(snapshot.copy_text(1), notice["text"])
