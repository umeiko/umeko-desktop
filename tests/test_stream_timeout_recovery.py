"""Stream idle timeout, auto-recovery classification, model group failover, and provider settings."""
from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import app.gateway as gateway_module
from app.gateway import (
    DEFAULT_GROUP_FIRST_PACKET_TIMEOUT_MS,
    DEFAULT_REQUEST_MAX_RETRIES,
    DEFAULT_STREAM_IDLE_TIMEOUT_MS,
    DEFAULT_STREAM_MAX_RETRIES,
    Gateway,
    LocalServer,
    STREAM_FIRST_EVENT_TIMEOUT_ERROR,
    STREAM_HEADER_TIMEOUT_ERROR,
    STREAM_IDLE_TIMEOUT_ERROR,
    STREAM_INCOMPLETE_ERROR,
    STREAM_INTERRUPTED_ERROR,
    STREAM_TIMEOUT_ERROR,
    normalize_request_max_retries,
    normalize_stream_idle_timeout_ms,
    normalize_stream_max_retries,
    provider_request_max_retries,
    provider_stream_idle_timeout_seconds,
    provider_stream_max_retries,
    validate_request_max_retries,
    validate_stream_idle_timeout_seconds,
    validate_stream_max_retries,
)
from app.integration import UnconfiguredAdapter
from app.model_groups import GROUP_MODEL
from app.network_retry import transient_failure
from app.provider_errors import diagnostic_notice, is_staged_continue_failure
from app.request_diagnostics import RequestFailure
from app.storage import Store
from umeko_provider_sdk.network import SplitTimeoutHTTPHandler, SplitTimeoutHTTPSHandler


class StreamTimeoutConfigTests(unittest.TestCase):
    def test_defaults_and_validation(self):
        self.assertEqual(DEFAULT_STREAM_IDLE_TIMEOUT_MS, 300_000)
        self.assertEqual(normalize_stream_idle_timeout_ms(None), 300_000)
        self.assertEqual(normalize_stream_idle_timeout_ms(""), 300_000)
        self.assertEqual(normalize_stream_idle_timeout_ms(True), 300_000)
        self.assertEqual(normalize_stream_idle_timeout_ms(500), 300_000)
        self.assertEqual(normalize_stream_idle_timeout_ms(9_999_999), 300_000)
        self.assertEqual(normalize_stream_idle_timeout_ms(600_000), 600_000)
        self.assertEqual(provider_stream_idle_timeout_seconds({}), 300.0)
        self.assertEqual(provider_stream_idle_timeout_seconds({"streamIdleTimeoutMs": 450_000}), 450.0)

        self.assertIsNone(validate_stream_idle_timeout_seconds(""))
        self.assertIsNone(validate_stream_idle_timeout_seconds("   "))
        self.assertEqual(validate_stream_idle_timeout_seconds("10"), 10_000)
        self.assertEqual(validate_stream_idle_timeout_seconds("300"), 300_000)
        self.assertEqual(validate_stream_idle_timeout_seconds("1800"), 1_800_000)
        for bad in ("0", "9", "1801", "-5", "abc", "30.5"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_stream_idle_timeout_seconds(bad)

        self.assertEqual(DEFAULT_STREAM_MAX_RETRIES, 5)
        self.assertEqual(DEFAULT_REQUEST_MAX_RETRIES, 2)
        self.assertEqual(normalize_stream_max_retries(None), 5)
        self.assertEqual(normalize_stream_max_retries(0), 0)
        self.assertEqual(normalize_stream_max_retries(100), 100)
        self.assertEqual(normalize_stream_max_retries(101), 5)
        self.assertEqual(provider_stream_max_retries({"streamMaxRetries": 3}), 3)
        self.assertIsNone(validate_stream_max_retries(""))
        self.assertEqual(validate_stream_max_retries("0"), 0)
        self.assertEqual(validate_stream_max_retries("100"), 100)
        for bad in ("-1", "101", "abc", "1.5"):
            with self.subTest(stream_retry_bad=bad), self.assertRaises(ValueError):
                validate_stream_max_retries(bad)

        self.assertEqual(normalize_request_max_retries(None), 2)
        self.assertEqual(normalize_request_max_retries(0), 0)
        self.assertEqual(normalize_request_max_retries(100), 100)
        self.assertEqual(normalize_request_max_retries(101), 2)
        self.assertEqual(provider_request_max_retries({"requestMaxRetries": 4}), 4)
        self.assertIsNone(validate_request_max_retries(""))
        self.assertEqual(validate_request_max_retries("0"), 0)
        self.assertEqual(validate_request_max_retries("4"), 4)
        for bad in ("-1", "101", "abc", "2.5"):
            with self.subTest(request_retry_bad=bad), self.assertRaises(ValueError):
                validate_request_max_retries(bad)

    def test_transient_and_diagnostic_notice_messages(self):
        for err in (
            TimeoutError(STREAM_TIMEOUT_ERROR),
            TimeoutError(STREAM_HEADER_TIMEOUT_ERROR),
            TimeoutError(STREAM_FIRST_EVENT_TIMEOUT_ERROR),
            TimeoutError(STREAM_IDLE_TIMEOUT_ERROR),
            ConnectionError(STREAM_INTERRUPTED_ERROR),
            ConnectionError(STREAM_INCOMPLETE_ERROR),
        ):
            self.assertTrue(transient_failure(err), str(err))
        self.assertTrue(transient_failure("request failed", [{"exception": "timed out", "response": {}}]))
        self.assertTrue(transient_failure(ValueError("Upstream stream ended before completion")))

        report = " [Umeko:12345678-1234-1234-1234-123456789abc]"
        for msg in (
            STREAM_TIMEOUT_ERROR,
            STREAM_HEADER_TIMEOUT_ERROR,
            STREAM_FIRST_EVENT_TIMEOUT_ERROR,
            STREAM_IDLE_TIMEOUT_ERROR,
            STREAM_INTERRUPTED_ERROR,
            STREAM_INCOMPLETE_ERROR,
        ):
            self.assertEqual(diagnostic_notice("Network error: stream interrupted. " + msg + report), msg)
            self.assertTrue(is_staged_continue_failure(msg + report))
        self.assertFalse(is_staged_continue_failure("供应商返回 HTTP 401：Unauthorized" + report))
        self.assertFalse(is_staged_continue_failure("供应商返回 HTTP 429：insufficient_quota" + report))
        self.assertTrue(is_staged_continue_failure("供应商返回 HTTP 504：Server process timeout（提示：供应商服务端处理超时，请稍后重试）" + report))
        self.assertEqual(
            diagnostic_notice("供应商返回 HTTP 504：Server process timeout（提示：供应商服务端处理超时，请稍后重试）" + report),
            "供应商返回 HTTP 504：Server process timeout（提示：供应商服务端处理超时，请稍后重试）",
        )
        self.assertEqual(
            diagnostic_notice("无法连接供应商：Connection refused" + report),
            "无法连接供应商：Connection refused",
        )
        self.assertEqual(
            diagnostic_notice(f"模型组中的可用模型均请求失败（最后一次失败：{STREAM_TIMEOUT_ERROR}）" + report),
            f"模型组中的可用模型均请求失败（最后一次失败：{STREAM_TIMEOUT_ERROR}）",
        )


class StreamTimeoutGatewayTests(unittest.TestCase):
    def setUp(self):
        self.mode = "ok"
        self.delay = 0.0
        self.calls = []
        fixture = self

        class Upstream(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                model = body.get("model", "")
                fixture.calls.append(model)
                mode = fixture.mode.get(model, "ok") if isinstance(fixture.mode, dict) else fixture.mode
                delay = fixture.delay.get(model, 0.0) if isinstance(fixture.delay, dict) else fixture.delay

                if mode == "504":
                    raw = json.dumps({"error": {"message": "Server process timeout", "code": "504"}}).encode()
                    self.send_response(504)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(raw)
                    return

                if mode == "non_stream_slow":
                    time.sleep(delay)
                    raw = json.dumps({
                        "choices": [{"index": 0, "message": {"role": "assistant", "content": "non-stream ok"}, "finish_reason": "stop"}]
                    }).encode()
                    try:
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(raw)))
                        self.send_header("Connection", "close")
                        self.end_headers()
                        self.wfile.write(raw)
                    except OSError:
                        pass
                    return

                if mode == "stream_preamble_then_pause":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    try:
                        self.wfile.write(b'data: {"choices":[{"index":0,"delta":{"role":"assistant","content":"working..."}}]}\n\n')
                        self.wfile.flush()
                        time.sleep(delay)
                        self.wfile.write(b'data: {"choices":[{"index":0,"delta":{"content":"done"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
                        self.wfile.flush()
                    except OSError:
                        pass
                    return

                if mode == "headers_then_pause":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.flush()
                    time.sleep(delay)
                    try:
                        self.wfile.write(b'data: {"choices":[{"index":0,"delta":{"role":"assistant","content":"late"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
                        self.wfile.flush()
                    except OSError:
                        pass
                    return

                if mode == "heartbeat_then_complete":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    try:
                        for _ in range(8):
                            time.sleep(delay / 8.0)
                            self.wfile.write(b": keep-alive\n\n")
                            self.wfile.flush()
                        self.wfile.write(b'data: {"choices":[{"index":0,"delta":{"role":"assistant","content":"heartbeat ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
                        self.wfile.flush()
                    except OSError:
                        pass
                    return

                if mode == "heartbeat_then_truncate":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    try:
                        for _ in range(5):
                            time.sleep(0.08)
                            self.wfile.write(b": keep-alive\n\n")
                            self.wfile.flush()
                    except OSError:
                        pass
                    return

                if mode == "503_always":
                    raw = json.dumps({"error": {"message": "temporarily unavailable"}}).encode()
                    self.send_response(503)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Retry-After", "0")
                    self.send_header("Content-Length", str(len(raw)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(raw)
                    return

                if mode == "stream_drop":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    try:
                        self.wfile.write(b'data: {"choices":[{"index":0,"delta":{"role":"assistant","content":"partial"}}]}\n\n')
                        self.wfile.flush()
                        self.connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    return

                if mode == "quota":
                    raw = json.dumps({"error": {"code": "insufficient_quota", "message": "No credits"}}).encode()
                    self.send_response(429)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(raw)
                    return

                raw = b'data: {"choices":[{"index":0,"delta":{"role":"assistant","content":"ok:' + model.encode() + b'"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(raw)

        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        self.thread = threading.Thread(target=self.upstream.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.upstream.server_close)
        self.addCleanup(self.upstream.shutdown)

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = f"http://127.0.0.1:{self.upstream.server_port}/v1"
        self.providers = [
            {
                "id": "primary", "name": "Primary", "api": "openai", "key": "primary-key",
                "baseUrl": base, "proxy": {"mode": "direct", "url": ""},
                "streamIdleTimeoutMs": 600,
                "models": [{"alias": "primary", "upstream": "primary"}],
            },
            {
                "id": "backup", "name": "Backup", "api": "openai", "key": "backup-key",
                "baseUrl": base, "proxy": {"mode": "direct", "url": ""},
                "streamIdleTimeoutMs": 600,
                "models": [{"alias": "backup", "upstream": "backup"}],
            },
        ]
        self.store = SimpleNamespace(
            directory=Path(self.temp.name),
            data={
                "providers": self.providers,
                "modelGroup": {
                    "enabled": True,
                    "members": [
                        {"provider": "primary", "model": "primary", "effort": "off"},
                        {"provider": "backup", "model": "backup", "effort": "off"},
                    ],
                },
            },
        )
        self.gateway = Gateway(self.store, UnconfiguredAdapter())
        self.server = LocalServer(self.gateway, 0, "test-token", private=True)
        self.addCleanup(self.server.close)

    def _post(self, model, stream=True, **metadata):
        req = Request(
            f"http://127.0.0.1:{self.server.port}/v1/chat/completions",
            headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
            data=json.dumps({"model": model, "stream": stream, "messages": [{"role": "user", "content": "hi"}], **metadata}).encode(),
        )
        return urlopen(req, timeout=10)

    def test_idle_timeout_mid_stream_and_recovery_with_higher_provider_timeout(self):
        self.mode = "stream_preamble_then_pause"
        self.delay = 1.2
        with patch.object(gateway_module, "MIN_STREAM_IDLE_TIMEOUT_MS", 100):
            with self._post("primary", stream=True) as resp:
                body = resp.read().decode("utf-8")
            self.assertIn("umeko_gateway_timeout", body)
            self.assertIn(STREAM_IDLE_TIMEOUT_ERROR, body)
            self.assertIn('"retryable": true', body)

            # Raising per-provider streamIdleTimeoutMs lets the same pause succeed.
            self.providers[0]["streamIdleTimeoutMs"] = 3000
            with self._post("primary", stream=True) as resp:
                body = resp.read().decode("utf-8")
            self.assertIn("done", body)
            self.assertNotIn("umeko_gateway_timeout", body)

    def test_four_diagnostic_phases_and_sse_heartbeat_handling(self):
        def read_latest_report():
            files = sorted((Path(self.temp.name) / "request-errors").glob("*.json"), key=lambda p: p.stat().st_mtime)
            return json.loads(files[-1].read_text(encoding="utf-8"))

        with patch.object(gateway_module, "MIN_STREAM_IDLE_TIMEOUT_MS", 100):
            # Phase 1: waiting_headers (no HTTP headers before timeout)
            self.mode = "non_stream_slow"
            self.delay = 1.1
            with self.assertRaises(HTTPError) as caught:
                self._post("primary", stream=True)
            payload = json.loads(caught.exception.read().decode("utf-8"))
            caught.exception.close()
            self.assertEqual(payload["error"]["code"], "umeko_stream_interrupted")
            rep = read_latest_report()
            diag = rep["streamDiagnostics"]
            self.assertEqual(diag["phase"], "waiting_headers")
            self.assertIsNone(diag["firstEventMs"])
            self.assertFalse(diag["completedNormally"])
            self.assertGreaterEqual(diag["totalMs"], 400)
            self.assertGreaterEqual(diag["lastDataToErrorMs"], 400)

            # Phase 2: waiting_first_sse (HTTP 200 SSE headers received, paused before first event)
            self.mode = "headers_then_pause"
            self.delay = 1.1
            with self.assertRaises(HTTPError) as caught:
                self._post("primary", stream=True)
            payload = json.loads(caught.exception.read().decode("utf-8"))
            caught.exception.close()
            self.assertIn(STREAM_FIRST_EVENT_TIMEOUT_ERROR, payload["error"]["message"])
            self.assertEqual(payload["error"]["code"], "umeko_gateway_timeout")
            rep = read_latest_report()
            diag = rep["streamDiagnostics"]
            self.assertEqual(diag["phase"], "waiting_first_sse")
            self.assertIsNotNone(diag["headersReceivedAt"])
            self.assertIsNone(diag["firstEventMs"])
            self.assertFalse(diag["completedNormally"])
            self.assertGreaterEqual(diag["lastDataToErrorMs"], 400)

            # Phase 3: stream_idle (first SSE event emitted, then paused)
            self.mode = "stream_preamble_then_pause"
            self.delay = 1.1
            with self._post("primary", stream=True) as resp:
                body = resp.read().decode("utf-8")
            self.assertIn(STREAM_IDLE_TIMEOUT_ERROR, body)
            rep = read_latest_report()
            diag = rep["streamDiagnostics"]
            self.assertEqual(diag["phase"], "stream_idle")
            self.assertIsNotNone(diag["firstEventMs"])
            self.assertIsNotNone(diag["firstEventAt"])
            self.assertFalse(diag["completedNormally"])
            self.assertGreaterEqual(diag["lastDataToErrorMs"], 400)
            self.assertGreaterEqual(diag["totalMs"], diag["lastDataToErrorMs"])

            # Heartbeat comments reset the socket idle timer across a duration longer than streamIdleTimeoutMs!
            self.mode = "heartbeat_then_complete"
            self.delay = 1.2
            with self._post("primary", stream=True) as resp:
                body = resp.read().decode("utf-8")
            self.assertIn("heartbeat ok", body)

            # Phase 4: incomplete_stream (heartbeats arrive continuously, then stream closes without finish_reason)
            self.mode = "heartbeat_then_truncate"
            with self.assertRaises(HTTPError) as caught:
                self._post("primary", stream=True)
            payload = json.loads(caught.exception.read().decode("utf-8"))
            caught.exception.close()
            self.assertIn(STREAM_INCOMPLETE_ERROR, payload["error"]["message"])
            rep = read_latest_report()
            diag = rep["streamDiagnostics"]
            self.assertEqual(diag["phase"], "incomplete_stream")
            self.assertGreaterEqual(diag["heartbeatCount"], 5)
            self.assertFalse(diag["completedNormally"])
            self.assertIsNotNone(diag["totalMs"])

    def test_provider_request_max_retries_is_applied(self):
        self.mode = "503_always"
        self.providers[0]["requestMaxRetries"] = 0
        self.calls.clear()
        with self.assertRaises(HTTPError) as caught:
            self._post("primary", stream=True)
        caught.exception.close()
        self.assertEqual(len(self.calls), 1)

        self.providers[0]["requestMaxRetries"] = 3
        self.calls.clear()
        with self.assertRaises(HTTPError) as caught:
            self._post("primary", stream=True)
        caught.exception.close()
        self.assertEqual(len(self.calls), 4)
        self.calls.clear()
        with self.assertRaises(HTTPError) as caught:
            self._post("primary", stream=True, _umeko_gateway_continuation=True)
        caught.exception.close()
        self.assertEqual(len(self.calls), 1)

    def test_unwritable_diagnostics_keep_gateway_timeout_retryable(self):
        self.gateway.diagnostics.directory.write_text("not a directory", encoding="utf-8")
        self.mode = "non_stream_slow"
        self.delay = 1.2
        with patch.object(gateway_module, "MIN_STREAM_IDLE_TIMEOUT_MS", 100):
            with self.assertRaises(HTTPError) as caught:
                self._post("primary", stream=True)
            with caught.exception as response:
                self.assertEqual(response.code, 503)
                error = json.load(response)["error"]
            self.assertTrue(error["retryable"])
            self.assertIn(STREAM_HEADER_TIMEOUT_ERROR, error["message"])
            self.assertNotIn("[Umeko:", error["message"])

            self.mode = "ok"
            self.delay = 0.0
            with self._post("primary", stream=True) as response:
                self.assertIn("ok:primary", response.read().decode("utf-8"))

    def test_non_stream_timeout_and_504_and_mid_stream_drop_are_retryable(self):
        with patch.object(gateway_module, "MIN_STREAM_IDLE_TIMEOUT_MS", 100):
            self.mode = "non_stream_slow"
            self.delay = 1.2
            with self.assertRaises(HTTPError) as caught:
                self._post("primary", stream=True)
            self.assertEqual(caught.exception.code, 503)
            payload = json.loads(caught.exception.read().decode("utf-8"))
            caught.exception.close()
            self.assertTrue(payload["error"]["retryable"])
            self.assertIn(STREAM_HEADER_TIMEOUT_ERROR, payload["error"]["message"])

            self.mode = "504"
            with self.assertRaises(HTTPError) as caught:
                self._post("primary", stream=True)
            self.assertEqual(caught.exception.code, 503)
            payload = json.loads(caught.exception.read().decode("utf-8"))
            caught.exception.close()
            self.assertTrue(payload["error"]["retryable"])
            self.assertIn("供应商服务端处理超时", payload["error"]["message"])

            self.mode = "stream_drop"
            with self._post("primary", stream=True) as resp:
                body = resp.read().decode("utf-8")
            self.assertIn("umeko_stream_interrupted", body)
            self.assertIn(STREAM_INCOMPLETE_ERROR, body)

    def test_model_group_failover_and_all_transient_retryable(self):
        with patch.object(gateway_module, "MIN_STREAM_IDLE_TIMEOUT_MS", 100):
            # Primary times out before headers, backup succeeds immediately.
            self.mode = {"primary": "non_stream_slow", "backup": "ok"}
            self.delay = {"primary": 1.2, "backup": 0.0}
            with self._post(GROUP_MODEL, stream=True) as resp:
                body = resp.read().decode("utf-8")
            self.assertIn("ok:backup", body)
            self.assertEqual(self.calls, ["primary", "backup"])

            # When all members fail transiently, LocalServer returns 503 so Pi retries.
            self.calls.clear()
            self.gateway.reset_model_group()
            self.mode = {"primary": "504", "backup": "504"}
            with self.assertRaises(HTTPError) as caught:
                self._post(GROUP_MODEL, stream=True)
            self.assertEqual(caught.exception.code, 503)
            payload = json.loads(caught.exception.read().decode("utf-8"))
            caught.exception.close()
            self.assertTrue(payload["error"]["retryable"])
            self.assertIn("模型组中的可用模型均请求失败", payload["error"]["message"])
            self.assertIn("HTTP 504", payload["error"]["message"])

            # When all members fail non-retryably (quota), LocalServer returns 400 (no pointless retry).
            self.calls.clear()
            self.gateway.reset_model_group()
            self.mode = {"primary": "quota", "backup": "quota"}
            with self.assertRaises(HTTPError) as caught:
                self._post(GROUP_MODEL, stream=True)
            self.assertEqual(caught.exception.code, 400)
            payload = json.loads(caught.exception.read().decode("utf-8"))
            caught.exception.close()
            self.assertFalse(payload["error"]["retryable"])

    def test_model_group_separates_first_packet_failover_from_mid_stream_read_timeout(self):
        observed = []

        def fake_open(opener, request, *, timeout=20, **kwargs):
            http_handlers = [h for h in opener.handlers if isinstance(h, (SplitTimeoutHTTPHandler, SplitTimeoutHTTPSHandler))]
            self.assertEqual(len(http_handlers), 2)
            self.assertLessEqual(http_handlers[0]._connect_timeout, 15.0)
            observed.append(timeout)
            raise TimeoutError("timed out")

        self.providers[0]["streamIdleTimeoutMs"] = 600_000
        self.providers[1].pop("streamIdleTimeoutMs", None)
        with patch.object(gateway_module, "compatible_open", side_effect=fake_open):
            with self.assertRaises(RequestFailure) as caught:
                list(self.gateway.group_events([{"role": "user", "content": "hi"}]))
        # First candidate has a backup -> uses separate first-packet failover timeout (45s).
        # Last candidate has no backup -> uses full streamIdleTimeoutMs (300s).
        self.assertEqual(observed, [DEFAULT_GROUP_FIRST_PACKET_TIMEOUT_MS / 1000.0, 300.0])
        self.assertTrue(caught.exception.retryable)

        # Once the first SSE event arrives on primary, mid-stream read timeout switches to full streamIdleTimeoutMs (not first-packet timeout!).
        with patch.object(gateway_module, "MIN_STREAM_IDLE_TIMEOUT_MS", 100), \
             patch.object(gateway_module, "DEFAULT_GROUP_FIRST_PACKET_TIMEOUT_MS", 400):
            self.gateway.reset_model_group()
            self.providers[0]["streamIdleTimeoutMs"] = 2500
            self.mode = {"primary": "stream_preamble_then_pause", "backup": "ok"}
            self.delay = {"primary": 0.9, "backup": 0.0}
            with self._post(GROUP_MODEL, stream=True) as resp:
                body = resp.read().decode("utf-8")
            self.assertIn("done", body)
            self.assertNotIn("ok:backup", body)


class ProviderTimeoutPreferenceTests(unittest.TestCase):
    def test_network_timeout_and_retries_persist_atomically_and_expose_umeko_control(self):
        from app.controller import Controller

        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"UMEKO_DATA_DIR": temp}):
            backend = Controller(root)
            try:
                self.assertTrue(
                    backend.saveProvider(
                        "", "Fixture", "openai", "http://127.0.0.1:1/v1", "fixture-key",
                        json.dumps([{"upstream": "fixture", "alias": "fixture"}]),
                    )
                )
                provider = backend.store.data["providers"][0]
                identifier = provider["id"]
                self.assertTrue(backend.setProviderNetworkConfig(identifier, "direct", "", "", "600", "8", "4"))
                self.assertEqual(provider["streamIdleTimeoutMs"], 600_000)
                self.assertEqual(provider["streamMaxRetries"], 8)
                self.assertEqual(provider["requestMaxRetries"], 4)
                saved = Store(Path(temp)).data["providers"][0]
                self.assertEqual(saved["streamIdleTimeoutMs"], 600_000)
                self.assertEqual(saved["streamMaxRetries"], 8)
                self.assertEqual(saved["requestMaxRetries"], 4)

                # Legacy 4-arg setProviderNetwork preserves existing timeout and retry overrides.
                self.assertTrue(backend.setProviderNetwork(identifier, "system", "", ""))
                self.assertEqual(provider["streamIdleTimeoutMs"], 600_000)
                self.assertEqual(provider["streamMaxRetries"], 8)
                self.assertEqual(provider["requestMaxRetries"], 4)

                # Invalid retry fails atomically without modifying proxy or saved values.
                previous_proxy = provider["proxy"].copy()
                self.assertFalse(backend.setProviderNetworkConfig(identifier, "direct", "", "", "400", "101", "2"))
                self.assertEqual(provider["proxy"], previous_proxy)
                self.assertEqual(provider["streamIdleTimeoutMs"], 600_000)
                self.assertEqual(provider["streamMaxRetries"], 8)

                # umeko_desktop providers.timeouts operation updates all three fields cleanly.
                result = backend._umeko_control.execute({
                    "operation": "providers.timeouts",
                    "arguments": {
                        "id": identifier,
                        "streamIdleTimeoutSeconds": "450",
                        "streamMaxRetries": "3",
                        "requestMaxRetries": "1",
                    },
                })
                self.assertTrue(result["ok"], result)
                self.assertEqual(provider["streamIdleTimeoutMs"], 450_000)
                self.assertEqual(provider["streamMaxRetries"], 3)
                self.assertEqual(provider["requestMaxRetries"], 1)

                # Blank resets to defaults by removing custom overrides.
                self.assertTrue(backend.setProviderNetworkConfig(identifier, "direct", "", "", "", "", ""))
                for key in ("streamIdleTimeoutMs", "streamMaxRetries", "requestMaxRetries"):
                    self.assertNotIn(key, provider)
                    self.assertNotIn(key, Store(Path(temp)).data["providers"][0])
            finally:
                backend.close()


if __name__ == "__main__":
    unittest.main()
