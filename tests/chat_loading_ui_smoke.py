"""Immediate cover, responsive cold reads, latest-click wins, and cancellation."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['UMEKO_DATA_DIR'] = tempfile.mkdtemp(prefix='umeko-loading-ui-')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from main import create_application
from app.transcripts import preview

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

def click(name):
    item = find(name)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier,
                     item.mapToScene(item.boundingRect().center()).toPoint())

def wait_for(predicate, label):
    for _ in range(300):
        QTest.qWait(10)
        if predicate():
            return
    raise AssertionError(label)

gate = threading.Event()
try:
    # No model/network is needed to present a native transcript.
    backend._sessions = []
    for i in range(5):
        path = Path(os.environ['UMEKO_DATA_DIR']) / f'{i}.jsonl'
        path.write_text(json.dumps({'type': 'message', 'id': f'm{i}', 'message': {
            'role': 'user', 'content': [{'type': 'text', 'text': f'Conversation {i}'}]
        }}) + '\n', encoding='utf-8')
        backend._sessions.append({'id': str(i), 'title': f'Conversation {i}', 'file': str(path), 'workspace': ''})
    backend.openSession('0')
    QTest.qWait(1300)
    cover = find('chatLoadingOverlay')
    reads, ready = [], []
    backend.sessionPreview.ready.connect(lambda token, ok: ready.append((token, ok)))
    def slow_read(path):
        reads.append(Path(path).stem)
        if len(reads) == 1:
            assert gate.wait(8), 'Test failed to release reader'
        return preview(path)
    ticks = []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    with patch('app.session_preview.preview', side_effect=slow_read):
        click('sidebarRow_1')
        assert cover.isVisible() and cover.opacity() == 1, 'Old chat was not covered immediately'
        assert backend.activeSession == '0'
        wait_for(lambda: bool(reads), 'Background read never started')
        wait_for(lambda: cover.property('artworkLoaded'), 'Approved image did not load')
        before = len(ticks)
        QTest.qWait(140)
        assert len(ticks) - before >= 4, 'Disk I/O blocked the UI event loop'
        assert cover.isVisible() and cover.opacity() == 1
        click('sidebarRow_2')
        QTest.qWait(60)
        click('sidebarRow_3')
        QTest.qWait(100)
        assert reads == ['1'], 'Rapid switching started extra parallel readers'
        assert backend.activeSession == '0'
        out = ROOT / 'artifacts/screenshots'
        out.mkdir(parents=True, exist_ok=True)
        assert window.grabWindow().save(str(out / 'chat-loading.png'))
        gate.set()
        wait_for(lambda: backend.activeSession == '3', 'Latest selection did not activate')
        assert reads == ['1', '3'], reads
        assert len(ready) == 1 and ready[0][1], 'Stale completion was delivered'
        assert backend.messages[-1]['text'] == 'Conversation 3'
        assert cover.isVisible(), 'Cover disappeared before layout/fade'
        wait_for(lambda: 0 < cover.opacity() < 1, 'No fade between cover and chat')
        wait_for(lambda: not cover.isVisible(), 'Cover remained after completion')

    # Cached switching and leaving for settings both retire pending work.
    click('sidebarRow_0')
    assert cover.isVisible()
    wait_for(lambda: backend.activeSession == '0' and not cover.isVisible(), 'Warm switch stayed covered')
    gate.clear()
    reads.clear()
    with patch('app.session_preview.preview', side_effect=slow_read):
        click('sidebarRow_4')
        wait_for(lambda: bool(reads), 'Cancel test read never started')
        window.setProperty('page', 'settings')
        assert not cover.property('loading') and not window.property('sidebarSwitching')
        gate.set()
        QTest.qWait(250)
        assert backend.activeSession == '0', 'Cancelled read changed chat'
    window.setProperty('page', 'chat')
    with patch('app.session_preview.preview', side_effect=OSError('fixture read failure')):
        click('sidebarRow_4')
        wait_for(lambda: not window.property('sidebarSwitching') and not cover.isVisible(), 'Failed read stayed covered')
        assert backend.activeSession == '0'
    assert not warnings, '\n'.join(warnings)
    print('CHAT_LOADING_UI_OK: immediate cover, live event loop, latest-only read, fade, cancel and failure recovery')
finally:
    gate.set()
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
