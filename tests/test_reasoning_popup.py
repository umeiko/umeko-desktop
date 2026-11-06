"""Actual ModelPopup.open reaches the QML onOpened discovery hook once."""
import os
from pathlib import Path
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
os.environ.setdefault('QT_QUICK_CONTROLS_STYLE', 'Basic')

from PySide6.QtCore import QObject, Property, QMetaObject, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

ROOT = Path(__file__).resolve().parents[1]


class PopupBackend(QObject):
    changed = Signal()
    reasoningDetectionChanged = Signal()
    reasoningChanged = Signal()

    def __init__(self):
        super().__init__()
        self.ensure_calls = 0

    config = Property('QVariantMap', lambda self: {
        'providers': [], 'fontFamily': '', 'theme': 'light',
        'selectedProvider': '', 'selectedModel': ''}, notify=changed)
    themeStyle = Property('QVariantMap', lambda self: {}, constant=True)
    fontScale = Property(float, lambda self: 1.0, constant=True)
    lineSpacing = Property(str, lambda self: 'standard', constant=True)
    language = Property(str, lambda self: 'en', constant=True)
    reasoningLevels = Property('QStringList', lambda self: [], notify=reasoningDetectionChanged)
    reasoningDetectionState = Property(str, lambda self: 'unknown', notify=reasoningDetectionChanged)
    reasoningOffSupported = Property('QVariant', lambda self: None, notify=reasoningDetectionChanged)
    reasoningEffort = Property(str, lambda self: 'off', notify=reasoningChanged)

    @Slot(result=bool)
    def ensureReasoningDetection(self):
        self.ensure_calls += 1
        return True

    @Slot(str, result=bool)
    def setReasoningEffort(self, effort):
        return effort == 'off'


class ReasoningPopupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def until(self, predicate):
        deadline = time.monotonic() + 4
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
        self.assertTrue(predicate(), 'QML popup event deadline exceeded')

    def test_actual_popup_open_invokes_ensure_once_per_open(self):
        backend = PopupBackend()
        engine = QQmlApplicationEngine()
        warnings = []
        engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
        engine.rootContext().setContextProperty('backend', backend)
        source = b'''import QtQuick
import QtQuick.Controls
import "app/qml"
ApplicationWindow {
    visible: true; width: 900; height: 700
    Item { id: anchor; x: 30; y: 600; width: 200; height: 32
        ModelPopup {
            objectName: "testedModelPopup"; parent: anchor
            exit: Transition {}
        }
    }
}'''
        try:
            engine.loadData(source, QUrl.fromLocalFile(str(ROOT / 'reasoning-popup-fixture.qml')))
            self.assertTrue(engine.rootObjects(), warnings)
            window = engine.rootObjects()[0]
            popup = window.findChild(QObject, 'testedModelPopup')
            self.assertIsNotNone(popup)
            self.app.processEvents()
            self.assertEqual(backend.ensure_calls, 0, 'constructing the popup must not request discovery')

            self.assertTrue(QMetaObject.invokeMethod(popup, 'open'))
            self.until(lambda: backend.ensure_calls == 1)
            self.assertTrue(popup.property('opened'))
            self.assertTrue(QMetaObject.invokeMethod(popup, 'open'))
            backend.changed.emit()
            backend.reasoningDetectionChanged.emit()
            self.app.processEvents()
            self.assertEqual(backend.ensure_calls, 1, 'an already open popup must not re-run onOpened')

            self.assertTrue(QMetaObject.invokeMethod(popup, 'close'))
            self.until(lambda: not popup.property('visible'))
            self.assertTrue(QMetaObject.invokeMethod(popup, 'open'))
            self.until(lambda: backend.ensure_calls == 2)
            self.assertEqual(warnings, [])
        finally:
            import shiboken6
            shiboken6.delete(engine)
            self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
