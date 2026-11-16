"""Real plugin session model QML with an isolated backend; no desktop or Pi services."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QUICK_BACKEND"] = "software"
os.environ["QT_QUICK_CONTROLS_STYLE"] = "Basic"

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
import shiboken6
from test_preview_channel import isolated_test_module, qt_application

CHOICES = [{"providerId": "test-provider", "model": "test-model-a", "label": "Test provider / test-model-a"},
           {"providerId": "test-provider", "model": "test-model-b", "label": "Test provider / test-model-b"}]


class ProfileBackend(QObject):
    changed = Signal()

    def __init__(self, language="zh"):
        super().__init__()
        self._language = language
        self._profiles = [{"plugin": "session-task-service", "profile": "tasks", "pluginName": "Session task service",
                           "model": "test-model-a", "provider": "test-provider"}]
        self.calls = []
        self.accept_save = True

    @Property(str, notify=changed)
    def language(self): return self._language

    @Property(float, constant=True)
    def fontScale(self): return 1.0

    @Property(str, constant=True)
    def lineSpacing(self): return "standard"

    @Property("QVariantMap", notify=changed)
    def config(self):
        return {"fontFamily": qt_application().font().family(), "theme": "light", "ui": {}}

    @Property("QVariantMap", constant=True)
    def themeStyle(self): return {"base": "light", "colors": {}}

    @Property("QVariantList", notify=changed)
    def pluginSessionProfiles(self): return [dict(row) for row in self._profiles]

    @Property("QVariantList", notify=changed)
    def pluginSessionModels(self): return [dict(row) for row in CHOICES]

    @Slot(str, str, str, str, result=bool)
    def savePluginSessionModel(self, plugin, profile, model, provider):
        self.calls.append((plugin, profile, model, provider))
        if not self.accept_save:
            return False
        self._profiles[0].update(model=model, provider=provider)
        self.changed.emit()
        return True


class ProfileSettings:
    def __init__(self, language="zh"):
        self.backend = ProfileBackend(language)
        self.engine = QQmlApplicationEngine()
        self.warnings = []
        self.engine.warnings.connect(lambda errors: self.warnings.extend(error.toString() for error in errors))
        self.engine.rootContext().setContextProperty("backend", self.backend)
        qml = '''
import QtQuick
import QtQuick.Controls
import "%s" as UI
ApplicationWindow {
    width: 820; height: 360; visible: true
    color: UI.Theme.bg
    UI.PluginSessionModels { x: 36; y: 36; width: parent.width - 72 }
}
''' % QUrl.fromLocalFile(str(ROOT / "app/qml")).toString()
        self.engine.loadData(qml.encode("utf-8"), QUrl.fromLocalFile(str(ROOT / "tests/PluginSessionModelsHarness.qml")))
        roots = self.engine.rootObjects()
        if not roots:
            raise AssertionError("\n".join(self.warnings))
        self.window = roots[0]
        if not isinstance(self.window, QQuickWindow):
            raise AssertionError("Expected a Qt Quick application window")
        qt_application().processEvents()
        qt_application().processEvents()

    def items(self):
        # Repeater delegates are visual children, not QObject children.
        pending, found = [self.window.contentItem()], []
        while pending:
            item = pending.pop()
            found.append(item)
            pending.extend(item.childItems())
        return found

    def picker(self):
        item = next((item for item in self.items() if item.objectName() == "pluginSessionModel_session-task-service_tasks"), None)
        if item is None:
            raise AssertionError("Missing plugin session model picker")
        return item

    def close(self):
        self.window.close()
        shiboken6.delete(self.engine)


class PluginSessionModelSettingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = qt_application()

    def ui(self, language="zh"):
        result = ProfileSettings(language)
        self.addCleanup(result.close)
        return result

    def test_picker_shows_current_model_and_saves_only_model_and_provider(self):
        ui = self.ui()
        picker = ui.picker()
        self.assertEqual(picker.property("currentIndex"), 0)
        self.assertEqual(picker.property("displayText"), "Test provider / test-model-a")
        picker.setProperty("currentIndex", 1)
        picker.activated.emit(1)
        self.app.processEvents()
        self.assertEqual(ui.backend.calls, [("session-task-service", "tasks", "test-model-b", "test-provider")])
        self.app.processEvents()
        self.assertEqual(picker.property("displayText"), "Test provider / test-model-b")
        self.assertEqual(ui.warnings, [])

    def test_rejected_save_restores_the_saved_model(self):
        ui = self.ui()
        ui.backend.accept_save = False
        picker = ui.picker()
        picker.setProperty("currentIndex", 1)
        picker.activated.emit(1)
        self.app.processEvents()
        self.app.processEvents()
        self.assertEqual(picker.property("currentIndex"), 0)
        self.assertEqual(ui.warnings, [])

    def test_english_labels(self):
        ui = self.ui("en")
        texts = {item.property("text") for item in ui.items() if isinstance(item.property("text"), str)}
        self.assertIn("Plugin session models", texts)
        self.assertIn("Session profile: tasks", texts)
        self.assertEqual(ui.warnings, [])


if __name__ != "__main__":
    class IsolatedPluginSessionModelSettingTests(unittest.TestCase):
        def test_plugin_session_model_setting_in_isolated_process(self):
            isolated_test_module(self, Path(__file__).resolve())


def load_tests(loader, tests, pattern):
    if __name__ == "__main__":
        return tests
    return unittest.TestSuite([IsolatedPluginSessionModelSettingTests("test_plugin_session_model_setting_in_isolated_process")])


if __name__ == "__main__":
    unittest.main()
