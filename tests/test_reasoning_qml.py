"""Load the actual popup offscreen and exercise its dynamic backend bindings."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ReasoningPopupTests(unittest.TestCase):
    def test_dynamic_popup_loads_and_tracks_manual_levels(self):
        with tempfile.TemporaryDirectory(prefix='umeko-reasoning-qml-') as profile:
            environment = {**os.environ, 'UMEKO_DATA_DIR': profile,
                           'QT_QPA_PLATFORM': 'offscreen', 'QT_QUICK_BACKEND': 'software'}
            run = subprocess.run([sys.executable, __file__, '--worker'], cwd=ROOT, env=environment,
                capture_output=True, text=True, timeout=45,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertEqual(run.returncode, 0, run.stdout[-1000:] + run.stderr[-3000:])
            self.assertIn('REASONING_POPUP_OK', run.stdout)


def worker():
    sys.path.insert(0, str(ROOT))
    import faulthandler
    faulthandler.enable()
    from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtWidgets import QApplication
    import shiboken6
    class Backend(QObject):
        changed = Signal()
        reasoningLevelsChanged = Signal()
        reasoningChanged = Signal()
        def __init__(self):
            super().__init__()
            self.options = [{'value': 'off', 'label': '关闭'}, {'value': 'medium', 'label': 'medium'},
                            {'value': 'xhigh', 'label': 'xhigh'}]
            self.effort = 'off'
        config = Property('QVariantMap', lambda self: {'providers': [], 'fontFamily': '', 'theme': 'light'}, constant=True)
        themeStyle = Property('QVariantMap', lambda self: {}, constant=True)
        fontScale = Property(float, lambda self: 1., constant=True)
        lineSpacing = Property(str, lambda self: 'standard', constant=True)
        language = Property(str, lambda self: 'zh', constant=True)
        reasoningLevels = Property('QVariantList', lambda self: self.options, notify=reasoningLevelsChanged)
        reasoningDetectionState = Property(str, lambda self: 'manual', notify=reasoningLevelsChanged)
        reasoningEffort = Property(str, lambda self: self.effort, notify=reasoningChanged)
        @Slot(str, result=bool)
        def setReasoningEffort(self, value):
            self.effort = value
            self.reasoningChanged.emit()
            return True
    app = QApplication([])
    if not QFontDatabase.families() and os.name == 'nt':
        for font in ('msyh.ttc', 'segoeui.ttf', 'consola.ttf'):
            QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / font))
    backend = Backend()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend', backend)
    source = b'''import QtQuick
import QtQuick.Controls
import "app/qml"
ApplicationWindow {
    visible: false; width: 800; height: 600
    Item { id: anchor; width: 200; height: 32
        ModelPopup { objectName: "modelPopup"; parent: anchor }
    }
}'''
    window = None
    try:
        engine.loadData(source, QUrl.fromLocalFile(str(ROOT / 'reasoning-test.qml')))
        assert engine.rootObjects(), 'Popup harness did not load'
        window = engine.rootObjects()[0]
        popup = window.findChild(QObject, 'modelPopup')
        assert popup is not None
        def buttons():
            app.processEvents()
            pending = [popup.property('contentItem')]
            names = set()
            while pending:
                item = pending.pop()
                if item.objectName().startswith('reasoningEffort_'):
                    names.add(item.objectName())
                pending.extend(item.childItems())
            return names
        assert buttons() == {'reasoningEffort_off', 'reasoningEffort_medium', 'reasoningEffort_xhigh'}
        assert backend.setReasoningEffort('medium')
        assert backend.reasoningDetectionState == 'manual'
        backend.options = [{'value': value, 'label': value} for value in ('off', 'low', 'high', 'max')]
        backend.reasoningLevelsChanged.emit()
        assert buttons() == {'reasoningEffort_off', 'reasoningEffort_low', 'reasoningEffort_high', 'reasoningEffort_max'}
        print('REASONING_POPUP_OK', flush=True)
    finally:
        shiboken6.delete(engine)


if __name__ == '__main__':
    if '--worker' in sys.argv:
        worker()
    else:
        unittest.main()
