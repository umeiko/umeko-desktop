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
    DEFAULT_STREAM_IDLE_TIMEOUT_MS,
    Gateway,
    LocalServer,
    STREAM_INTERRUPTED_ERROR,
    STREAM_TIMEOUT_ERROR,
    normalize_stream_idle_timeout_ms,
    provider_stream_idle_timeout_seconds,
    validate_stream_idle_timeout_seconds,
)
from app.integration import UnconfiguredAdapter
from app.model_groups import GROUP_MODEL
from app.network_retry import transient_failure
from app.provider_errors import diagnostic_notice
from app.request_diagnostics import RequestFailure
from app.storage import Store


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

    def test_transient_and_diagnostic_notice_messages(self):
        self.assertTrue(transient_failure(TimeoutError(STREAM_TIMEOUT_ERROR)))
        self.assertTrue(transient_failure(ConnectionError(STREAM_INTERRUPTED_ERROR)))
        self.assertTrue(transient_failure("request failed", [{"exception": "timed out", "response": {}}]))
        self.assertTrue(transient_failure(ValueError("Upstream stream ended before completion")))

        report = " [Umeko:12345678-1234-1234-1234-123456789abc]"
        self.assertEqual(
            diagnostic_notice("Network error: stream interrupted. " + STREAM_TIMEOUT_ERROR + report),
            STREAM_TIMEOUT_ERROR,
        )
        self.assertEqual(
            diagnostic_notice("Network error: stream interrupted. " + STREAM_INTERRUPTED_ERROR + report),
            STREAM_INTERRUPTED_ERROR,
        )
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

    def _post(self, model, stream=True):
        req = Request(
            f"http://127.0.0.1:{self.server.port}/v1/chat/completions",
            headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
            data=json.dumps({"model": model, "stream": stream, "messages": [{"role": "user", "content": "hi"}]}).encode(),
        )
        return urlopen(req, timeout=10)

    def test_idle_timeout_mid_stream_and_recovery_with_higher_provider_timeout(self):
        self.mode = "stream_preamble_then_pause"
        self.delay = 1.2
        with patch.object(gateway_module, "MIN_STREAM_IDLE_TIMEOUT_MS", 100):
            with self._post("primary", stream=True) as resp:
                body = resp.read().decode("utf-8")
            self.assertIn("umeko_stream_interrupted", body)
            self.assertIn(STREAM_TIMEOUT_ERROR, body)
            self.assertIn('"retryable": true', body)

            # Raising per-provider streamIdleTimeoutMs lets the same pause succeed.
            self.providers[0]["streamIdleTimeoutMs"] = 3000
            with self._post("primary", stream=True) as resp:
                body = resp.read().decode("utf-8")
            self.assertIn("done", body)
            self.assertNotIn("umeko_stream_interrupted", body)

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
            self.assertIn(STREAM_TIMEOUT_ERROR, payload["error"]["message"])

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
            self.assertIn(STREAM_INTERRUPTED_ERROR, body)

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

    def test_model_group_honors_provider_timeout_without_45s_cap(self):
        observed = []

        def fake_open(opener, request, *, timeout=20, **kwargs):
            observed.append(timeout)
            raise TimeoutError("timed out")

        self.providers[0]["streamIdleTimeoutMs"] = 600_000
        self.providers[1].pop("streamIdleTimeoutMs", None)
        with patch.object(gateway_module, "compatible_open", side_effect=fake_open):
            with self.assertRaises(RequestFailure) as caught:
                list(self.gateway.group_events([{"role": "user", "content": "hi"}]))
        self.assertEqual(observed, [600.0, 300.0])
        self.assertTrue(caught.exception.retryable)


class ProviderTimeoutPreferenceTests(unittest.TestCase):
    def test_network_timeout_persists_validates_atomically_and_preserves_legacy_slot(self):
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
                self.assertTrue(backend.setProviderNetworkWithTimeout(identifier, "direct", "", "", "600"))
                self.assertEqual(provider["streamIdleTimeoutMs"], 600_000)
                self.assertEqual(Store(Path(temp)).data["providers"][0]["streamIdleTimeoutMs"], 600_000)

                # Legacy 4-arg setProviderNetwork preserves existing streamIdleTimeoutMs.
                self.assertTrue(backend.setProviderNetwork(identifier, "system", "", ""))
                self.assertEqual(provider["streamIdleTimeoutMs"], 600_000)

                # Invalid timeout fails atomically without modifying proxy or timeout.
                previous_proxy = provider["proxy"].copy()
                self.assertFalse(backend.setProviderNetworkWithTimeout(identifier, "direct", "", "", "5"))
                self.assertEqual(provider["proxy"], previous_proxy)
                self.assertEqual(provider["streamIdleTimeoutMs"], 600_000)

                # Blank resets to default by removing the custom override.
                self.assertTrue(backend.setProviderNetworkWithTimeout(identifier, "direct", "", "", ""))
                self.assertNotIn("streamIdleTimeoutMs", provider)
                self.assertNotIn("streamIdleTimeoutMs", Store(Path(temp)).data["providers"][0])
            finally:
                backend.close()


if __name__ == "__main__":
    unittest.main()
