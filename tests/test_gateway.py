from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.gateway import Gateway, LocalServer, validate_base_url
from app.integration import Completion, UnconfiguredAdapter
from app.pi_runtime import node_executable, verify_runtime
from app.storage import Store

ROOT = Path(__file__).resolve().parents[1]


class FixtureAdapter:
    def __init__(self):
        self.calls = []

    def complete(self, model, messages, tools, max_tokens):
        self.calls.append((model, messages, tools, max_tokens))
        if tools and messages[-1]["role"] != "tool":
            tool = next((t for t in tools if t["name"] == "read_file"), tools[0])
            return Completion(tool_calls=[{"id": "read-1", "name": tool["name"], "arguments": {"path": "hello.txt"}}])
        return Completion("本机测试通过", input_tokens=3, output_tokens=5)


class GatewayTests(unittest.TestCase):
    def test_length_reason_takes_precedence_over_partial_tool_calls(self):
        from app.gateway import openai_response, anthropic_response
        result = Completion(tool_calls=[{'id':'partial', 'name':'write', 'arguments':{}}], finish_reason='length')
        self.assertEqual(openai_response(result, 'fixture')['choices'][0]['finish_reason'], 'length')
        self.assertEqual(anthropic_response(result, 'fixture')['stop_reason'], 'max_tokens')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "data")
        self.store.data.update(selectedProvider="internal", selectedModel="umeko-default", providers=[{"id":"internal", "name":"Fixture", "api":"internal", "baseUrl":"", "key":"", "models":[{"upstream":"default", "alias":"umeko-default"}]}])
        self.adapter = FixtureAdapter()
        self.gateway = Gateway(self.store, self.adapter)
        self.server = LocalServer(self.gateway, 0, "fixture-key")

    def tearDown(self):
        self.server.close()
        self.temp.cleanup()

    def request(self, path, body=None, token="fixture-key", headers=None):
        headers = headers or {"Authorization": "Bearer " + token}
        req = urllib.request.Request(f"http://127.0.0.1:{self.server.port}" + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json", **headers})
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.read().decode()

    def payload(self, **kwargs):
        return {"model": "umeko-default", "messages": [{"role": "user", "content": "你好"}], **kwargs}

    def test_requires_key(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/v1/models", token="wrong")
        self.assertEqual(caught.exception.code, 401)

    def test_openai_completion_and_mapping(self):
        self.store.data["providers"][0]["models"][0]["upstream"] = "private-original-name"
        result = json.loads(self.request("/v1/chat/completions", self.payload()))
        self.assertEqual(result["choices"][0]["message"]["content"], "本机测试通过")
        self.assertEqual(self.adapter.calls[0][0], "private-original-name")

    def test_anthropic_completion_system_and_x_api_key(self):
        result = json.loads(self.request("/v1/messages", self.payload(system="system text", max_tokens=100), headers={"x-api-key": "fixture-key"}))
        self.assertEqual(result["content"][0]["text"], "本机测试通过")
        self.assertEqual(self.adapter.calls[0][1][0], {"role": "system", "content": "system text"})

    def test_both_stream_formats(self):
        openai = self.request("/v1/chat/completions", self.payload(stream=True))
        self.assertIn("chat.completion.chunk", openai)
        self.assertTrue(openai.endswith("data: [DONE]\n\n"))
        anthropic = self.request("/v1/messages", self.payload(stream=True))
        self.assertIn("event: message_start", anthropic)
        self.assertIn("event: content_block_delta", anthropic)
        self.assertIn("event: message_stop", anthropic)

    def test_tool_call_serialization(self):
        tools = [{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}]
        data = json.loads(self.request("/v1/chat/completions", self.payload(tools=tools)))
        self.assertEqual(data["choices"][0]["finish_reason"], "tool_calls")
        call = data["choices"][0]["message"]["tool_calls"][0]
        self.assertEqual(json.loads(call["function"]["arguments"]), {"path": "hello.txt"})
        data = json.loads(self.request("/v1/messages", self.payload(tools=[{"name":"read_file","input_schema":{"type":"object"}}])))
        self.assertEqual(data["stop_reason"], "tool_use")

    def test_unknown_model_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/v1/chat/completions", self.payload(model="unknown"))
        self.assertEqual(caught.exception.code, 400)
        self.assertFalse(self.adapter.calls)

    def test_text_only_model_rejects_images_instead_of_discarding_them(self):
        content = [{"type": "text", "text": "Read the fixture"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,fixture"}}]
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request("/v1/chat/completions", self.payload(messages=[{"role": "user", "content": content}]))
        self.assertEqual(error.exception.code, 400)
        self.assertFalse(self.adapter.calls)
        self.store.data["providers"][0]["models"][0].update(vision=True, visionAuto=False)
        result = json.loads(self.request("/v1/chat/completions", self.payload(messages=[{"role": "user", "content": content}])))
        self.assertEqual(result["choices"][0]["message"]["content"], "本机测试通过")
        self.assertEqual(self.adapter.calls[-1][1][-1]["content"], content)

    def test_unconfigured_adapter_explicit_error(self):
        self.gateway.adapter = UnconfiguredAdapter()
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/v1/chat/completions", self.payload())
        self.assertEqual(caught.exception.code, 503)
        self.assertIn("integration_required", caught.exception.read().decode())

    def test_disabled_protocol_and_private_route(self):
        self.server.protocols["anthropic"] = False
        for path in ("/v1/messages", "/_pi/tool"):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.request(path, self.payload())
            self.assertEqual(caught.exception.code, 404)

    def test_dpapi_secret_round_trip(self):
        self.store.data["password"] = "synthetic-password"
        self.store.data["providers"].append({"id":"fixture", "name":"fixture", "api":"openai", "baseUrl":"http://127.0.0.1", "key":"synthetic-api-key", "models":[]})
        self.store.save()
        raw = self.store.path.read_text()
        self.assertNotIn("synthetic-password", raw)
        self.assertNotIn("synthetic-api-key", raw)
        restored = Store(self.root / "data")
        self.assertEqual(restored.data["password"], "synthetic-password")
        self.assertEqual(restored.data["providers"][-1]["key"], "synthetic-api-key")
        self.assertEqual(restored.data["server"]["keys"], self.store.data["server"]["keys"])



class ManualProviderTests(unittest.TestCase):
    def test_explicit_provider_url_and_tool_result_conversion(self):
        received = []
        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append((self.path, dict(self.headers), body))
                response = ({"content":[{"type":"text","text":"fixture"}],"usage":{"input_tokens":1,"output_tokens":2}}
                            if self.path.endswith("messages") else {"choices":[{"message":{"content":"fixture"}}]})
                raw = json.dumps(response).encode()
                self.send_response(200); self.send_header("Content-Length",str(len(raw))); self.end_headers(); self.wfile.write(raw)
        upstream = ThreadingHTTPServer(("127.0.0.1",0), Upstream)
        thread = threading.Thread(target=upstream.serve_forever, daemon=True); thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                store = Store(Path(temp))
                provider = {"id":"fixture","name":"fixture","api":"openai","baseUrl":f"http://127.0.0.1:{upstream.server_port}/v1","key":"fixture-key","models":[{"upstream":"actual-model","alias":"friendly"}]}
                store.data["providers"].append(provider)
                gateway = Gateway(store, UnconfiguredAdapter())
                self.assertEqual(gateway.complete("friendly",[{"role":"user","content":"hello"}]).text,"fixture")
                self.assertEqual(received[-1][0],"/v1/chat/completions")
                self.assertEqual(received[-1][2]["model"],"actual-model")
                self.assertEqual(received[-1][1]["Authorization"],"Bearer fixture-key")
                provider["api"] = "anthropic"
                self.assertEqual(gateway.complete("friendly",[{"role":"tool","tool_call_id":"tool-1","content":"result"}]).text,"fixture")
                self.assertEqual(received[-1][0],"/v1/messages")
                self.assertEqual(received[-1][2]["messages"][0]["content"][0]["type"],"tool_result")
                provider["models"][0].update(vision=True, visionAuto=False)
                images = [{"role": "user", "content": [{"type": "text", "text": "Inspect"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,cGl4ZWxz"}}]}]
                gateway.complete("friendly", images)
                self.assertEqual(received[-1][2]["messages"][0]["content"][1], {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "cGl4ZWxz"}})
                provider["api"] = "openai"
                gateway.complete("friendly", images)
                self.assertEqual(received[-1][2]["messages"], images)
        finally:
            upstream.shutdown(); upstream.server_close(); thread.join(timeout=2)

    def test_base_url_validation(self):
        for bad in ("", "ftp://host", "https://user:pass@host", "https://host?key=x"):
            with self.assertRaises(ValueError): validate_base_url(bad)


if __name__ == "__main__":
    unittest.main()
