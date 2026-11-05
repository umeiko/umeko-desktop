"""Provider discovery uses real HTTP catalogs and preserves editable settings."""
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from PySide6.QtGui import QGuiApplication

from app.controller import Controller
from app.provider_models import fetch_model_windows
from app.storage import Store

ROOT = Path(__file__).resolve().parents[1]


class ModelWindowDiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def wait_discovery(self, controller):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            self.app.processEvents()
            if not controller._reasoning_discovery.jobs:
                return
            time.sleep(.005)
        self.fail('offline catalog discovery deadline exceeded')

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
        result = {'levels': {'state': 'known', 'levels': [], 'source': 'probe', 'verified': True},
                  'format': {'state': 'known', 'format': 'openai', 'source': 'probe', 'verified': True}}
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"UMEKO_DATA_DIR": temp}), \
                patch('app.provider_plugins.BundledProviders.sync', return_value=[]), \
                patch('app.controller.LocalServer'), \
                patch('app.controller.Controller._restart_pi', new=lambda self: None), \
                patch('app.controller.Controller._write_pi', new=lambda self, payload, record=None: None), \
                patch('app.controller_reasoning.fetch_model_windows', return_value={'known': 64000, 'unknown': None}), \
                patch('app.gateway.Gateway.detect_reasoning', return_value=result):
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
                self.wait_discovery(controller)
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
            finally:
                controller.close()

    def test_refresh_failure_leaves_settings_and_reports_error(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"UMEKO_DATA_DIR": temp}), \
                patch('app.provider_plugins.BundledProviders.sync', return_value=[]), \
                patch('app.controller.LocalServer'), \
                patch('app.controller.Controller._restart_pi', new=lambda self: None), \
                patch('app.controller.Controller._write_pi', new=lambda self, payload, record=None: None), \
                patch('app.controller_reasoning.fetch_model_windows', side_effect=ValueError('fixture catalog unavailable')) as catalog, \
                patch('app.gateway.Gateway.detect_reasoning', side_effect=ValueError('fixture probe unavailable')) as probe:
            controller = Controller(ROOT)
            messages = []
            controller.toast.connect(messages.append)
            try:
                known = {'state': 'known', 'verified': True, 'source': 'probe'}
                self.assertTrue(controller.saveProvider('', 'Fixture', 'openai', 'https://fixture.invalid/v1', 'fixture', json.dumps([
                    {'upstream': 'model', 'alias': 'model', 'contextWindow': 64000, 'contextWindowAuto': False,
                     'reasoningLevels': ['vendor-level'], 'reasoningLevelsAuto': True,
                     'reasoningDetection': {**known, 'levels': ['vendor-level']},
                     'reasoningFormat': 'qwen', 'reasoningFormatAuto': True,
                     'reasoningFormatDetection': {**known, 'format': 'qwen'}}])))
                provider = controller.store.data['providers'][0]
                controller.refreshProviderModels(provider['id'])
                self.wait_discovery(controller)
                row = provider['models'][0]
                self.assertTrue(catalog.called)
                self.assertTrue(probe.called)
                self.assertEqual(row['contextWindow'], 64000)
                self.assertEqual(row['reasoningLevels'], ['vendor-level'])
                self.assertEqual(row['reasoningFormat'], 'qwen')
                self.assertEqual(row['reasoningDetection']['state'], 'failed')
                self.assertEqual(row['reasoningFormatDetection']['state'], 'failed')
                self.assertEqual(row['reasoningDetection']['error'], '[redacted] probe unavailable')
            finally:
                controller.close()
