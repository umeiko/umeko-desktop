"""A long unindexed chat opens at its latest messages; earlier ones join above.

Before the complete index exists the view shows the latest messages, row for
row as the complete index ends, with the question list held back. Staying at
the latest message, the earlier rows are inserted above without a reset.
Scrolling to the top of the partial history shows a loading row, then the
earlier rows appear above the message that was on screen.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
os.environ.setdefault('UMEKO_LANGUAGE', 'zh')
os.environ['UMEKO_DATA_DIR'] = tempfile.mkdtemp(prefix='umeko-recent-history-')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QMetaObject, Q_ARG, Qt
from main import create_application
from app.transcript_index import RECENT_BYTES, TranscriptRepository
from test_recent_history import Conversation, compaction

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
    return None


def pause(ms):
    # QTest.qWait keeps the interpreter lock; the index is built on a thread.
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def wait_for(predicate, label, seconds=30):
    for _ in range(seconds * 100):
        pause(10)
        if predicate():
            return
    raise AssertionError(label)


def first_visible(view):
    top, best = view.property('contentY'), None
    for item in view.property('contentItem').childItems():
        if item.property('messageSlot') is True and item.property('y') + item.property('height') > top and item.property('y') < top + view.property('height'):
            if best is None or item.property('index') < best[0]:
                best = (item.property('index'), round(item.property('y') - top))
    return best


data = Path(os.environ['UMEKO_DATA_DIR'])
sessions = []
for name in ('a', 'b'):
    chat = Conversation(data / f'{name}.jsonl')
    chat.turns(380, branch=True, subagents=True)
    chat.add(compaction('start-' + name, chat.parent, 'running', event='event-' + name))
    chat.add(compaction('finish-' + name, chat.parent, 'success', event='event-' + name))
    chat.turns(20, subagents=True)
    chat.write()
    assert chat.path.stat().st_size > 4 * RECENT_BYTES, chat.path.stat().st_size
    sessions.append({'id': name, 'title': 'Conversation ' + name, 'file': str(chat.path), 'workspace': ''})
expected = {row['id']: TranscriptRepository(data / 'expected-index').open(row['file']) for row in sessions}
backend._sessions = sessions
pause(300)


def displayed(model):
    # The rows the view pages in, from the snapshot the model shows.
    return [model.snapshot.row(row) for row in range(model.base_count)]


def rows(snapshot, first=0):
    return [snapshot.row(row) for row in range(first, snapshot.count)]


try:
    # 1. Stay at the latest message while the complete index is built.
    model_resets = []
    backend.openSession('a')
    wait_for(lambda: backend.activeSession == 'a' and backend.messageModel.partialHistory, 'Partial history did not open')
    model = backend.messageModel
    model.modelReset.connect(lambda: model_resets.append(1))
    full = expected['a']
    recent_count = model.rowCount()
    assert 0 < recent_count < full.count // 4, (recent_count, full.count)
    assert model.questionCount == 0, 'Question list appeared before the complete index'
    assert displayed(model) == rows(full, full.count - recent_count), 'Latest messages differ from the complete index'
    inserted = []
    model.rowsInserted.connect(lambda parent, first, last: inserted.append((first, last)))
    wait_for(lambda: not model.partialHistory, 'Complete history did not arrive')
    view = window.property('conversation')
    assert not model_resets, 'Completing the history reset the view'
    assert inserted[0] == (0, full.count - recent_count - 1), inserted
    assert model.rowCount() == full.count and model.questionCount == full.question_count
    assert displayed(model) == rows(full), 'Complete history differs from the index'
    wait_for(lambda: view.property('atYEnd'), 'View left the latest message')

    # 2. Scroll to the top of the partial history before it is complete. The
    # complete index waits until the loading row has been checked.
    gate = threading.Event()
    build = backend.transcripts.open
    def gated(path, **values):
        if threading.current_thread().name.startswith('transcript-history'):
            assert gate.wait(30), 'Test did not release the index'
        return build(path, **values)
    backend.transcripts.open = gated
    backend.openSession('b')
    wait_for(lambda: backend.activeSession == 'b' and backend.messageModel.partialHistory, 'Second partial history did not open')
    model = backend.messageModel
    view = window.property('conversation')
    full = expected['b']
    recent_count = model.rowCount()
    wait_for(lambda: view.property('count') == recent_count and not view.property('restoring'), 'Partial view did not settle')
    for _ in range(2000):
        QMetaObject.invokeMethod(view, 'scrollBy', Qt.DirectConnection, Q_ARG('QVariant', -1500))
        pause(5)
        if view.property('atYBeginning'):
            break
    assert view.property('atYBeginning'), 'Could not reach the top of the partial history'
    pause(300)
    assert model.partialHistory and backend._view.history_wanted, 'Reaching the top did not ask for earlier history'
    loading = find('earlierHistoryLoading')
    assert loading is not None and loading.isVisible(), 'Loading row missing at the top of the partial history'
    anchor = first_visible(view)
    shift = full.count - recent_count
    gate.set()
    wait_for(lambda: not model.partialHistory, 'Earlier history did not load')
    backend.transcripts.open = build
    pause(300)
    after = first_visible(view)
    assert after[0] in (anchor[0] + shift, anchor[0] + shift - 1), (anchor, after, shift)
    assert not (loading and loading.isVisible()), 'Loading row stayed after the history loaded'
    assert model.questionCount == full.question_count
    for _ in range(20):
        QMetaObject.invokeMethod(view, 'scrollBy', Qt.DirectConnection, Q_ARG('QVariant', -400))
        pause(30)
    assert first_visible(view)[0] < shift, 'Earlier rows did not appear when scrolling up'
    assert displayed(model) == rows(full), 'Complete history differs from the index'
    assert not warnings, '\n'.join(warnings)
    print('RECENT_HISTORY_UI_OK: latest messages first, matching rows, no reset at the tail, loading row and anchored earlier rows')
finally:
    if 'gate' in globals():
        gate.set()
    backend.close()

