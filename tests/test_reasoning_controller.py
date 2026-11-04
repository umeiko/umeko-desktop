"""Offscreen controller coverage using an isolated profile and loopback provider."""
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
from app.provider_models import ModelWindows
from app.request_diagnostics import RequestFailure
from app.storage import Store


ROOT = Path(__file__).resolve().parents[1]
APP = QGuiApplication.instance() or QGuiApplication([])


def manual(alias, levels):
    return {"upstream": alias + "-upstream", "alias": alias,
            "reasoningLevels": levels, "reasoningLevelsAuto": False}


def automatic(alias, levels=None):
    row = {"upstream": alias + "-upstream", "alias": alias}
    if levels is not None:
        row.update(reasoningLevels=list(levels), reasoningLevelsAuto=True,
                   reasoningDetection={"state": "known", "source": "metadata", "levels": list(levels)})
    return row


class ReasoningControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.environment = patch.dict(os.environ, {"UMEKO_DATA_DIR": self.temp.name})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.bundle = patch("app.provider_plugins.BundledProviders.sync", return_value=[])
        self.bundle.start()
        self.addCleanup(self.bundle.stop)
        self.controllers = []
        self.catalog = []
        self.gets = []
        self.posts = []
        self.catalog_entered = threading.Event()
        self.catalog_release = threading.Event()
        self.catalog_release.set()
        self.reject_chat = False
        test = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def reply(self, status, payload):
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                test.gets.append(self.path)
                test.catalog_entered.set()
                if not test.catalog_release.wait(10):
                    self.reply(503, {"error": {"message": "Fixture catalogue latch deadline"}})
                    return
                self.reply(200, {"data": list(test.catalog)})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                test.posts.append(body)
                if test.reject_chat:
                    self.reply(400, {"error": {"param": "reasoning_effort",
                        "message": "Unsupported value for reasoning_effort: 'xhigh'. Supported values are: 'low', 'high'."}})
                else:
                    self.reply(200, {"choices": [{"message": {"role": "assistant", "content": "fixture OK"},
                                                  "finish_reason": "stop"}]})

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http_thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.http_thread.start()
        self.addCleanup(self.close_fixture)

    def close_fixture(self):
        self.catalog_release.set()
        for controller in self.controllers:
            controller.close()
        self.http.shutdown()
        self.http.server_close()
        self.http_thread.join(timeout=2)
        APP.processEvents()

    def wait_for(self, predicate, message="controller event did not arrive"):
        if predicate():
            return
        loop = QEventLoop()
        poll = QTimer()
        deadline = QTimer()
        deadline.setSingleShot(True)
        poll.timeout.connect(lambda: loop.quit() if predicate() else None)
        deadline.timeout.connect(loop.quit)
        poll.start(5)
        deadline.start(10000)
        loop.exec()
        poll.stop()
        deadline.stop()
        self.assertTrue(predicate(), message)

    def controller(self, models=None, selected=None, seed=True):
        if seed:
            store = Store()
            if models is not None:
                store.data["providers"] = [{"id": "fixture", "name": "Fixture", "api": "openai",
                    "baseUrl": f"http://127.0.0.1:{self.http.server_port}/v1", "key": "synthetic-local-key",
                    "proxy": {"mode": "direct", "url": ""}, "models": models}]
                store.data.update(selectedProvider="fixture", selectedModel=selected or models[0]["alias"])
            store.save()
        controller = Controller(ROOT)
        # These tests operate controller state; never start a Pi subprocess.
        no_write = patch.object(controller, "_write_pi", return_value=None)
        no_write.start()
        self.addCleanup(no_write.stop)
        no_restart = patch.object(controller, "_restart_pi", return_value=None)
        no_restart.start()
        self.addCleanup(no_restart.stop)
        self.controllers.append(controller)
        return controller

    def model(self, controller, alias):
        return controller._reasoning.model("fixture", alias)

    def test_add_and_refresh_metadata_use_catalogue_without_probe(self):
        self.catalog = [{"id": "fresh-upstream", "reasoning": {"supported_efforts": ["high", "low"]}}]
        with patch("app.gateway.Gateway.detect_reasoning_levels") as probe:
            controller = self.controller()
            self.assertTrue(controller.saveProvider("", "Fixture", "openai",
                f"http://127.0.0.1:{self.http.server_port}/v1", "synthetic-local-key",
                json.dumps([{"upstream": "fresh-upstream", "alias": "fresh"}])))
            provider_id = controller.store.data["providers"][-1]["id"]
            self.wait_for(lambda: controller.modelReasoningSettings(provider_id, "fresh").get("state") == "known")
            self.assertEqual(controller.modelReasoningSettings(provider_id, "fresh")["reasoningLevels"], ["low", "high"])
            self.assertEqual(len(self.gets), 1)
            self.catalog = [{"id": "fresh-upstream", "reasoning": {"supported_efforts": ["xhigh", "medium"]}}]
            controller.refreshProviderModels(provider_id)
            self.wait_for(lambda: controller.modelReasoningSettings(provider_id, "fresh")["reasoningLevels"] == ["medium", "xhigh"])
            self.assertEqual(len(self.gets), 2)
            probe.assert_not_called()

    def test_manual_override_wins_an_inflight_result_and_survives_restart(self):
        self.catalog = [{"id": "fresh-upstream"}]
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def detect(*_):
            entered.set()
            if not release.wait(10):
                raise RuntimeError("Fixture probe latch deadline")
            return {"state": "known", "source": "probe", "levels": ["low", "high"]}
        with patch("app.gateway.Gateway.detect_reasoning_levels", side_effect=detect) as probe:
            controller = self.controller([automatic("fresh")])
            self.wait_for(entered.is_set)
            self.assertTrue(controller.setModelReasoningLevels("fixture", "fresh", ["medium", "xhigh"], False))
            release.set()
            self.wait_for(lambda: not controller._reasoning.jobs)
            settings = controller.modelReasoningSettings("fixture", "fresh")
            self.assertEqual(settings["state"], "manual")
            self.assertEqual(settings["reasoningLevels"], ["medium", "xhigh"])
            self.assertEqual(settings["reasoningDetection"]["levels"], ["low", "high"])
            probe.assert_called_once()
            controller.close()
            restarted = self.controller(seed=False)
            APP.processEvents()
            self.assertEqual(restarted.modelReasoningSettings("fixture", "fresh"), settings)
            self.assertEqual(probe.call_count, 1)

    def test_explicit_manual_redetect_refreshes_cache_then_auto_uses_it(self):
        self.catalog = [{"id": "fresh-upstream"}]
        with patch("app.gateway.Gateway.detect_reasoning_levels", return_value={
                "state": "known", "source": "probe", "levels": ["low", "high"]}) as probe:
            controller = self.controller([manual("fresh", ["medium", "xhigh"])])
            APP.processEvents()
            self.assertEqual(self.gets, [])
            self.assertTrue(controller.redetectReasoningLevels())
            self.wait_for(lambda: not controller._reasoning.jobs and
                          controller.modelReasoningSettings("fixture", "fresh")["reasoningDetection"]["state"] == "known")
            settings = controller.modelReasoningSettings("fixture", "fresh")
            self.assertEqual(settings["state"], "manual")
            self.assertEqual(settings["reasoningLevels"], ["medium", "xhigh"])
            self.assertEqual(settings["reasoningDetection"]["levels"], ["low", "high"])
            probe.assert_called_once_with("fresh", "fixture")
            self.assertTrue(controller.setModelReasoningLevels("fixture", "fresh", [], True))
            settings = controller.modelReasoningSettings("fixture", "fresh")
            self.assertEqual(settings["state"], "known")
            self.assertEqual(settings["reasoningLevels"], ["low", "high"])
            self.assertEqual(probe.call_count, 1)

    def test_connection_edit_invalidates_auto_cache_and_preserves_manual_levels(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        snapshots = []
        windows = ModelWindows()
        windows.update({"fresh-upstream": None, "custom-upstream": None})
        windows.reasoning.update({"fresh-upstream": ["medium", "xhigh"], "custom-upstream": ["low"]})
        def fetch(provider):
            snapshots.append((provider["api"], provider["baseUrl"]))
            entered.set()
            if not release.wait(10):
                raise RuntimeError("Fixture changed-connection latch deadline")
            return windows
        with patch("app.controller_reasoning.fetch_model_windows", side_effect=fetch), \
                patch("app.gateway.Gateway.detect_reasoning_levels") as probe:
            controller = self.controller([automatic("fresh", ["low", "high"]), manual("custom", ["custom-raw"])])
            APP.processEvents()
            self.assertFalse(entered.is_set())
            base_url = f"http://127.0.0.1:{self.http.server_port}/v2"
            self.assertTrue(controller.saveProvider("fixture", "Changed fixture", "anthropic", base_url, "",
                json.dumps([{"upstream": "fresh-upstream", "alias": "fresh"},
                            {"upstream": "custom-upstream", "alias": "custom"}])))
            automatic_row = self.model(controller, "fresh")
            self.assertEqual(automatic_row["reasoningLevels"], [])
            self.assertTrue(automatic_row["reasoningLevelsAuto"])
            self.assertIn(automatic_row["reasoningDetection"]["state"], ("unknown", "probing"))
            self.assertEqual(self.model(controller, "custom")["reasoningLevels"], ["custom-raw"])
            self.assertEqual(controller.modelReasoningSettings("fixture", "custom")["state"], "manual")
            self.wait_for(entered.is_set)
            self.assertEqual(automatic_row["reasoningDetection"]["state"], "probing")
            release.set()
            self.wait_for(lambda: automatic_row["reasoningDetection"]["state"] == "known")
            self.assertEqual(snapshots, [("anthropic", base_url)])
            self.assertEqual(automatic_row["reasoningLevels"], ["medium", "xhigh"])
            self.assertEqual(self.model(controller, "custom")["reasoningLevels"], ["custom-raw"])
            probe.assert_not_called()

    def test_plugin_declared_levels_keep_manual_choices_and_old_schema_unknown(self):
        controller = self.controller([manual("ready", ["low"])])
        record = {"id": "plugin-fixture", "models": [{"upstream": "plugin-manual", "alias": "plugin-custom",
                    "reasoningLevels": ["custom"], "reasoningLevelsAuto": False}]}
        rows = controller._provider_plugins._models(record, [
            {"id": "plugin-manual", "reasoningLevels": ["high", "low"]},
            {"id": "plugin-auto", "reasoningLevels": ["max", "low"]},
            {"id": "plugin-legacy", "reasoning": True},
        ])
        custom, auto, legacy = rows
        self.assertEqual(custom["alias"], "plugin-custom")
        self.assertFalse(custom["reasoningLevelsAuto"])
        self.assertEqual(custom["reasoningLevels"], ["custom"])
        self.assertEqual(custom["reasoningDetection"], {"state": "known", "source": "metadata", "levels": ["low", "high"]})
        self.assertTrue(auto["reasoningLevelsAuto"])
        self.assertEqual(auto["reasoningLevels"], ["low", "max"])
        self.assertEqual(auto["reasoningDetection"]["state"], "known")
        self.assertTrue(legacy["reasoningLevelsAuto"])
        self.assertEqual(legacy["reasoningLevels"], [])
        self.assertEqual(legacy["reasoningDetection"]["state"], "unknown")

    def test_unknown_activation_discovers_in_background_while_off_chat_works(self):
        self.catalog = [{"id": "fresh-upstream", "reasoning": {"supported_efforts": ["low", "high"]}}]
        self.catalog_release.clear()
        with patch("app.gateway.Gateway.detect_reasoning_levels") as probe:
            controller = self.controller([manual("ready", ["low"]), automatic("fresh")], selected="ready")
            APP.processEvents()
            self.assertEqual(self.gets, [])
            controller.selectModel("fixture", "fresh")
            self.wait_for(self.catalog_entered.is_set)
            self.assertEqual(controller.reasoningDetectionState, "probing")
            self.assertTrue(controller.setReasoningEffort("off"))
            completion = controller.gateway.complete("fresh", [{"role": "user", "content": "fixture"}],
                                                       provider_id="fixture")
            self.assertEqual(completion.text, "fixture OK")
            self.assertNotIn("reasoning_effort", self.posts[0])
            self.assertFalse(self.catalog_release.is_set())
            self.catalog_release.set()
            self.wait_for(lambda: controller.reasoningDetectionState == "known")
            self.assertEqual(self.model(controller, "fresh")["reasoningLevels"], ["low", "high"])
            probe.assert_not_called()

    def test_selection_and_session_open_clamp_and_control_accepts_raw_levels(self):
        controller = self.controller([manual("wide", ["low", "medium", "high", "xhigh"]),
                                      manual("narrow", ["low", "high"])])
        controller._view.id = "current"
        self.assertTrue(controller.setReasoningEffort("medium"))
        controller.selectModel("fixture", "narrow")
        self.assertEqual(controller.reasoningEffort, "low")
        self.assertEqual(controller.store.data["sessionMeta"]["current"]["reasoningEffort"], "low")
        controller.store.data["sessionMeta"]["history"] = {"reasoningEffort": "medium"}
        controller._sessions = [{"id": "history", "title": "Fixture history", "workspace": "", "file": "",
                                 "provider": "fixture", "model": "narrow", "messages": [], "history": []}]
        controller.openSession("history")
        self.assertEqual(controller.reasoningEffort, "low")
        self.assertEqual(Store().data["sessionMeta"]["history"]["reasoningEffort"], "low")
        controller.selectModel("fixture", "wide")
        for value in ("medium", "xhigh"):
            result = controller._umeko_control.execute({"operation": "sessions.reasoning", "arguments": {"value": value}})
            self.assertTrue(result["ok"], result)
            self.assertEqual(controller.reasoningEffort, value)
        result = controller._umeko_control.execute({"operation": "sessions.reasoning", "arguments": {"value": "max"}})
        self.assertFalse(result["ok"])
        self.assertEqual(controller.reasoningEffort, "xhigh")
        self.assertIn("medium", result["error"])

    def test_midchat_rejection_removes_level_refreshes_once_and_never_replays(self):
        with patch("app.gateway.Gateway.detect_reasoning_levels", return_value={
                "state": "known", "source": "probe", "levels": ["low", "high", "xhigh"]}) as probe:
            controller = self.controller([automatic("fresh", ["low", "high", "xhigh"])])
            APP.processEvents()
            self.assertTrue(controller.setReasoningEffort("xhigh"))
            self.reject_chat = True
            with self.assertRaises(RequestFailure) as caught:
                controller.gateway.complete("fresh", [{"role": "user", "content": "fixture chat"}],
                    provider_id="fixture", parameters={"reasoning_effort": "xhigh"})
            self.assertFalse(caught.exception.retryable)
            self.wait_for(lambda: self.model(controller, "fresh")["reasoningDetection"].get("state") == "known"
                          and "xhigh" in self.model(controller, "fresh")["reasoningDetection"].get("rejected", []))
            self.assertEqual(self.model(controller, "fresh")["reasoningLevels"], ["low", "high"])
            self.assertEqual(controller.reasoningEffort, "high")
            self.assertEqual(len(self.posts), 1)
            probe.assert_called_once_with("fresh", "fixture")
            saved = Store().data["providers"][0]["models"][0]
            self.assertEqual(saved["reasoningDetection"]["rejected"], ["xhigh"])
            self.assertEqual(saved["reasoningLevels"], ["low", "high"])


if __name__ == "__main__":
    unittest.main()
