"""Provider discovery uses real HTTP catalogs and preserves editable settings."""
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from app.controller import Controller
from app.provider_models import fetch_model_windows
from app.storage import Store

ROOT = Path(__file__).resolve().parents[1]


class ModelWindowDiscoveryTests(unittest.TestCase):
    def test_http_catalog_protocols_and_missing_metadata(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                requests.append((self.path, self.headers))
                if self.path.endswith("after_id=page1"):
                    payload = {"data": [{"id": "page2", "limits": {"max_input_tokens": 48000}}]}
                elif self.path == "/v1/models":
                    payload = {"data": [{"id": "page1", "context_window": 64000}], "has_more": True, "last_id": "page1"}
                else:
                    payload = {"data": [{"id": "known", "top_provider": {"context_length": 96000}}, {"id": "unknown"}]}
                raw = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            values = {"api": "openai", "baseUrl": base, "key": "fixture", "proxy": {"mode": "direct"}}
            self.assertEqual(fetch_model_windows(values), {"known": 96000, "unknown": None})
            self.assertEqual(requests[0][0], "/models")
            self.assertEqual(requests[0][1]["Authorization"], "Bearer fixture")
            self.assertEqual(fetch_model_windows({**values, "api": "anthropic"}), {"page1": 64000, "page2": 48000})
            self.assertEqual(requests[1][1]["x-api-key"], "fixture")
            self.assertEqual(requests[1][1]["anthropic-version"], "2023-06-01")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_refresh_save_cap_restart_and_unknown_default(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"UMEKO_DATA_DIR": temp}):
            controller = Controller(ROOT)
            messages = []
            controller.toast.connect(messages.append)
            try:
                self.assertTrue(controller.saveProvider("", "Fixture", "openai", "http://127.0.0.1:1/v1", "fixture", json.dumps([
                    {"upstream": "known", "alias": "known", "compactionThreshold": 20000},
                    {"upstream": "unknown", "alias": "unknown"}])))
                provider = controller.store.data["providers"][0]
                identifier = provider["id"]

                def synchronous_job(name, fn):
                    controller._on_job_done(name, {"ok": True, "value": fn()})

                with patch("app.controller.fetch_model_windows", return_value={"known": 64000, "unknown": None}), patch.object(controller, "_job", side_effect=synchronous_job):
                    controller.refreshProviderModels(identifier)
                known, unknown = provider["models"]
                self.assertEqual((known["providerContextWindow"], known["contextWindow"], known["compactionThreshold"]), (64000, 64000, 20000))
                self.assertEqual(unknown["contextWindow"], 128000)
                bad = [{**row, "provider": identifier} for row in provider["models"]]
                bad[0].update(compactionThreshold=64001, contextWindow=128000, contextWindowAuto=False, providerContextWindow=999999)
                controller.saveMappings(json.dumps(bad))
                self.assertIn("64000", messages[-1])
                self.assertEqual(controller.gateway.provider(identifier)["models"][0]["compactionThreshold"], 20000)
                saved = Store(Path(temp)).data["providers"][0]["models"][0]
                self.assertEqual((saved["providerContextWindow"], saved["compactionThreshold"]), (64000, 20000))
                # An old name/alias-only editor keeps the server's metadata and threshold.
                self.assertTrue(controller.saveProvider(identifier, "Fixture", "openai", "http://127.0.0.1:1/v1", "", json.dumps([
                    {"upstream": "known", "alias": "renamed"}, {"upstream": "unknown", "alias": "unknown"}])))
                saved = controller.gateway.provider(identifier)["models"][0]
                self.assertEqual((saved["providerContextWindow"], saved["compactionThreshold"]), (64000, 20000))
            finally:
                controller.close()

    def test_refresh_failure_leaves_settings_and_reports_error(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"UMEKO_DATA_DIR": temp}):
            controller = Controller(ROOT)
            messages = []
            controller.toast.connect(messages.append)
            try:
                controller._on_job_done("model-windows:missing", {"ok": False, "value": "fixture catalog unavailable"})
                self.assertEqual(messages[-1], "fixture catalog unavailable")
            finally:
                controller.close()
