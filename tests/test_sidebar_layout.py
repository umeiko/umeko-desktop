"""Layout preference compatibility and persistence, without starting Pi."""
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
APP = QCoreApplication.instance() or QCoreApplication([])


class SidebarLayoutTests(unittest.TestCase):
    def test_old_profiles_gain_layout_defaults_and_invalid_widths_remain_usable(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp))
            saved = json.loads(store.path.read_text(encoding="utf-8"))
            saved.pop("ui")
            store.path.write_text(json.dumps(saved), encoding="utf-8")
            self.assertEqual({k:v for k,v in Store(Path(temp)).data['ui'].items() if k.startswith('sidebar')}, {"sidebarWidth": 244, "sidebarCollapsed": False})
            for bad, expected in (("invalid", 244), (True, 244), (None, 244), (-20, 200), (2000, 480)):
                saved["ui"] = {"sidebarWidth": bad}
                store.path.write_text(json.dumps(saved), encoding="utf-8")
                self.assertEqual({k:v for k,v in Store(Path(temp)).data['ui'].items() if k.startswith('sidebar')}, {"sidebarWidth": expected, "sidebarCollapsed": False})

    def test_saved_layout_survives_restart_without_changing_the_active_conversation(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"UMEKO_DATA_DIR": temp}):
            controller = Controller(ROOT)
            try:
                record = controller._view
                record.draft = "Unsent fixture"
                record.phase = "running"
                record.messages = [{"role": "user", "text": "Fixture"}]
                changed = []
                controller.changed.connect(lambda: changed.append(True))
                self.assertTrue(controller.saveSidebarLayout(352, True))
                self.assertEqual((controller.sidebarWidth, controller.sidebarCollapsed), (352, True))
                self.assertIs(controller._view, record)
                self.assertTrue(record.busy)
                self.assertEqual(record.draft, "Unsent fixture")
                self.assertEqual(record.messages[0]["text"], "Fixture")
                self.assertEqual(changed, [], "layout updates refreshed unrelated settings")
                self.assertEqual({k:v for k,v in Store(Path(temp)).data["ui"].items() if k.startswith("sidebar")}, {"sidebarWidth": 352, "sidebarCollapsed": True})
                with patch.object(controller.store, "save", side_effect=OSError("fixture denied")):
                    self.assertFalse(controller.saveSidebarLayout(400, False))
                self.assertEqual((controller.sidebarWidth, controller.sidebarCollapsed), (352, True))
            finally:
                controller.close()
            restarted = Controller(ROOT)
            try:
                self.assertEqual((restarted.sidebarWidth, restarted.sidebarCollapsed), (352, True))
            finally:
                restarted.close()


if __name__ == "__main__":
    unittest.main()
