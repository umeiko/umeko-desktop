"""Mouse-only edge visibility across disabled covers and actual chat switches."""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['UMEKO_DATA_DIR'] = tempfile.mkdtemp(prefix='umeko-edge-hover-')
os.environ['UMEKO_LANGUAGE'] = 'zh'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QCursor
from app.storage import Store
from main import create_application

store = Store()
store.data['agent']['agentDir'] = str(store.directory / 'agent')
store.save()
app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))


def find(name):
    stack = [window.contentItem()]
    while stack:
        item = stack.pop()
        if item.objectName() == name:
            return item
        stack.extend(item.childItems())
    raise AssertionError(name)


def wait_for(predicate, label):
    for _ in range(200):
        QTest.qWait(10)
        if predicate():
            return
    raise AssertionError(label + ' ' + str(states()) + f' window={window.geometry()} screen={window.screen().availableGeometry()} cursor={QCursor.pos()}')


def states():
    return [{key: button.property(key) for key in ('opacity', 'nearby', 'hovered', 'visualFocus', 'enabled')}
            for button in (left, right)]


def move(item):
    QTest.mouseMove(window, item.mapToScene(item.boundingRect().center()).toPoint())


def hidden():
    wait_for(lambda: left.opacity() < .01 and right.opacity() < .01, 'Stale edge visibility')


try:
    window.resize(1800, 980)
    window.requestActivate()
    QTest.qWait(350)
    backend._sessions = []
    for i in range(3):
        path = store.directory / f'hover-{i}.jsonl'
        path.write_text(json.dumps({'type': 'message', 'id': f'm{i}', 'message': {
            'role': 'user', 'content': [{'type': 'text', 'text': f'Hover conversation {i}'}]
        }}) + '\n', encoding='utf-8')
        backend._sessions.append({'id': str(i), 'title': f'Hover conversation {i}', 'file': str(path), 'workspace': ''})
    backend.openSession('0')
    QTest.qWait(250)
    controls = find('chatWidthControls')
    left, right = find('expandChatLeft'), find('expandChatRight')
    prompt = find('promptInput')
    assert controls.property('expandable')

    # The full empty gutter reveals its own edge, including far above/below
    # the mascot. Returning to the actual chat/input column hides both.
    for side, edge, other in (('Left', left, right), ('Right', right, left)):
        zone = find('chatWidth' + side + 'HoverZone')
        for x, y in ((12, 16), (zone.width() - 12, 16), (zone.width() / 2, zone.height() - 16)):
            QTest.mouseMove(window, zone.mapToScene(QPointF(x, y)).toPoint())
            wait_for(lambda: edge.opacity() > .95 and other.opacity() < .01, 'Gutter did not reveal ' + side)
        move(prompt)
        hidden()

    # A cover disables the items while the pointer leaves; no local exit event
    # is guaranteed to be delivered before the same items are enabled again.
    move(left)
    wait_for(lambda: left.opacity() > .95, 'Left edge not revealed')
    controls.setEnabled(False)
    move(prompt)
    QTest.qWait(80)
    controls.setEnabled(True)
    hidden()

    # A remembered focus reason must not keep a mascot visible once the user
    # resumes pointing elsewhere, even if the focused button receives no click.
    left.forceActiveFocus(Qt.TabFocusReason)
    move(left)
    wait_for(lambda: left.opacity() > .95, 'Focused edge not revealed')
    move(prompt)
    hidden()

    # Repeated genuine sidebar switches use the loading cover and replace the
    # transcript. Do not send another mouse move after the cover disappears.
    for i in range(6):
        edge = left if i % 2 == 0 else right
        other = right if edge is left else left
        move(edge)
        wait_for(lambda: edge.opacity() > .95 and other.opacity() < .01, f'Wrong edge revealed at switch {i}')
        target = str((i + 1) % 3)
        row = find('sidebarRow_' + target)
        move(row)
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, row.mapToScene(row.boundingRect().center()).toPoint())
        wait_for(lambda: backend.activeSession == target and not find('chatLoadingOverlay').isVisible(), 'Chat switch failed')
        hidden()
        move(prompt)
        hidden()

    move(right)
    wait_for(lambda: right.opacity() > .95, 'Right edge not revealed after switching')
    window.setProperty('page', 'settings')
    move(find('settingsButton'))
    window.setProperty('page', 'chat')
    hidden()
    move(left)
    wait_for(lambda: left.opacity() > .95, 'Left edge not revealed after settings')
    window.resize(1060, 760)
    move(prompt)
    window.resize(1800, 980)
    QTest.qWait(250)
    hidden()
    move(right)
    wait_for(lambda: right.opacity() > .95, 'Right edge not revealed after resizing')
    QTest.mouseMove(window, QPoint(-20, -20))
    hidden()
    assert not warnings, '\n'.join(warnings)
    print('CHAT_WIDTH_HOVER_UI_OK: disabled cover, six chat switches, each edge, settings, resize and window exit')
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
