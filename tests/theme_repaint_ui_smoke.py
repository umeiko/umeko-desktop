"""Theme frames and retained chat state; --native uses the platform GPU renderer.

Frame progress is checked before any grabWindow(), which itself forces rendering.
Passing this smoke does not reproduce a machine-specific display driver failure.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
profile = tempfile.TemporaryDirectory(prefix='umeko-theme-repaint-', ignore_cleanup_errors=True)
base = Path(profile.name)
os.environ.update(UMEKO_DATA_DIR=str(base/'profile'), UMEKO_LANGUAGE='zh',
                  PI_CODING_AGENT_DIR=str(base/'agent'))
if '--native' not in sys.argv:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ.setdefault('QT_QUICK_BACKEND', 'software')

from PySide6.QtCore import Q_ARG, QMetaObject, QPointF, Qt
from PySide6.QtTest import QTest
import shiboken6
from main import create_application

app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings, frames = [], []
engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
window.frameSwapped.connect(lambda: frames.append(time.monotonic()))


def items(root=None):
    stack = [root or window.contentItem()]
    while stack:
        item = stack.pop()
        yield item
        stack.extend(item.childItems())


def find(name, root=None):
    return next(item for item in items(root) if item.objectName() == name)


def wait(check, label):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        QTest.qWait(20)
        if check():
            return
    raise AssertionError(label + ': ' + '\n'.join(warnings[:5]))


try:
    backend.setCharacterEnabled(False)
    history = base/'history.jsonl'
    with history.open('w', encoding='utf-8') as output:
        for index in range(120):
            output.write(json.dumps({'type': 'message', 'id': str(index),
                'parentId': str(index-1) if index else None,
                'message': {'role': 'user' if index % 2 == 0 else 'assistant',
                            'content': f'Message {index}\n\n' + 'Theme repaint keeps this history. '*12}}) + '\n')
    backend._sessions = [{'id': 'theme-history', 'file': str(history),
                          'title': 'Theme history', 'workspace': str(base)}]
    backend.sessionPreview.prepare('theme-history', 1)
    wait(lambda: backend.sessionPreview.prepared is not None, 'prepare history')
    assert backend.sessionPreview.activate(1)
    view = find('conversation')
    wait(lambda: not view.property('restoring'), 'initial restore')
    assert QMetaObject.invokeMethod(view, 'jumpToMessage', Qt.DirectConnection, Q_ARG('QVariant', 40))
    wait(lambda: not view.property('restoring') and
         any(item.objectName() == 'messageBubble_40' for item in items(view)), 'anchor loaded')
    QTest.qWait(500)
    anchor = find('messageBubble_40', view)
    anchor_y = anchor.mapToItem(view, QPointF()).y()
    anchor_id = shiboken6.getCppPointer(anchor)[0]
    prompt = find('promptInput')
    prompt.setProperty('text', 'Unsent theme-switch draft')
    prompt.setProperty('cursorPosition', 7)
    model = backend.messageModel
    initial_geometry = window.geometry()
    initial_session = backend.activeSession

    def verify_state():
        assert find('conversation') is view and backend.messageModel is model
        assert backend.activeSession == initial_session
        current = find('messageBubble_40', view)
        assert shiboken6.getCppPointer(current)[0] == anchor_id, 'theme recreated the chat body'
        assert abs(current.mapToItem(view, QPointF()).y() - anchor_y) < 2, 'theme moved the scroll anchor'
        assert prompt.property('text') == 'Unsent theme-switch draft'
        assert prompt.property('cursorPosition') == 7
        assert window.geometry() == initial_geometry

    def rendered(change):
        before = len(frames)
        change()
        wait(lambda: len(frames) > before, 'theme did not present a frame')
        QTest.qWait(80)
        verify_state()

    for _ in range(3):
        for theme in ('dark', 'light', 'yanami', 'white'):
            rendered(lambda: backend.setTheme(theme))
    # A custom palette can change without changing the window background or ID.
    custom = base/'theme.json'
    theme = {'format': 'umeko-theme', 'version': 1, 'id': 'repaint',
             'name': 'Repaint', 'base': 'white', 'colors': {'ink': '#183850'}}

    def import_theme():
        custom.write_text(json.dumps(theme), encoding='utf-8')
        assert backend.importTheme(str(custom))

    rendered(import_theme)
    assert window.color().name() == '#ffffff'
    theme['colors']['ink'] = '#501838'
    rendered(import_theme)
    assert window.color().name() == '#ffffff'
    rendered(lambda: backend.removeTheme('custom:repaint'))

    def rapid_switch():
        for theme in ('dark', 'yanami', 'light', 'white') * 5:
            backend.setTheme(theme)

    rendered(rapid_switch)
    assert window.color().name() == '#ffffff'
    # Changes while minimized/hidden must survive the next normal exposure.
    window.hide()
    backend.setTheme('dark')
    QTest.qWait(100)
    rendered(window.show)
    assert window.color().name() == '#191c1b'
    assert not window.grabWindow().isNull()
    assert not warnings, '\n'.join(warnings)
    print('THEME_REPAINT_UI_OK: builtins, custom same-background update/delete, rapid switching, '
          'hidden restore, frame progress, draft/cursor/history/anchor retained; '
          + str(window.rendererInterface().graphicsApi()), flush=True)
finally:
    backend.close()
    window.hide()
    shiboken6.delete(engine)
    profile.cleanup()
