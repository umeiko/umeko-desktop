"""Subagent snapshots reuse ordinary tool history rows and stable child IDs."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.controller_runtime import PiControllerMixin
from app.transcripts import present, preview


def message(identifier, role="assistant", content="", parent=None):
    return {"type": "message", "id": identifier, "parentId": parent,
            "message": {"role": role, "content": content}}


def launch(identifier, call="launch", parent=None):
    return message(identifier, content=[{"type": "toolCall", "id": call,
        "name": "subagent", "arguments": {"type": "worker", "task": "Inspect"}}], parent=parent)


def snapshot(identifier, call="launch", child="child", state="running", background=True, continued=False, parent=None):
    agent = {"id": child, "type": "worker", "task": "Inspect", "status": state,
             "isBackground": background, "toolUses": 3, "activity": "Reading source",
             "result": "Answer" if state == "done" else "", "error": "Failed" if state == "error" else "",
             "continued": continued}
    return {"type": "custom", "id": identifier, "parentId": parent,
            "customType": "umeko-subagent", "data": {"version": 1, "toolCallId": call,
            "tool": {"id": "subagent:" + child, "name": "subagent", "path": "",
                     "arguments": {"type": "worker", "task": "Inspect", "mode": "background" if background else "foreground"},
                     "state": state, "result": agent["result"] or agent["error"], "subagent": agent}}}


class SubagentHistoryTests(unittest.TestCase):
    def test_resume_link_suppresses_launch_on_a_later_page(self):
        entries = [launch('continued', 'resume-call'), {'id':'link', 'type':'custom',
            'customType':'umeko-subagent-link', 'data':{'version':1, 'toolCallId':'resume-call',
            'subagentId':'subagent:child'}}]
        rows, _ = present(entries, '.')
        self.assertEqual(rows[0]['tools'], [])

    def test_snapshots_update_launch_owner_and_suppress_duplicate_launch(self):
        entries = [launch("a"), snapshot("s1"), message("b", content="Later answer"),
                   snapshot("s2", state="done")]
        rows, _ = present(entries, ".")
        self.assertEqual(len(rows), 2)
        self.assertEqual([tool["id"] for tool in rows[0]["tools"]], ["subagent:child"])
        tool = rows[0]["tools"][0]
        self.assertEqual(tool["state"], "done")
        self.assertEqual(tool["result"], "Answer")
        self.assertEqual(tool["subagent"]["toolUses"], 3)
        self.assertNotIn("tools", rows[1])

    def test_continuation_updates_original_child_across_later_turn(self):
        entries = [launch("a"), snapshot("s1"), message("u", "user", "Continue"),
                   launch("b", "continue"), snapshot("s2", call="continue", state="error", background=False, continued=True)]
        rows, _ = present(entries, ".")
        child = rows[0]["tools"][0]
        self.assertEqual(child["state"], "error")
        self.assertEqual(child["result"], "Failed")
        self.assertTrue(child["subagent"]["continued"])
        self.assertFalse(child["subagent"]["isBackground"])
        self.assertEqual(child["arguments"]["mode"], "foreground")
        self.assertEqual(rows[2]["tools"], [])
        self.assertEqual(sum(len(row.get("tools", [])) for row in rows), 1)

    def test_unlinked_snapshot_uses_preceding_assistant_and_launch_without_snapshot_survives(self):
        entries = [message("a", content="Working"), snapshot("s", call=None, state="interrupted", background=False),
                   launch("b", "ordinary")]
        rows, _ = present(entries, ".")
        self.assertEqual(rows[0]["tools"][0]["state"], "interrupted")
        self.assertEqual(rows[1]["tools"][0]["id"], "ordinary")

    def test_native_jsonl_round_trip_preserves_child_and_regular_tool_media(self):
        entries = [launch("a"), snapshot("s", state="done", parent="a"),
                   message("b", content=[{"type": "toolCall", "id": "read", "name": "read", "arguments": {"path": "report.txt"}},
                                         {"type": "toolCall", "id": "media", "name": "submit_to_chatbox", "arguments": {}}], parent="s"),
                   {"type": "message", "id": "r", "parentId": "b", "message": {"role": "toolResult", "toolCallId": "read", "content": "File contents"}},
                   {"type": "message", "id": "m", "parentId": "r", "message": {"role": "toolResult", "toolCallId": "media", "content": "Delivered", "details": {"umekoChatbox": {"version": 1, "items": [{"kind": "file", "path": "report.txt"}]}}}}]
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "history.jsonl"
            file.write_text("\n".join(json.dumps(entry) for entry in [{"type": "session", "cwd": temp}, *entries]) + "\n", encoding="utf-8")
            rows, _ = preview(file)
        self.assertEqual(rows[0]["tools"][0]["id"], "subagent:child")
        regular, media = rows[1]["tools"]
        self.assertEqual(regular["state"], "done")
        self.assertEqual(regular["result"], "File contents")
        self.assertTrue(regular["path"].endswith("report.txt"))
        self.assertEqual(media["media"], [{"kind": "file", "path": "report.txt"}])

    def test_live_update_refreshes_metadata_args_and_original_dirty_row(self):
        tool = snapshot("s")["data"]["tool"]
        record = SimpleNamespace(messages=[{"role": "assistant", "text": "", "tools": [tool]},
            {"role": "user", "text": "Continue"}, {"role": "assistant", "text": "Later"}],
            workspace=".", projection_dirty_from=None, body_dirty=False)
        host = SimpleNamespace(_closing=False, _view=object(), _subagents=SimpleNamespace(merge=lambda *_: None))
        updated = snapshot("final", state="done", background=False, continued=True)["data"]["tool"]
        PiControllerMixin._handle_pi_event(host, record, {"type": "tool", "id": updated["id"],
            "name": "subagent", "args": updated["arguments"], "state": "done", "result": "Answer",
            "subagent": updated["subagent"]})
        self.assertEqual(record.projection_dirty_from, 0)
        self.assertEqual(tool["arguments"]["mode"], "foreground")
        self.assertTrue(tool["subagent"]["continued"])
        self.assertEqual(tool["result"], "Answer")
        self.assertEqual(sum(len(row.get("tools", [])) for row in record.messages), 1)
