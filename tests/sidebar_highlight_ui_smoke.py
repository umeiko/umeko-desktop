"""Sidebar refreshes must never animate via the transient first-row selection."""
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['UMEKO_DATA_DIR'] = tempfile.mkdtemp(prefix='umeko-highlight-ui-')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
os.environ['PI_OFFLINE'] = '1'
from PySide6.QtCore import QObject, QPointF
from PySide6.QtTest import QTest
from main import create_application

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


def aligned(identifier):
    row = find('sidebarRow_' + identifier)
    assert view.property('currentItem') is row, 'Model reset lost the actual selected row'
    assert abs(highlight.mapToScene(QPointF()).y() - row.mapToScene(QPointF()).y()) < .2
    assert abs(highlight.height() - row.height()) < .2


try:
    workspace = os.environ['UMEKO_DATA_DIR']
    backend.store.data['projects'] = [{'id': 'project', 'name': 'Fixture', 'path': workspace}]
    backend._sessions = [{'id': str(i), 'title': f'Fixture {i}', 'workspace': workspace} for i in range(32)]
    backend._view.id = '24'
    backend.chatChanged.emit()
    QTest.qWait(1300)
    # Behaviors instantiate their animation lazily; exercise a real selection
    # before observing subsequent resets of an unchanged selection.
    backend._view.id = '23'
    backend.chatChanged.emit()
    QTest.qWait(250)
    backend._view.id = '24'
    backend.chatChanged.emit()
    QTest.qWait(250)
    view, highlight = find('projectList'), find('sidebarHighlight')
    animator = window.findChild(QObject, 'sidebarSelectionAnimator')
    aligned('24')
    positions, starts = [], []
    highlight.yChanged.connect(lambda: positions.append(highlight.y()))
    animator.runningChanged.connect(lambda: starts.append(highlight.y()) if animator.property('running') else None)
    expected = highlight.y()
    # A title or status update replaces QVariantList delegates. Even without
    # changing selection this used to reset y to zero and restart the animator.
    for turn in range(6):
        backend._sessions[3]['title'] = f'Background update {turn}'
        backend.chatChanged.emit()
        QTest.qWait(230)
        aligned('24')
    assert not starts, ('Unchanged selection restarted its animation', starts, positions)
    assert all(abs(y - expected) < .2 for y in positions), ('Highlight flashed at another row', positions)
    # Scrolling must move the highlight with its row, without a new animation.
    view.setProperty('contentY', max(view.property('originY'), view.property('contentY') - 55))
    QTest.qWait(30)
    aligned('24')
    assert not animator.property('running'), 'Scrolling animated the highlight separately from its row'
    # No selection may hide the highlight; restoring it must retain its position.
    saved = backend._sessions
    backend._sessions = []
    backend.chatChanged.emit()
    QTest.qWait(30)
    assert not highlight.isVisible()
    backend._sessions = saved
    backend.chatChanged.emit()
    QTest.qWait(230)
    aligned('24')
    assert all(abs(y - expected) < .2 for y in positions), ('Hidden highlight reset its position', positions)
    # Different row heights and a genuine selection change still align exactly.
    backend._view.id = '20'
    backend.chatChanged.emit()
    QTest.qWait(250)
    aligned('20')
    assert all(y > 100 for y in positions), ('Selection animation visited the top', positions)
    assert not warnings, '\n'.join(warnings)
    print('SIDEBAR_HIGHLIGHT_UI_OK: background refresh, model reset, scrolling, hide/restore and selection change')
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
