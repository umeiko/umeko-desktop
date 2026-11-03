"""Real session-cache QML with an isolated backend; no desktop or Pi services.

Documentation captures: python tests/test_session_cache_setting.py --capture
"""
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

from PySide6.QtCore import QObject, Property, QEventLoop, QPointF, QTimer, QUrl, Signal, Slot
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
import shiboken6
from test_preview_channel import isolated_test_module, qt_application


class CacheBackend(QObject):
    changed = Signal()

    def __init__(self, language="zh", size=None):
        super().__init__()
        self._language = language
        self._ui = {} if size is None else {"sessionCacheSize": size}
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
        return {"fontFamily": qt_application().font().family(), "theme": "light", "ui": dict(self._ui)}

    @Property("QVariantMap", constant=True)
    def themeStyle(self): return {"base": "light", "colors": {}}

    @Slot(int, result=bool)
    def setSessionCacheSize(self, value):
        self.calls.append(value)
        if not self.accept_save:
            return False
        self._ui["sessionCacheSize"] = value
        self.changed.emit()
        return True


class CacheSettings:
    def __init__(self, language="zh", size=None):
        self.backend = CacheBackend(language, size)
        self.engine = QQmlApplicationEngine()
        self.warnings = []
        self.engine.warnings.connect(lambda errors: self.warnings.extend(error.toString() for error in errors))
        self.engine.rootContext().setContextProperty("backend", self.backend)
        qml = '''
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "%s" as UI
ApplicationWindow {
    width: 820; height: 470; visible: true
    color: UI.Theme.bg
    title: "Umeko session cache preferences"
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 36; spacing: 18
        Text { text: "Umeko"; color: UI.Theme.muted; font.family: UI.Theme.fontFamily; font.pixelSize: 12; font.letterSpacing: 1.6 }
        Text { text: UI.I18n.t("Pi 配置"); color: UI.Theme.ink; font.family: UI.Theme.fontFamily; font.pixelSize: 28; font.weight: Font.DemiBold }
        UI.SettingsFold {
            Layout.fillWidth: true; title: UI.I18n.t("运行与资源"); expanded: true
            UI.SessionCacheSettings { width: parent.width }
        }
        Item { Layout.fillHeight: true }
    }
}
''' % QUrl.fromLocalFile(str(ROOT / "app/qml")).toString()
        self.engine.loadData(qml.encode("utf-8"), QUrl.fromLocalFile(str(ROOT / "tests/SessionCacheHarness.qml")))
        roots = self.engine.rootObjects()
        if not roots:
            raise AssertionError("\n".join(self.warnings))
        self.window = roots[0]
        if not isinstance(self.window, QQuickWindow):
            raise AssertionError("Expected a Qt Quick application window")
        qt_application().processEvents()

    def find(self, name):
        item = self.window.findChild(QObject, name)
        if item is None:
            raise AssertionError("Missing QML object: " + name)
        return item

    def modify(self, value):
        control = self.find("sessionCacheSizeValue")
        control.setProperty("value", value)
        control.valueModified.emit()
        qt_application().processEvents()

    def capture(self, path):
        loop = QEventLoop()
        guard = QTimer()
        guard.setSingleShot(True)
        guard.timeout.connect(loop.quit)
        self.window.afterAnimating.connect(loop.quit)
        self.window.requestUpdate()
        guard.start(5000)
        loop.exec()
        self.window.afterAnimating.disconnect(loop.quit)
        guard.stop()
        qt_application().processEvents()
        for name in ("sessionCacheTitle", "sessionCacheSizeLabel", "sessionCacheDescription", "sessionCacheRunningDescription"):
            item = self.find(name)
            position = item.mapToScene(QPointF(0, 0))
            if (item.property("contentHeight") > item.property("height") + 1
                    or item.property("contentWidth") > item.property("width") + 1
                    or position.y() + item.property("height") > self.window.height()):
                raise AssertionError("Offscreen setting text does not fit: " + name)
        image = self.window.grabWindow()
        if image.isNull() or not image.save(str(path)):
            raise AssertionError("Unable to capture offscreen QML: " + str(path))

    def close(self):
        self.window.close()
        shiboken6.delete(self.engine)


class SessionCacheSettingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = qt_application()

    def ui(self, language="zh", size=None):
        result = CacheSettings(language, size)
        self.addCleanup(result.close)
        return result

    def test_missing_saved_setting_displays_default_without_writing(self):
        ui = self.ui()
        self.assertEqual(ui.find("sessionCacheSizeValue").property("value"), 3)
        self.assertEqual(ui.backend.calls, [])
        self.assertEqual(ui.find("sessionCacheTitle").property("text"), "会话缓存")
        self.assertIn("设为 0", ui.find("sessionCacheDescription").property("text"))
        self.assertIn("包括当前会话", ui.find("sessionCacheDescription").property("text"))
        self.assertIn("仅保留当前空闲会话", ui.find("sessionCacheDescription").property("text"))
        self.assertIn("不占用此数量", ui.find("sessionCacheRunningDescription").property("text"))
        self.assertEqual(ui.warnings, [])

    def test_edit_saves_zero_and_qt_integer_maximum(self):
        ui = self.ui(size=5)
        self.assertEqual(ui.find("sessionCacheSizeValue").property("value"), 5)
        ui.modify(0)
        self.assertEqual(ui.backend.calls, [0])
        self.assertEqual(ui.backend.config["ui"]["sessionCacheSize"], 0)
        ui.modify(2147483647)
        self.assertEqual(ui.backend.calls, [0, 2147483647])
        self.assertEqual(ui.backend.config["ui"]["sessionCacheSize"], 2147483647)
        self.assertEqual(ui.warnings, [])

    def test_failed_save_restores_value_and_live_config_remains_bound(self):
        ui = self.ui(size=7)
        ui.backend.accept_save = False
        ui.modify(0)
        self.assertEqual(ui.backend.calls, [0])
        self.assertEqual(ui.find("sessionCacheSizeValue").property("value"), 7)
        ui.backend._ui["sessionCacheSize"] = 4
        ui.backend.changed.emit()
        self.app.processEvents()
        self.assertEqual(ui.find("sessionCacheSizeValue").property("value"), 4)
        self.assertEqual(ui.backend.calls, [0])
        self.assertEqual(ui.warnings, [])

    def test_english_labels_and_running_session_explanation(self):
        ui = self.ui(language="en", size=0)
        self.assertEqual(ui.find("sessionCacheTitle").property("text"), "Session cache")
        self.assertEqual(ui.find("sessionCacheSizeLabel").property("text"), "Cached idle sessions")
        self.assertIn("Set to 0", ui.find("sessionCacheDescription").property("text"))
        self.assertIn("including the current session", ui.find("sessionCacheDescription").property("text"))
        self.assertIn("keep only the current idle session", ui.find("sessionCacheDescription").property("text"))
        description = ui.find("sessionCacheRunningDescription").property("text")
        self.assertIn("running, using tools or awaiting approval", description)
        self.assertIn("do not count toward this limit", description)
        self.assertEqual(ui.find("sessionCacheSizeValue").property("value"), 0)
        self.assertEqual(ui.backend.calls, [])
        self.assertEqual(ui.warnings, [])


def capture_documentation():
    app = qt_application()
    output = ROOT / "docs/images"
    output.mkdir(parents=True, exist_ok=True)
    for language in ("zh", "en"):
        ui = CacheSettings(language, 3)
        try:
            ui.capture(output / ("session-cache-" + language + ".png"))
            if ui.warnings:
                raise AssertionError("\n".join(ui.warnings))
        finally:
            ui.close()
    print("Offscreen captures: docs/images/session-cache-{zh,en}.png")


if __name__ != "__main__":
    class IsolatedSessionCacheSettingTests(unittest.TestCase):
        def test_session_cache_setting_in_isolated_process(self):
            isolated_test_module(self, Path(__file__).resolve())


def load_tests(loader, tests, pattern):
    if __name__ == "__main__":
        return tests
    return unittest.TestSuite([IsolatedSessionCacheSettingTests("test_session_cache_setting_in_isolated_process")])


if __name__ == "__main__":
    if sys.argv[1:] == ["--capture"]:
        capture_documentation()
    else:
        unittest.main()
