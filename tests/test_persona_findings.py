"""Focused controller regressions for the persona-test findings."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication

from app.controller import Controller
from app.storage import Store

ROOT = Path(__file__).resolve().parents[1]


class PersonaFindingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        profile = Path(self.temp.name) / "profile"
        agent = Path(self.temp.name) / "pi-agent"
        agent.mkdir()
        self.environment = patch.dict(os.environ, {"UMEKO_DATA_DIR": str(profile),
            "PI_CODING_AGENT_DIR": str(agent), "QT_QPA_PLATFORM": "offscreen"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        store = Store(profile)
        store.data["agent"]["agentDir"] = str(agent)
        store.save()
        self.c = Controller(ROOT)
        self.addCleanup(self.c.close)

    def provider(self, models):
        self.assertTrue(self.c.saveProvider("", "Fixture", "openai",
            "http://127.0.0.1:18181/v1", "synthetic-key", json.dumps(models)))
        return self.c.store.data["providers"][-1]

    def test_same_upstream_two_aliases_roundtrip_through_both_save_entries(self):
        models = [{"upstream": "fixture-model", "alias": "quick", "vision": False,
                   "visionAuto": False, "contextWindow": 32000, "contextWindowAuto": False},
                  {"upstream": "fixture-model", "alias": "visual", "vision": True,
                   "visionAuto": False, "contextWindow": 64000, "contextWindowAuto": False}]
        provider = self.provider(models)
        mappings = [{"provider": provider["id"], **model} for model in provider["models"]]
        self.assertTrue(self.c.saveMappings(json.dumps(mappings)))
        # Old editors omit capabilities. Preserve each alias's own settings.
        names = [{"upstream": model["upstream"], "alias": model["alias"]} for model in models]
        self.assertTrue(self.c.saveProvider(provider["id"], "Fixture", "openai",
            provider["baseUrl"], "", json.dumps(names)))
        saved = self.c.gateway.provider(provider["id"])["models"]
        self.assertEqual([(m["alias"], m["upstream"], m["vision"], m["contextWindow"]) for m in saved],
            [("quick", "fixture-model", False, 32000), ("visual", "fixture-model", True, 64000)])

    def test_invalid_mapping_returns_failure_and_keeps_saved_configuration(self):
        provider = self.provider([{"upstream": "one", "alias": "one"}])
        before = copy.deepcopy(self.c.store.data["providers"])
        invalid = [{"provider": provider["id"], "upstream": model, "alias": "duplicate"}
                   for model in ("one", "two")]
        result = self.c._umeko_control.execute({"operation": "models.mappings", "arguments": {"models": invalid}})
        self.assertFalse(result["ok"])
        self.assertNotEqual(result.get("status"), "applied")
        self.assertIn("别名不能重复", result["error"])
        self.assertEqual(self.c.store.data["providers"], before)
        self.assertFalse(self.c.saveProvider(provider["id"], "Fixture", "openai", provider["baseUrl"], "",
            json.dumps([{k: v for k, v in model.items() if k != "provider"} for model in invalid])))
        self.assertEqual(self.c.store.data["providers"], before)

    def test_send_during_kernel_check_has_visible_and_queryable_reason(self):
        notices = []
        self.c.toast.connect(notices.append)
        self.c._kernel_busy = True
        self.assertFalse(self.c.send("Hello"))
        self.assertIn("完成后即可再次发送", notices[-1])
        self.assertEqual(self.c.lastSendError, notices[-1])
        status = self.c._umeko_control.execute({"operation": "status.get"})
        self.assertEqual(status["lastSendError"], notices[-1])
        self.assertTrue(status["kernel"]["busy"])
        self.assertEqual(self.c._view.messages, [])


if __name__ == "__main__":
    unittest.main()
