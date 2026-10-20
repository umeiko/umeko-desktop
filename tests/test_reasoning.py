import json
import tempfile
import unittest
from pathlib import Path

from app.protocols import collect_openai, anthropic_events_to_openai, openai_events_to_anthropic
from app.transcripts import preview


class ReasoningTests(unittest.TestCase):
    def test_stream_conversion_keeps_reasoning_text_tools_and_usage(self):
        source = [
            {"choices": [{"delta": {"reasoning_content": "Check "}}]},
            {"choices": [{"delta": {"reasoning_content": "fixtures."}}]},
            {"choices": [{"delta": {"content": "Found a fix."}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "one", "function": {"name": "read", "arguments": '{"path":"a.txt"}'}}]}, "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}},
        ]
        converted = list(openai_events_to_anthropic(source, "fixture", "msg_fixture"))
        restored = collect_openai(anthropic_events_to_openai(converted))
        direct = collect_openai(source)
        self.assertEqual(restored, direct)
        self.assertEqual(restored["choices"][0]["message"]["reasoning_content"], "Check fixtures.")
        self.assertEqual(restored["choices"][0]["finish_reason"], "tool_calls")

    def test_anthropic_final_and_openai_reasoning_aliases(self):
        message = {"content": [{"type": "thinking", "thinking": "Local reasoning"}, {"type": "text", "text": "Answer"}]}
        result = collect_openai(anthropic_events_to_openai([message]))
        self.assertEqual(result["choices"][0]["message"]["reasoning_content"], "Local reasoning")
        for name in ("reasoning", "reasoning_text", "reasoning_content"):
            result = collect_openai([{"choices": [{"message": {"role": "assistant", "content": "Answer", name: "Local reasoning"}}]}])
            self.assertEqual(result["choices"][0]["message"]["reasoning_content"], "Local reasoning")

    def test_cold_preview_retains_reasoning_only_messages_on_active_branch(self):
        entries = [
            {"type": "session", "id": "fixture"},
            {"type": "message", "id": "one", "parentId": None, "message": {"role": "user", "content": "Check"}},
            {"type": "message", "id": "old", "parentId": "one", "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": "Old branch"}]}},
            {"type": "message", "id": "active", "parentId": "one", "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": "Active reasoning"}]}},
        ]
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "native.jsonl"
            original = "\n".join(json.dumps(entry) for entry in entries)
            file.write_text(original, encoding="utf-8")
            messages, _ = preview(file)
            self.assertEqual(messages[-1]["thinking"], "Active reasoning")
            self.assertEqual(messages[-1]["text"], "")
            self.assertEqual(len(messages), 2)
            self.assertEqual(file.read_text(encoding="utf-8"), original)
