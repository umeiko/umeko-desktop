"""Cold Widget catalog arrival: no detail click, no idle polling after settlement."""
import os
from pathlib import Path
import time
import subprocess
import sys

if len(sys.argv) == 1:
    for scenario in ("ready", "failed"):
        subprocess.run([sys.executable, __file__, scenario], check=True)
    print("PI_WIDGET_COLD_START_OK: first-open tags, async failure, no idle polling")
    raise SystemExit(0)

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest
import shiboken6

root = Path(__file__).resolve().parents[1]
app = QGuiApplication([])
engine = QQmlApplicationEngine()
failed = sys.argv[1] == 'failed'
engine.setInitialProperties({'failInventory': failed})
engine.load(QUrl.fromLocalFile(str(root/'tests/fixtures/PiManagerColdStart.qml')))
assert engine.rootObjects()
window = engine.rootObjects()[0]

def wait(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        QTest.qWait(20)
        if predicate(): return
    raise AssertionError('First-open tool inventory did not settle')

try:
    wait(lambda: window.property('inventoryRequests') == 1)
    if failed:
        wait(lambda: window.property('registryFailed') and '失败' in window.property('page').property('notice'))
        assert not window.property('page').property('inventoryLoading')
        assert '失败' in window.property('page').property('notice')
    else:
        wait(lambda: window.property('tagsReady'))
        assert not window.property('page').property('selected')
        assert not window.property('page').property('inventoryLoading')
        screenshot = root/'artifacts/screenshots/pi-widget-first-open.png'
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        assert window.grabWindow().save(str(screenshot))
    count = window.property('statusRequests')
    QTest.qWait(900)
    assert window.property('statusRequests') == count, 'Settled Widget must stop polling'
    assert window.property('inventoryRequests') == 1, 'Do not reload Pi repeatedly'
finally:
    window.hide()
    shiboken6.delete(engine)
