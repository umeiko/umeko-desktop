"""Isolated HTTP evidence for the shared reasoning mapper and discovery path."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.gateway import Gateway, LocalServer
from app.integration import UnconfiguredAdapter
from app.provider_models import fetch_model_windows
from app.request_diagnostics import RequestFailure


MESSAGES = [{"role": "user", "content": "Reply OK."}]


class ReasoningGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.calls, self.mode, self.rejections = [], "answer", []
        owner = self

        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def send(self, payload, status=200, sse=False):
                raw = (("data: " + json.dumps(payload) + "\n\n") if sse else json.dumps(payload)).encode()
                self.send_response(status)
                self.send_header("Content-Type", "text/event-stream" if sse else "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                owner.calls.append((self.path, None))
                self.send({"data": [{"id": "actual", "contextWindow": 8192,
                                     "reasoningLevels": ["level3", "level1"]}], "has_more": False})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.calls.append((self.path, body))
                effort = body.get("reasoning_effort")
                nested = body.get("chat_template_kwargs", {})
                mode = owner.mode
                if mode in ("enum", "no-list") and effort is not None:
                    levels = ["level1", "level3"] if mode == "enum" else ["low", "high"]
                    if effort not in levels:
                        error = {"error": {"param": "reasoning_effort", "message": "invalid reasoning_effort value"}}
                        if mode == "enum":
                            error["error"]["allowed"] = levels
                        return self.send(error, 400)
                if mode in ("reject-http", "reject-sse"):
                    error = {"error": {"message": "invalid chat_template_kwargs.reasoning_effort; expected one of 'low', 'high'",
                                       "param": "chat_template_kwargs.reasoning_effort", "allowed": ["low", "high"]}}
                    return self.send(error, 200 if mode == "reject-sse" else 400, mode == "reject-sse")
                if mode == "auth":
                    return self.send({"error": {"message": "invalid API key for reasoning_effort"}}, 401)
                if mode == "auth-effort":
                    return self.send({"error": {"message": "invalid reasoning_effort", "allowed": ["low", "high"],
                                               "param": "reasoning_effort"}}, 401)
                if mode in ("anthropic-switch-reject-http", "anthropic-switch-reject-sse"):
                    return self.send({"type": "error", "error": {"type": "invalid_request_error",
                                      "message": "enable_thinking is an unsupported field"}},
                                     400 if mode.endswith("http") else 200, mode.endswith("sse"))
                if mode in ("anthropic-effort-reject-http", "anthropic-effort-reject-sse"):
                    return self.send({"type": "error", "error": {"type": "invalid_request_error",
                                      "param": "output_config.effort", "message": "invalid effort",
                                      "allowed": ["low", "high"]}},
                                     400 if mode.endswith("http") else 200, mode.endswith("sse"))
                if mode == "anthropic":
                    return self.send({"content": [{"type": "text", "text": "OK"}], "stop_reason": "end_turn"})
                thinking = mode == "chat-template" and nested.get("enable_thinking") is True
                thinking = thinking or mode == "qwen" and body.get("enable_thinking") is True
                delta = {"content": "OK"}
                if thinking:
                    delta["reasoning"] = "visible reasoning"
                if mode == "split-think":
                    raw = "".join("data: " + json.dumps({"choices": [{"delta": {"content": value}}]}) + "\n\n"
                                  for value in ("<thi", "nk>hidden", "</think>", "OK"))
                    raw = raw.encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    return self.wfile.write(raw)
                self.send({"choices": [{"message": delta, "finish_reason": "stop"}]})

        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        self.thread = threading.Thread(target=lambda: self.upstream.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()
        self.model = {"alias": "friendly", "upstream": "actual", "reasoningLevels": ["low", "high"],
                      "reasoningLevelsAuto": False, "reasoningFormat": "openai", "reasoningFormatAuto": False}
        self.provider = {"id": "fixture", "name": "Fixture", "api": "openai", "key": "synthetic-key",
                         "baseUrl": f"http://127.0.0.1:{self.upstream.server_port}/v1", "models": [self.model]}
        self.store = SimpleNamespace(directory=Path(self.temp.name), data={"providers": [self.provider]})
        self.gateway = Gateway(self.store, UnconfiguredAdapter(), reasoning_rejected=lambda *args: self.rejections.append(args))

    def tearDown(self):
        self.upstream.shutdown()
        self.upstream.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def complete(self, parameters):
        return self.gateway.complete("friendly", MESSAGES, parameters=parameters)

    def test_custom_enum_and_no_enum_use_real_one_token_requests(self):
        self.model.update(reasoningLevelsAuto=True, reasoningFormatAuto=False)
        for mode, expected in (("enum", ["level1", "level3"]), ("no-list", ["low", "high"])):
            with self.subTest(mode=mode):
                self.mode = mode
                start = len(self.calls)
                result = self.gateway.detect_reasoning("friendly")
                self.assertEqual(result["levels"]["levels"], expected)
                self.assertEqual(result["levels"]["state"], "known")
                self.assertTrue(all(body["max_tokens"] == 1 for _, body in self.calls[start:]))
        self.assertFalse((self.store.directory / "request-errors").exists())
        self.assertFalse(self.rejections)

    def test_silent_acceptance_requires_observed_chat_template_format(self):
        self.model.update(reasoningFormatAuto=True)
        self.mode = "chat-template"
        result = self.gateway.detect_reasoning("friendly", advertised_levels=["low", "high"])
        self.assertEqual(result["format"]["format"], "chat-template")
        self.assertTrue(result["format"]["onObserved"])
        self.assertTrue(result["format"]["offVerified"])
        self.assertTrue(any(body.get("chat_template_kwargs", {}).get("enable_thinking") is True for _, body in self.calls))
        self.assertTrue(any(body.get("chat_template_kwargs", {}).get("enable_thinking") is False for _, body in self.calls))
        self.assertFalse((self.store.directory / "request-errors").exists())

    def test_qwen_switch_is_top_level(self):
        self.model.update(reasoningFormatAuto=True)
        self.mode = "qwen"
        result = self.gateway.detect_reasoning("friendly")
        self.assertEqual(result["format"]["format"], "qwen")
        on = [body for _, body in self.calls if body.get("enable_thinking") is True]
        self.assertTrue(on)
        self.assertTrue(all("enable_thinking" not in body.get("chat_template_kwargs", {}) for body in on))

    def test_split_think_markers_are_assembled_and_private_fields_are_removed(self):
        self.mode = "split-think"
        with patch("app.gateway.detect_model", side_effect=lambda request, **kwargs: request("high", "openai", 16)):
            result = self.gateway.detect_reasoning("friendly")
        self.assertEqual(result, {"thinking": True, "content": True})
        self.assertTrue(all(not any(key.startswith("_umeko_") for key in body) for _, body in self.calls))

    def test_forwarding_uses_mapper_once_and_off_is_explicit(self):
        self.model["reasoningFormat"] = "chat-template"
        self.complete({"_umeko_reasoning_effort": "high", "reasoning_effort": "high"})
        body = self.calls[-1][1]
        self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": True, "reasoning_effort": "high"})
        self.assertNotIn("reasoning_effort", body)
        self.complete({"_umeko_reasoning_effort": "off"})
        self.assertEqual(self.calls[-1][1]["chat_template_kwargs"], {"enable_thinking": False})

    def test_local_server_passes_documented_fields_and_restricts_private_intent(self):
        for private in (False, True):
            server = LocalServer(self.gateway, 0, "fixture", private=private)
            try:
                body = {"model": "friendly", "messages": MESSAGES, "enable_thinking": False,
                        "chat_template_kwargs": {"enable_thinking": False}, "thinking": {"type": "disabled"},
                        "reasoning": {"enabled": False}, "unexpected_key": "must not pass",
                        "_umeko_reasoning_effort": "high", "_umeko_reasoning_format": "qwen"}
                request = urllib.request.Request(f"http://127.0.0.1:{server.port}/v1/chat/completions",
                                                 data=json.dumps(body).encode(),
                                                 headers={"Content-Type": "application/json", "Authorization": "Bearer fixture"})
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=5) as response:
                    response.read()
                forwarded = self.calls[-1][1]
                self.assertNotIn("unexpected_key", forwarded)
                self.assertFalse(any(key.startswith("_umeko_") for key in forwarded))
                if private:
                    self.assertEqual(forwarded["reasoning_effort"], "high")
                    self.assertNotIn("enable_thinking", forwarded)
                else:
                    for key in ("enable_thinking", "chat_template_kwargs", "thinking", "reasoning"):
                        self.assertEqual(forwarded[key], body[key])
                    self.assertNotIn("reasoning_effort", forwarded)
            finally:
                server.close()

    def test_anthropic_url_and_native_effort_mapping_stay_compatible(self):
        self.provider["api"] = "anthropic"
        self.mode = "anthropic"
        self.model["reasoningFormat"] = "anthropic-adaptive"
        self.complete({"_umeko_reasoning_effort": "high"})
        self.assertEqual(self.calls[-1][0], "/v1/messages")
        self.assertEqual(self.calls[-1][1]["output_config"], {"effort": "high"})
        self.assertEqual(self.calls[-1][1]["thinking"], {"type": "adaptive"})
        self.complete({"_umeko_reasoning_effort": "off"})
        self.assertEqual(self.calls[-1][1]["thinking"], {"type": "disabled"})
        self.assertNotIn("output_config", self.calls[-1][1])

    def test_public_explicit_template_and_top_level_effort_are_both_preserved(self):
        server = LocalServer(self.gateway, 0, "fixture", private=False)
        try:
            body = {"model": "friendly", "messages": MESSAGES, "reasoning_effort": "high",
                    "chat_template_kwargs": {"enable_thinking": True, "reasoning_effort": "low"}}
            request = urllib.request.Request(f"http://127.0.0.1:{server.port}/v1/chat/completions",
                                             data=json.dumps(body).encode(),
                                             headers={"Content-Type": "application/json", "Authorization": "Bearer fixture"})
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=5) as response:
                response.read()
            forwarded = self.calls[-1][1]
            self.assertEqual(forwarded["reasoning_effort"], "high")
            self.assertEqual(forwarded["chat_template_kwargs"], body["chat_template_kwargs"])
        finally:
            server.close()

    def test_anthropic_compatible_switch_fields_reach_upstream_for_every_format(self):
        self.provider["api"] = "anthropic"
        self.mode = "anthropic"
        expected = {
            "anthropic": ({"output_config": {"effort": "high"}}, {}),
            "deepseek": ({"thinking": {"type": "enabled"}, "output_config": {"effort": "high"}},
                         {"thinking": {"type": "disabled"}}),
            "anthropic-adaptive": ({"thinking": {"type": "adaptive"}, "output_config": {"effort": "high"}},
                                   {"thinking": {"type": "disabled"}}),
            "qwen": ({"enable_thinking": True, "output_config": {"effort": "high"}}, {"enable_thinking": False}),
            "chat-template": ({"chat_template_kwargs": {"enable_thinking": True, "reasoning_effort": "high"}},
                              {"chat_template_kwargs": {"enable_thinking": False}}),
            "openai-none": ({"output_config": {"effort": "high"}}, {"output_config": {"effort": "none"}}),
        }
        for format, cases in expected.items():
            for effort, fields in zip(("high", "off"), cases):
                with self.subTest(format=format, effort=effort):
                    self.complete({"_umeko_reasoning_effort": effort, "_umeko_reasoning_format": format})
                    path, body = self.calls[-1]
                    self.assertEqual(path, "/v1/messages")
                    observed = {key: body[key] for key in
                                ("output_config", "thinking", "enable_thinking", "chat_template_kwargs", "reasoning", "reasoning_effort")
                                if key in body}
                    self.assertEqual(observed, fields)
                    self.assertFalse(any(key.startswith("_umeko_") for key in body))

    def test_anthropic_compatible_rejected_switch_keeps_http_and_sse_probe_details(self):
        self.provider["api"] = "anthropic"
        for mode, status in (("anthropic-switch-reject-http", 400), ("anthropic-switch-reject-sse", 200)):
            with self.subTest(mode=mode):
                self.mode = mode
                before = len(self.calls)
                with patch("app.gateway.detect_model", side_effect=lambda request, **kwargs: request("off", "qwen", 1)):
                    with self.assertRaises(ValueError) as error:
                        self.gateway.detect_reasoning("friendly")
                self.assertIn("enable_thinking", str(error.exception))
                self.assertEqual(error.exception.status_code, status)
                self.assertEqual(len(self.calls), before + 1)
                self.assertEqual(self.calls[-1][1]["enable_thinking"], False)
        self.assertFalse(self.rejections)
        self.assertFalse((self.store.directory / "request-errors").exists())

    def test_anthropic_compatible_effort_rejection_notifies_without_retry(self):
        self.provider["api"] = "anthropic"
        for mode in ("anthropic-effort-reject-http", "anthropic-effort-reject-sse"):
            with self.subTest(mode=mode):
                self.mode = mode
                before, notifications = len(self.calls), len(self.rejections)
                with self.assertRaises(RequestFailure) as error:
                    self.complete({"_umeko_reasoning_effort": "max", "_umeko_reasoning_format": "qwen"})
                self.assertFalse(error.exception.retryable)
                self.assertEqual(self.calls[-1][1]["output_config"], {"effort": "max"})
                self.assertEqual(len(self.calls), before + 1)
                self.assertEqual(len(self.rejections), notifications + 1)
                self.assertEqual(self.rejections[-1], ("fixture", "actual", "max", ["low", "high"]))

    def test_automatic_verified_off_format_applies_only_to_private_off_chat(self):
        self.provider["api"] = "anthropic"
        self.mode = "anthropic"
        self.model.update(reasoningFormat="anthropic", reasoningFormatAuto=True,
                          reasoningFormatDetection={"state": "known", "offVerified": True, "offFormat": "qwen"})
        self.complete({"_umeko_reasoning_effort": "high"})
        self.assertEqual(self.calls[-1][1]["output_config"], {"effort": "high"})
        self.assertNotIn("enable_thinking", self.calls[-1][1])
        self.complete({"_umeko_reasoning_effort": "off"})
        self.assertIs(self.calls[-1][1]["enable_thinking"], False)
        self.assertNotIn("output_config", self.calls[-1][1])
        self.model["reasoningFormatAuto"] = False
        self.complete({"_umeko_reasoning_effort": "off"})
        self.assertNotIn("enable_thinking", self.calls[-1][1])
        self.model["reasoningFormatAuto"] = True
        self.complete({"_umeko_reasoning_effort": "off", "_umeko_reasoning_format": "deepseek"})
        self.assertEqual(self.calls[-1][1]["thinking"], {"type": "disabled"})
        self.assertNotIn("enable_thinking", self.calls[-1][1])
        self.model["reasoningFormatDetection"]["offFormat"] = "not-a-format"
        self.complete({"_umeko_reasoning_effort": "off"})
        self.assertNotIn("enable_thinking", self.calls[-1][1])

    def test_http_and_sse_effort_rejections_notify_once_without_retry(self):
        for mode in ("reject-http", "reject-sse"):
            with self.subTest(mode=mode):
                self.mode = mode
                before = len(self.calls)
                notifications = len(self.rejections)
                with self.assertRaises(RequestFailure) as error:
                    self.complete({"_umeko_reasoning_effort": "max"})
                self.assertFalse(error.exception.retryable)
                self.assertIn("off, low, high", str(error.exception))
                self.assertEqual(len(self.calls), before + 1)
                self.assertEqual(len(self.rejections), notifications + 1)
                self.assertEqual(self.rejections[-1], ("fixture", "actual", "max", ["low", "high"]))
        self.assertFalse((self.store.directory / "request-errors").exists())

    def test_auth_failure_does_not_change_effort_capabilities(self):
        self.mode = "auth"
        with self.assertRaises(RequestFailure):
            self.complete({"_umeko_reasoning_effort": "high"})
        self.assertFalse(self.rejections)

    def test_probe_retains_auth_status_before_error_body_classification(self):
        self.mode = "auth-effort"
        self.model.update(reasoningLevelsAuto=True)
        result = self.gateway.detect_reasoning("friendly")
        self.assertNotEqual(result["levels"]["state"], "known")
        self.assertFalse(result["levels"]["levels"])
        self.assertEqual(len(self.calls), 1)
        self.assertFalse((self.store.directory / "request-errors").exists())

    def test_catalog_shares_one_request_and_preserves_dict_interface(self):
        windows = fetch_model_windows(self.provider)
        self.assertIsInstance(windows, dict)
        self.assertEqual(windows.reasoning, {"actual": ["level3", "level1"]})
        self.assertEqual(len(self.calls), 1)
        row = self.gateway.models()[0]
        self.assertEqual(row["providerID"], "fixture")
        self.assertEqual(row["reasoningLevels"], ["low", "high"])
        self.assertEqual(row["reasoningFormat"], "openai")


if __name__ == "__main__":
    unittest.main()
