"""Delayed cover without fade, responsive cold reads, latest-click wins, warm switches, lazy settings and cancellation."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('UMEKO_LANGUAGE','zh')
os.environ['UMEKO_DATA_DIR'] = tempfile.mkdtemp(prefix='umeko-loading-ui-')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import Qt, QTimer
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

def find_object(name):
    stack = [window.contentItem()]
    while stack:
        item = stack.pop()
        if item.objectName() == name:
            return item
        stack.extend(item.childItems())
    return None

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
    for i in range(6):
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
    read_transcript = backend.transcripts.open
    def slow_read(path, **kwargs):
        reads.append(Path(path).stem)
        if len(reads) == 1:
            assert gate.wait(8), 'Test failed to release reader'
        return read_transcript(path, **kwargs)
    ticks = []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    def watch_cover(seconds):
        # Every sampled state: drawn cover is fully opaque (no fade frames).
        samples, end = [], time.monotonic() + seconds
        while time.monotonic() < end:
            QTest.qWait(5)
            samples.append((cover.property('shown'), round(cover.opacity(), 3), window.property('sidebarSwitching')))
        return samples

    with patch.object(backend.transcripts, 'open', side_effect=slow_read):
        click('sidebarRow_1')
        # The old chat stays on screen for the first moments of a slow load,
        # with input held by the still transparent cover.
        assert cover.isVisible() and not cover.property('shown') and cover.opacity() == 0, 'Cover drew before its delay'
        assert backend.activeSession == '0'
        wait_for(lambda: bool(reads), 'Background read never started')
        wait_for(lambda: cover.property('shown') and cover.opacity() == 1, 'Slow load never showed the cover')
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
        assert backend.displayMessage(0)['text'] == 'Conversation 3'
        # Index handoff reveals lightweight local placeholders immediately.
        wait_for(lambda: not cover.isVisible(), 'Cover remained after completion')

    # Cached switching never draws the cover at all.
    click('sidebarRow_0')
    samples = watch_cover(0.4)
    assert not any(shown for shown, _, _ in samples), 'Retained view flashed the loading cover'
    wait_for(lambda: backend.activeSession == '0' and not cover.isVisible(), 'Warm switch stayed covered')
    # A first open that finishes within the delay never draws the cover. The
    # delay is widened here so the check does not depend on machine speed.
    cover.setProperty('showDelay', 5000)
    click('sidebarRow_5')
    samples = watch_cover(1.5)
    cover.setProperty('showDelay', 150)
    assert backend.activeSession == '5' and not cover.isVisible(), 'Fast first open did not finish'
    assert not any(shown for shown, _, _ in samples), 'Fast first open drew the cover'
    host = find('conversationHost')
    assert not host.property('revealPending') and host.property('heldPane') is None
    click('sidebarRow_0')
    wait_for(lambda: backend.activeSession == '0' and not cover.isVisible(), 'Return to retained view failed')
    # A drawn cover leaves in one step: no partially transparent frames.
    gate.clear()
    reads.clear()
    with patch.object(backend.transcripts, 'open', side_effect=slow_read):
        click('sidebarRow_2')
        wait_for(lambda: cover.property('shown'), 'Slow load never showed the cover')
        gate.set()
        samples = watch_cover(0.8)
        assert backend.activeSession == '2' and not cover.isVisible(), 'Covered load did not finish'
        assert {opacity for _, opacity, _ in samples} <= {0.0, 1.0}, samples
    click('sidebarRow_0')
    wait_for(lambda: backend.activeSession == '0' and not cover.isVisible(), 'Return to retained view failed')
    # Settings are built after the first frame and are ready before first use.
    wait_for(lambda: find_object('settingsPage') is not None, 'Settings were not preloaded')
    assert not find_object('settingsPage').isVisible()
    window.setProperty('page', 'settings')
    assert find_object('settingsPage').isVisible()
    window.setProperty('page', 'chat')
    gate.clear()
    reads.clear()
    with patch.object(backend.transcripts, 'open', side_effect=slow_read):
        click('sidebarRow_4')
        wait_for(lambda: bool(reads), 'Cancel test read never started')
        window.setProperty('page', 'settings')
        assert not cover.property('loading') and not window.property('sidebarSwitching')
        gate.set()
        QTest.qWait(250)
        assert backend.activeSession == '0', 'Cancelled read changed chat'
    window.setProperty('page', 'chat')
    with patch.object(backend.transcripts, 'open', side_effect=OSError('fixture read failure')):
        click('sidebarRow_4')
        wait_for(lambda: not window.property('sidebarSwitching') and not cover.isVisible(), 'Failed read stayed covered')
        assert backend.activeSession == '0'
    assert not warnings, '\n'.join(warnings)
    print('CHAT_LOADING_UI_OK: delayed opaque cover, live event loop, latest-only read, local placeholders, uncovered warm and fast switches, preloaded settings, cancel and failure recovery')
finally:
    gate.set()
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
