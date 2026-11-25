"""Rail clicks navigate paged chat and keep the indicator/label in sync."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
base = Path(tempfile.mkdtemp(prefix='umeko-question-rail-'))
os.environ['UMEKO_DATA_DIR'] = str(base / 'profile')
os.environ['PI_CODING_AGENT_DIR'] = str(base / 'agent')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
os.environ.setdefault('UMEKO_LANGUAGE', 'zh')

from PySide6.QtCore import Q_ARG, QCoreApplication, QMetaObject, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from main import create_application

count = 3000
transcript = base / 'history.jsonl'
with transcript.open('w', encoding='utf-8') as out:
    out.write(json.dumps({'type': 'session', 'id': 'rail', 'cwd': str(base)}) + '\n')
    for i in range(count * 2):
        out.write(json.dumps({'type': 'message', 'id': f'm{i}',
                             'parentId': f'm{i-1}' if i else None,
                             'message': {'role': 'user' if i % 2 == 0 else 'assistant',
                                         'content': f'Question {i // 2}' if i % 2 == 0 else 'Answer paragraph.\n\n' * 10}}) + '\n')

app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))


def find(name):
    pending = [window.contentItem()]
    while pending:
        item = pending.pop()
        if item.objectName() == name:
            return item
        pending.extend(item.childItems())
    return None


def wait(predicate, label):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        QTest.qWait(10)
        time.sleep(.001)  # Let the transcript reader release/obtain the GIL.
        if predicate():
            return
    raise AssertionError((label, warnings, backend.activeSession, backend.messageCount, backend.messageModel.questionCount, backend.sessionPreview.request, backend.sessionPreview.reading, backend.sessionPreview.direct_token))


def visible(index):
    listing = find('questionNavigationList')
    item = find(f'questionNavigationItem_{index}')
    return listing is not None and item is not None and listing.boundingRect().contains(
        item.mapToItem(listing, item.boundingRect().center()))


def tap(ratio):
    rail = find('questionNavigatorRail')
    pos = rail.mapToScene(QPointF(rail.width() / 2, 1 + ratio * (rail.height() - 2))).toPoint()
    QTest.mouseMove(window, pos)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, pos)
    local_y = rail.mapFromScene(QPointF(pos)).y()
    return int(max(0, min(1, (local_y - 1) / (rail.height() - 2))) * (count - 1) + .5)


try:
    backend._sessions = [{'id': 'rail', 'file': str(transcript), 'title': 'Rail fixture', 'workspace': str(base)}]
    backend.chatChanged.emit()
    backend.openSession('rail')
    wait(lambda: backend.messageModel.questionCount == count, 'indexed history')
    view = find('conversation')
    nav = find('questionNavigator')
    QMetaObject.invokeMethod(view, 'jumpToMessage', Q_ARG('QVariant', 2 * (count - 1)))
    wait(lambda: not view.property('restoring'), 'tail ready')
    QTest.qWait(300)
    def destination_ready(index):
        if view.property('restoring') or view.property('restoreIndex') != index * 2:
            return False
        bubble = find(f'messageBubble_{index * 2}')
        if bubble is None:
            return False
        y = bubble.mapToItem(view, QPointF()).y()
        # Native navigation may keep neighboring rows anchored during polish.
        return y >= -4 and y + min(bubble.height(), view.height()) <= view.height() + 4

    def check_selection(index):
        assert nav.property('activeQuestion') == index
        item = find(f'questionNavigationItem_{index}')
        assert item is not None and item.property('highlighted'), index
        rail, indicator = find('questionNavigatorRail'), find('questionNavigatorIndicator')
        expected = index * (rail.height() - indicator.height()) / (count - 1)
        assert abs(indicator.y() - expected) < .1, (indicator.y(), expected)

    # Hovering opens only the preview, without changing the chat viewport.
    chat_y, follow_tail = view.property('contentY'), view.property('followTail')
    rail = find('questionNavigatorRail')
    QTest.mouseMove(window, rail.mapToScene(rail.boundingRect().center()).toPoint())
    wait(lambda: nav.property('expanded'), 'hover opens preview')
    assert view.property('contentY') == chat_y and view.property('followTail') == follow_tail
    QTest.mouseMove(window, view.mapToScene(QPointF(40, 40)).toPoint())
    wait(lambda: not nav.property('expanded'), 'hover preview closes')
    QTest.qWait(120)
    started = time.perf_counter()
    target = tap(0)  # Click before the pending 90 ms hover timer fires.
    wait(lambda: visible(target) and destination_ready(target), 'first rail jump')
    cold = time.perf_counter() - started
    QTest.qWait(150)
    check_selection(target)
    assert view.property('contentY') != chat_y
    timings = []
    for ratio in (.5, 1, .25, .75, 0):
        started = time.perf_counter()
        target = tap(ratio)
        wait(lambda: visible(target) and destination_ready(target), f'rail jump {target}')
        timings.append(round((time.perf_counter() - started) * 1000, 1))
        QTest.qWait(120)  # The active-position timer must not undo selection.
        check_selection(target)
        assert not view.property('followTail')
    # Scrolling the preview is still passive, even after a direct rail jump.
    chat_y = view.property('contentY')
    listing = find('questionNavigationList')
    preview_y = listing.property('contentY')
    pos = listing.mapToScene(listing.boundingRect().center()).toPoint()
    QTest.mouseMove(window, pos)
    wheel = QWheelEvent(QPointF(pos), QPointF(window.mapToGlobal(pos)), QPoint(), QPoint(0, -120),
                        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QCoreApplication.sendEvent(window, wheel)
    wait(lambda: listing.property('contentY') > preview_y, 'preview wheel still works')
    assert view.property('contentY') == chat_y
    assert nav.property('activeQuestion') == target
    tap(.2)
    tap(.9)
    target = tap(.4)
    wait(lambda: visible(target) and destination_ready(target), 'last rapid jump wins')
    QTest.qWait(150)
    check_selection(target)
    # Clicking another visible label still jumps to its exact message.
    target += 1
    item = find(f'questionNavigationItem_{target}')
    pos = item.mapToScene(item.boundingRect().center()).toPoint()
    QTest.mouseMove(window, pos)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, pos)
    wait(lambda: destination_ready(target), 'label navigates actual chat')
    QTest.qWait(150)
    check_selection(target)
    # Ordinary chat scrolling releases the explicit selection and tracks location.
    pos = view.mapToScene(QPointF(40, 40)).toPoint()
    QTest.mouseMove(window, pos)
    wheel = QWheelEvent(QPointF(pos), QPointF(window.mapToGlobal(pos)), QPoint(), QPoint(0, -1200),
                        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QCoreApplication.sendEvent(window, wheel)
    wait(lambda: nav.property('selectedQuestion') == -1, 'chat scrolling releases selection')
    QTest.mouseMove(window, rail.mapToScene(rail.boundingRect().center()).toPoint())
    wait(lambda: nav.property('activeQuestion') != target, 'indicator tracks chat scrolling again')
    assert backend.transcripts.cache.weight <= backend.transcripts.cache.limit
    print('RAIL_DIRECT_JUMP_OK: 3000 paged questions, cold ms', round(cold * 1000, 1),
          'repeat ms', timings, 'platform', app.platformName(), flush=True)
    backend.newSession()
    wait(lambda: not nav.isVisible() and not nav.property('expanded'), 'empty history dismisses preview')
    assert not warnings, warnings
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
