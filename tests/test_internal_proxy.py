import json
import unittest
from app.protocols import collect_openai, iter_sse, openai_events_to_anthropic


class ProtocolTests(unittest.TestCase):
    def test_fragmented_utf8_tool_arguments_and_stop_reason(self):
        events = [
            {"choices": [{"delta": {"content": "你好", "tool_calls": [{"index": 0, "id": "call", "function": {"name": "read", "arguments": '{"path":'}}]}, "finish_reason": None}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"hello.txt"}'}}]}, "finish_reason": "tool_calls"}]},
        ]
        raw = ("".join("data: " + json.dumps(e, ensure_ascii=False) + "\n\n" for e in events) + "data: [DONE]\n\n").encode()
        chunks = [raw[i:i+1] for i in range(len(raw))]
        collected = collect_openai(iter_sse(chunks))
        msg = collected["choices"][0]["message"]
        self.assertEqual(msg["content"], "你好")
        self.assertEqual(json.loads(msg["tool_calls"][0]["function"]["arguments"]), {"path": "hello.txt"})
        anthropic = list(openai_events_to_anthropic(events, "fixture", "test"))
        self.assertEqual(anthropic[-2]["delta"]["stop_reason"], "tool_use")
        self.assertEqual(anthropic[-1]["type"], "message_stop")


if __name__ == "__main__": unittest.main()
