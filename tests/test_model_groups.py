"""Exercise model group routing at the authenticated loopback HTTP boundary."""

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.gateway import Gateway, LocalServer
from app.model_groups import GROUP_MODEL


class ModelGroupTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.replies = {}
        fixture = self

        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fixture.calls.append((body, self.headers["Authorization"]))
                status, raw = fixture.replies.get(body["model"], (200, None))
                if raw is None:
                    raw = json.dumps({"choices": [{"message": {"role": "assistant", "content": "backup answer"},
                                                  "finish_reason": "stop"}]}).encode()
                content_type = "text/event-stream" if raw.startswith(b"data: ") else "application/json"
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(upstream.server_close)
        self.addCleanup(upstream.shutdown)
        profile = tempfile.TemporaryDirectory()
        self.addCleanup(profile.cleanup)
        providers = [{"id": name, "name": name, "api": "openai", "key": name + "-secret",
                      "proxy": {"mode": "none"}, "baseUrl": f"http://127.0.0.1:{upstream.server_port}/v1",
                      "models": [{"alias": name, "upstream": name, "vision": index > 0, "visionAuto": False,
                                  "reasoningLevels": [effort], "reasoningLevelsAuto": False}]}
                     for index, (name, effort) in enumerate((("primary", "high"), ("backup", "vendor-level")))]
        group = {"enabled": True, "members": [{"provider": name, "model": name, "effort": effort}
                                             for name, effort in (("primary", "high"), ("backup", "vendor-level"))]}
        self.gateway = Gateway(SimpleNamespace(directory=Path(profile.name),
                                               data={"providers": providers, "modelGroup": group}), None)
        self.server = LocalServer(self.gateway, 0, "model-group-test", private=True)
        self.addCleanup(self.server.close)

    def request(self, server=None, **params):
        server = server or self.server
        request = Request(f"http://127.0.0.1:{server.port}/v1/chat/completions",
                          headers={"Authorization": "Bearer model-group-test", "Content-Type": "application/json"},
                          data=json.dumps({"model": GROUP_MODEL, "messages": [{"role": "user", "content": "hello"}],
                                           **params}).encode())
        return urlopen(request, timeout=10)

    def test_quota_uses_each_provider_once_with_its_own_effort_and_key(self):
        self.replies["primary"] = (429, b'{"error":{"code":"insufficient_quota"}}')
        with self.request(_umeko_reasoning_effort="off") as response:
            self.assertEqual(json.load(response)["choices"][0]["message"]["content"], "backup answer")
        self.assertEqual([(body["model"], body["reasoning_effort"], key) for body, key in self.calls],
                         [("primary", "high", "Bearer primary-secret"), ("backup", "vendor-level", "Bearer backup-secret")])
        self.assertEqual(self.calls[0][0]["messages"], self.calls[1][0]["messages"])
        self.assertNotIn(GROUP_MODEL, [row["id"] for row in self.gateway.models()])

    def test_invalid_request_does_not_attempt_another_provider(self):
        self.replies["primary"] = (400, b'{"error":{"code":"invalid_request","message":"Bad input"}}')
        with self.assertRaises(HTTPError) as result:
            self.request()
        self.assertEqual(result.exception.code, 400)
        result.exception.close()
        self.assertEqual([body["model"] for body, _ in self.calls], ["primary"])

    def test_images_only_reach_vision_members(self):
        with self.request(messages=[{"role": "user", "content": [{"type": "image_url",
                                                                  "image_url": {"url": "data:image/png;base64,AA=="}}]}]) as response:
            self.assertEqual(response.status, 200)
        self.assertEqual([body["model"] for body, _ in self.calls], ["backup"])

    def test_interrupted_stream_is_retried_as_a_new_request(self):
        self.replies["primary"] = (200, b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n')
        with self.request(stream=True) as response:
            events = response.read().decode()
        self.assertIn("partial", events)
        self.assertIn("umeko_stream_interrupted", events)
        self.assertNotIn("backup answer", events)
        self.assertEqual([body["model"] for body, _ in self.calls], ["primary"])
        with self.request(stream=True) as response:
            completed = response.read().decode()
        self.assertIn("backup answer", completed)
        self.assertNotIn("partial", completed)
        self.assertEqual([body["model"] for body, _ in self.calls], ["primary", "backup"])

    def test_group_is_private_and_stops_when_disabled(self):
        public = LocalServer(self.gateway, 0, "model-group-test")
        self.addCleanup(public.close)
        with self.assertRaises(HTTPError) as failed:
            self.request(server=public)
        failed.exception.close()
        self.gateway.store.data["modelGroup"]["enabled"] = False
        with self.assertRaises(HTTPError) as failed:
            self.request()
        failed.exception.close()
        self.assertEqual(self.calls, [])
