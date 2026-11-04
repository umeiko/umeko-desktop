"""Provider discovery uses real HTTP catalogs and preserves editable settings."""
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QGuiApplication

from app.controller import Controller
from app.provider_models import ModelWindows, fetch_model_windows
from app.storage import Store

ROOT = Path(__file__).resolve().parents[1]
APP = QGuiApplication.instance() or QGuiApplication([])


class ModelWindowDiscoveryTests(unittest.TestCase):
    def setUp(self):
        bundles = patch("app.provider_plugins.BundledProviders.sync", return_value=[])
        bundles.start()
        self.addCleanup(bundles.stop)

    def wait_for(self, predicate):
        if predicate():
            return
        loop = QEventLoop()
        poll, deadline = QTimer(), QTimer()
        deadline.setSingleShot(True)
        poll.timeout.connect(lambda: loop.quit() if predicate() else None)
        deadline.timeout.connect(loop.quit)
        poll.start(5)
        deadline.start(10000)
        loop.exec()
        poll.stop()
        deadline.stop()
        self.assertTrue(predicate(), "Provider model discovery did not finish")

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
        windows = ModelWindows()
        windows.update(known=64000, unknown=None)
        windows.reasoning.update(known=[], unknown=[])
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"UMEKO_DATA_DIR": temp}), \
                patch("app.controller_reasoning.fetch_model_windows", return_value=windows), \
                patch("app.gateway.Gateway.detect_reasoning_levels") as probe:
            controller = Controller(ROOT)
            messages = []
            controller.toast.connect(messages.append)
            try:
                self.assertTrue(controller.saveProvider("", "Fixture", "openai", "http://127.0.0.1:1/v1", "fixture", json.dumps([
                    {"upstream": "known", "alias": "known"},
                    {"upstream": "unknown", "alias": "unknown"}])))
                provider = controller.store.data["providers"][0]
                identifier = provider["id"]

                controller.refreshProviderModels(identifier)
                self.wait_for(lambda: not controller._reasoning.jobs
                              and provider["models"][0].get("providerContextWindow") == 64000)
                known, unknown = provider["models"]
                self.assertEqual((known["providerContextWindow"], known["contextWindow"]), (64000, 64000))
                self.assertEqual(unknown["contextWindow"], 128000)
                edited = [{**row, "provider": identifier} for row in provider["models"]]
                edited[0].update(contextWindow=128000, contextWindowAuto=False, providerContextWindow=999999)
                controller.saveMappings(json.dumps(edited))
                current = controller.gateway.provider(identifier)["models"][0]
                self.assertEqual((current["providerContextWindow"], current["contextWindow"]), (64000, 128000))
                saved = Store(Path(temp)).data["providers"][0]["models"][0]
                self.assertEqual((saved["providerContextWindow"], saved["contextWindow"]), (64000, 128000))
                # An old name/alias-only editor keeps server metadata and custom context.
                self.assertTrue(controller.saveProvider(identifier, "Fixture", "openai", "http://127.0.0.1:1/v1", "", json.dumps([
                    {"upstream": "known", "alias": "renamed"}, {"upstream": "unknown", "alias": "unknown"}])))
                saved = controller.gateway.provider(identifier)["models"][0]
                self.assertEqual((saved["providerContextWindow"], saved["contextWindow"]), (64000, 128000))
                probe.assert_not_called()
            finally:
                controller.close()

    def test_refresh_failure_leaves_settings_and_reports_error(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"UMEKO_DATA_DIR": temp}), \
                patch("app.controller_reasoning.fetch_model_windows", side_effect=ValueError("fixture catalog unavailable")), \
                patch("app.gateway.Gateway.detect_reasoning_levels", return_value={
                    "state": "failed", "source": "probe", "levels": [], "error": "fixture effort unavailable"}) as probe:
            store = Store()
            store.data["providers"] = [{"id": "fixture", "name": "Fixture", "api": "openai",
                "baseUrl": "http://127.0.0.1:1/v1", "key": "synthetic-local-key", "models": [{
                    "upstream": "known", "alias": "known", "contextWindowAuto": True,
                    "providerContextWindow": 64000, "reasoningLevels": ["low"], "reasoningLevelsAuto": True,
                    "reasoningDetection": {"state": "known", "source": "metadata", "levels": ["low"]}}]}]
            store.data.update(selectedProvider="fixture", selectedModel="known")
            store.save()
            controller = Controller(ROOT)
            try:
                controller.refreshProviderModels("fixture")
                self.wait_for(lambda: not controller._reasoning.jobs
                              and controller.gateway.provider("fixture")["models"][0]["reasoningDetection"]["state"] == "failed")
                model = controller.gateway.provider("fixture")["models"][0]
                self.assertEqual((model["providerContextWindow"], model["contextWindow"]), (64000, 64000))
                self.assertEqual(model["reasoningLevels"], ["low"])
                self.assertEqual(model["reasoningDetection"]["error"], "fixture effort unavailable")
                probe.assert_called_once_with("known", "fixture")
            finally:
                controller.close()
