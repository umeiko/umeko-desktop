"""PID scene-graph playback continues while the GUI thread is blocked."""
from pathlib import Path
import json
import os
import threading
import time

os.environ.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software', QSG_RENDER_LOOP='threaded')
from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression

app = QGuiApplication([])
engine = QQmlApplicationEngine()
root = Path(__file__).resolve().parents[1]
engine.loadData(b'''import QtQuick
Window {
    width: 640; height: 480; visible: true
    Rectangle { id: box; x: 40; y: 40; width: 80; height: 34; color: "red" }
    PidYAnimator { id: motion; target: box }
    function begin() { motion.snapTo(40); motion.moveTo(340) }
}''', QUrl.fromLocalFile(str(root / 'app/qml/PidThreadProbe.qml')))
assert engine.rootObjects(), 'PID animation probe failed to load'
window = engine.rootObjects()[0]
frames, stall = [], []
window.afterRendering.connect(lambda: frames.append((time.monotonic(), threading.get_ident())), Qt.DirectConnection)

def begin():
    expression = QQmlExpression(engine.rootContext(), window, 'begin()')
    expression.evaluate()
    assert not expression.hasError(), expression.error().toString()
    QTimer.singleShot(80, block)

def block():
    stall.append(time.monotonic())
    time.sleep(.4)
    stall.append(time.monotonic())
    QTimer.singleShot(800, app.quit)

QTimer.singleShot(200, begin)
app.exec()
during = [entry for entry in frames if stall[0] < entry[0] < stall[1]]
result = {'stall_ms': round((stall[1]-stall[0])*1000), 'rendered_frames_during_gui_stall': len(during)}
assert len(during) >= 10 and all(entry[1] != threading.get_ident() for entry in during), result
print('PID_RENDER_THREAD_OK:', json.dumps(result))
