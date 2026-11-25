"""Exercise the real pet popup, native focus and bound task route offscreen."""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
temporary = tempfile.TemporaryDirectory(prefix='umeko-pet-task-ui-')
os.environ.update(UMEKO_DATA_DIR=str(Path(temporary.name) / 'profile'),
                  PI_CODING_AGENT_DIR=str(Path(temporary.name) / 'agent'),
                  QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software', UMEKO_LANGUAGE='zh')
from PySide6.QtCore import QObject, QPoint, QPointF, Qt
from PySide6.QtGui import QGuiApplication, QInputMethodEvent
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QSystemTrayIcon
from shiboken6 import isValid
QSystemTrayIcon.show = lambda *args: None
from main import create_application

app, engine, backend = create_application()
backend.store.data.setdefault('agent', {})['agentDir'] = str(Path(temporary.name) / 'agent')
main = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda values: warnings.extend(value.toString() for value in values))
pet = backend.desktopPlugins.pet
out = Path(os.environ.get('UMEKO_PET_TASK_UI_OUTPUT', str(ROOT / 'build/pet-task-ui')))
out.mkdir(parents=True, exist_ok=True)


def wait(predicate, message):
    for _ in range(400):
        QTest.qWait(20)
        if predicate():
            return
    raise AssertionError(message + '\n' + '\n'.join(warnings))


def evaluate(obj, expression):
    query = QQmlExpression(QQmlEngine.contextForObject(obj), obj, expression)
    result = query.evaluate()[0]
    assert not query.hasError(), query.error().toString()
    return result


try:
    pet.ui('show', {})
    wait(lambda: main.findChild(QObject, 'desktopPetWindow') is not None, 'Pet did not load')
    window = main.findChild(QObject, 'desktopPetWindow')
    wait(lambda: window.mask().boundingRect().height() > 50, 'Pet silhouette missing')
    wait(lambda: pet.assistantStatus.get('bound'), 'Pet not bound')
    composer = window.findChild(QObject, 'desktopPetTaskComposer')
    field = composer.findChild(QObject, 'desktopPetTaskInput')
    bubble = window.findChild(QObject, 'desktopPetSpeechBubble')
    from PySide6.QtGui import QCursor, QMouseEvent
    from PySide6.QtCore import QEvent
    def dispatch(kind, global_pos, button, buttons):
        QCursor.setPos(global_pos)
        local = window.mapFromGlobal(global_pos)
        event = QMouseEvent(kind, QPointF(local), QPointF(global_pos), button, buttons, Qt.NoModifier)
        QGuiApplication.sendEvent(window, event)
        QTest.qWait(30)
    traces = {}
    for opened in (False, True):
        window.setPosition(350, 250)
        QTest.qWait(100)
        point = window.mask().boundingRect().center()
        if opened:
            QTest.mouseDClick(window, Qt.LeftButton, Qt.NoModifier, point)
            wait(lambda: composer.property('opened'), 'Composer did not open')
            field.setProperty('text', '拖动后仍保留的草稿')
        start = window.mapToGlobal(point)
        dispatch(QEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton)
        trace = []
        for delta in (10, 20, 30, 20, 0):
            dispatch(QEvent.MouseMove, start + QPoint(delta, 0), Qt.NoButton, Qt.LeftButton)
            trace.append([window.x(), window.y()])
            if opened:
                assert composer.property('desiredOpen'), 'Drag closed composer'
                assert not bubble.property('visible'), 'Ordinary drag bubble covers input'
                native = evaluate(composer, 'contentItem.Window.window')
                assert native.flags() & Qt.Tool == Qt.Tool
                assert abs(native.x() - (window.x() + (window.width()-native.width())/2)) <= 1
                assert field.property('text') == '拖动后仍保留的草稿'
            assert (window.x(), window.y()) == (350 + delta, 250), trace
        dispatch(QEvent.MouseButtonRelease, start, Qt.LeftButton, Qt.NoButton)
        assert pet.position() == {'x':350, 'y':250}
        if opened:
            assert composer.property('desiredOpen'), 'Dragging pet dismissed input'
            assert field.property('text') == '拖动后仍保留的草稿'
        if opened:
            # Critical assistant notices remain visible without overlapping
            # the input, both in normal placement and near the top edge.
            pet.assistantSpeech.emit('需要确认的重要任务通知')
            QTest.qWait(80)
            assert bubble.property('visible')
            for y in (250, 0):
                window.setY(y); QTest.qWait(80)
                top = window.y() + bubble.y()
                bottom = top + bubble.height()
                assert native.y() + native.height() <= top or native.y() >= bottom
                assert composer.property('desiredOpen')
            pet.assistantSpeech.emit('')
            window.setPosition(350, 250); QTest.qWait(80)
            assert window.grabWindow().save(str(out / 'drag-pet.png'))
            assert native.grabWindow().save(str(out / 'drag-composer.png'))
            QTest.keyClick(native, Qt.Key_Escape)
            wait(lambda: not composer.property('visible'), 'Escape did not close')
        traces[str(opened)] = trace
    (out / 'drag-result.json').write_text(json.dumps(traces, indent=2))
    print('Global drag regression passed', traces)
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
    app.processEvents()
    temporary.cleanup()
