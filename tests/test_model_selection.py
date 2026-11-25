"""Selected models survive completion and session changes with an offline runtime."""
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.test_preview_channel import qt_application
from app.controller import Controller
from app.pi_sessions import SessionState
from app.storage import Store


class ModelSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = qt_application()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="umeko-model-selection-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        environment = patch.dict(os.environ, {
            "UMEKO_DATA_DIR": str(self.directory / "profile"),
            "PI_CODING_AGENT_DIR": str(self.directory / "agent"),
        })
        environment.start()
        self.addCleanup(environment.stop)
        for target, options in (
            ("app.provider_plugins.BundledProviders.sync", {"return_value": []}),
            ("app.controller.LocalServer", {}),
        ):
            replacement = patch(target, **options)
            replacement.start()
            self.addCleanup(replacement.stop)
        seed = Store()
        seed.data["agent"].update(agentDir=str(self.directory / "agent"))
        seed.data["providers"] = [{
            "id": "selection-fixture", "name": "Selection Fixture", "api": "openai",
            "baseUrl": "https://selection.invalid/v1", "key": "", "models": [
                {"alias": name, "upstream": name, "reasoningLevels": [],
                 "reasoningLevelsAuto": False, "reasoningFormat": "openai",
                 "reasoningFormatAuto": False}
                for name in ("choice-a", "choice-b", "choice-c")
            ],
        }]
        seed.data.update(selectedProvider="selection-fixture", selectedModel="choice-a")
        seed.save()
        self.controller = Controller(ROOT)
        self.addCleanup(self.controller.close)
        self.requests = []
        self.writes = []
        for target, options in (
            ("_command_pi", {"side_effect": self.command}),
            ("_job", {"side_effect": AssertionError("Offline selection uses synchronous events")}),
        ):
            replacement = patch.object(self.controller, target, **options)
            replacement.start()
            self.addCleanup(replacement.stop)
        replacement = patch.object(self.controller._pool, "write",
                                   side_effect=lambda record, payload: self.writes.append((record, payload)))
        replacement.start()
        self.addCleanup(replacement.stop)

    def command(self, action, record=None, **values):
        """Capture the model at the real send path's runtime boundary."""
        record = record or self.controller._view
        self.requests.append((record.key, record.provider, record.model, action, values))
        record.action = action
        record.phase = "running"
        record.prompt_started = time.monotonic()
        record.cancelled = False
        return True

    def start(self):
        self.assertTrue(self.controller.send("Start the controlled turn"))
        record = self.controller._view
        self.assertTrue(record.busy)
        self.assertEqual(self.requests[-1][1:3], ("selection-fixture", "choice-a"))
        return record

    def select(self, name):
        self.controller.selectModel("selection-fixture", name)

    def assert_selected(self, name):
        self.assertEqual(self.controller.config["selectedProvider"], "selection-fixture")
        self.assertEqual(self.controller.config["selectedModel"], name)

    def complete(self, record):
        self.controller._handle_pi_event(record, {"type": "done"})
        self.assertFalse(record.busy)

    def assert_next_send(self, name):
        self.assertTrue(self.controller.send("Send immediately after completion"))
        self.assertEqual(self.requests[-1][1:3], ("selection-fixture", name))

    def test_busy_selection_survives_stop_and_completion(self):
        record = self.start()
        self.select("choice-b")
        self.controller.stop()
        self.assertEqual(self.writes[-1], (record, {"type": "abort"}))
        self.assertEqual(self.requests[0][2], "choice-a")
        self.complete(record)
        self.assert_selected("choice-b")
        self.assert_next_send("choice-b")

    def test_selection_at_turn_end_reaches_immediate_next_send(self):
        record = self.start()
        self.select("choice-b")
        self.complete(record)
        self.assert_selected("choice-b")
        self.assert_next_send("choice-b")

    def test_latest_selection_and_return_to_running_model_take_effect(self):
        record = self.start()
        self.select("choice-b")
        self.assert_selected("choice-b")
        self.select("choice-c")
        self.assert_selected("choice-c")
        self.select("choice-a")
        self.complete(record)
        self.assert_selected("choice-a")
        self.assert_next_send("choice-a")

    def session_switch(self, return_before_done):
        first = self.start()
        self.select("choice-b")
        second = SessionState(id="second-fixture", title="Second fixture",
                              provider="selection-fixture", model="choice-c")
        self.controller._pool.touch(second)
        self.controller._activate(second)
        self.assert_selected("choice-c")
        if return_before_done:
            self.controller._activate(first)
            self.assert_selected("choice-b")
            self.controller._activate(second)
        self.complete(first)
        self.assertIs(self.controller._view, second)
        self.assert_selected("choice-c")
        self.controller._activate(first)
        self.assert_selected("choice-b")
        self.assert_next_send("choice-b")

    def test_background_done_preserves_both_session_selections(self):
        self.session_switch(return_before_done=False)

    def test_returning_before_done_preserves_selected_model(self):
        self.session_switch(return_before_done=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
