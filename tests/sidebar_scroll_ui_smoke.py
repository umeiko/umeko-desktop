"""Keep a below-fold sidebar selection in view across model refreshes."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['UMEKO_DATA_DIR'] = tempfile.mkdtemp(prefix='umeko-sidebar-scroll-')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
os.environ['UMEKO_LANGUAGE'] = 'zh'
os.environ['PI_OFFLINE'] = '1'
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtTest import QTest
from main import create_application
from app.storage import Store
store = Store()
store.data["agent"]["agentDir"] = str(store.directory / "agent")
store.save()

app, engine, backend = create_application()
window = engine.rootObjects()[0]

def find(name):
    stack = [window.contentItem()]
    while stack:
        item = stack.pop()
        if item.objectName() == name:
            return item
        stack.extend(item.childItems())
    return None

def wait(predicate, label, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
        if predicate():
            return
    raise AssertionError(label)

def settle():
    end = time.monotonic() + .8
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(.005)

def capture(name):
    dest = ROOT / 'artifacts/sidebar-scroll' / (os.environ.get('SCROLL_LABEL', 'candidate') + '-' + name + '.png')
    dest.parent.mkdir(parents=True, exist_ok=True)
    assert window.grabWindow().save(str(dest))

try:
    workspace = Path(os.environ['UMEKO_DATA_DIR']) / 'workspace'
    workspace.mkdir()
    project = backend._ensure_project(str(workspace))
    backend._sessions = [{'id': f'scroll-{i:02d}', 'title': f'滚动回归演示 {i:02d}',
                          'file': '', 'workspace': str(workspace),
                          'messages': [{'role': 'user', 'text': f'这是合成会话 {i:02d}，不含真实聊天数据。'}]}
                         for i in range(64)]
    backend._activate(backend._new_view(str(workspace)))
    wait(lambda: find('sidebarRow_scroll-00') is not None, 'fixture sidebar loaded')
    view = find('projectList')
    view.positionViewAtEnd()
    settle()
    before = view.property('contentY')
    capture('before')
    row = find('sidebarRow_scroll-63')
    assert row is not None
    point = row.mapToScene(row.boundingRect().center()).toPoint()
    assert view.mapToScene(QPointF()).y() < point.y() < view.mapToScene(QPointF(0, view.height())).y()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    wait(lambda: backend._view.id == 'scroll-63', 'real sidebar activation')
    settle()
    after = view.property('contentY')
    animator = window.findChild(QObject, 'sidebarSelectionAnimator')
    wait(lambda: not animator.property('running'), 'selection highlight settles')
    selected = find('sidebarRow_scroll-63')
    highlight = find('sidebarHighlight')
    assert highlight.isVisible()
    assert abs(highlight.mapToScene(QPointF()).y() - selected.mapToScene(QPointF()).y()) <= 1, (highlight.y(),selected.y(),highlight.mapToScene(QPointF()).y(),selected.mapToScene(QPointF()).y())
    capture('after')
    print(json.dumps({'before': before, 'after': after, 'selected': backend._view.id, 'originY': view.property('originY'), 'height': view.height(), 'contentHeight': view.property('contentHeight')}), flush=True)
    assert abs(after-before) <= 1, ('selection moved sidebar', before, after)
    def bounds():
        low = view.property('originY')
        high = low + max(0, view.property('contentHeight') - view.height())
        assert low - 1 <= view.property('contentY') <= high + 1
    def visible(identifier):
        row = find('sidebarRow_' + identifier)
        assert row is not None, identifier
        top = row.mapToScene(QPointF()).y()
        viewport_top = view.mapToScene(QPointF()).y()
        assert top >= viewport_top - 1 and top + row.height() <= viewport_top + view.height() + 1
        return row
    def choose(identifier):
        row = visible(identifier)
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier,
                         row.mapToScene(row.boundingRect().center()).toPoint())
    visible('scroll-63')
    assert view.property('currentItem') is find('sidebarRow_scroll-63')
    # Repeated bottom selections and rapid newer navigation retain the viewport.
    for identifier in ('scroll-62', 'scroll-61', 'scroll-63'):
        before = view.property('contentY')
        choose(identifier)
        wait(lambda: backend._view.id == identifier, 'repeat activation')
        settle()
        assert abs(view.property('contentY') - before) <= 1, (before, view.property('contentY'), view.property('originY'))
        visible(identifier)
        bounds()
    before = view.property('contentY')
    choose('scroll-62')
    choose('scroll-61')
    wait(lambda: backend._view.id == 'scroll-61', 'newer selection wins')
    settle()
    assert abs(view.property('contentY') - before) <= 1, (before, view.property('contentY'), view.property('originY'))
    # Middle viewport and several queued model updates, without selection changes.
    view.setProperty('contentY', 900)
    settle()
    before = view.property('contentY')
    choose('scroll-30')
    wait(lambda: backend._view.id == 'scroll-30', 'middle selection')
    settle()
    assert abs(view.property('contentY') - before) <= 1, (before, view.property('contentY'), view.property('originY'))
    anchor = find('sidebarRow_scroll-30').mapToScene(QPointF()).y()
    for turn in range(5):
        backend._sessions[3]['title'] = f'后台标题更新 {turn}'
        backend.chatChanged.emit()
    settle()
    assert abs(view.property('contentY') - before) <= 1, (before, view.property('contentY'), view.property('originY'))
    # A new row above the viewport must preserve the same visible content.
    backend._sessions.insert(0, {'id': 'new-first', 'title': '新增合成会话',
                                'file': '', 'workspace': str(workspace)})
    backend.chatChanged.emit()
    settle()
    assert abs(find('sidebarRow_scroll-30').mapToScene(QPointF()).y() - anchor) <= 1
    bounds()
    # Deleted anchors and a shortened/empty model clamp to real bounds.
    backend._sessions = backend._sessions[:6]
    backend.chatChanged.emit()
    settle()
    bounds()
    backend._sessions = []
    backend.store.data['projects'] = []
    backend.chatChanged.emit()
    settle()
    bounds()
    print('SIDEBAR_SCROLL_UI_OK: 64 sessions, bottom/middle/repeated/rapid selection, background resets, insertion, shrink and empty model', flush=True)
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
