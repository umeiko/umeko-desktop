"""Grouped conversation loading (PR #97 review): count-based offscreen checks.

Rows load, lay out and appear in groups of consecutive messages. This smoke
scrolls a long tool-heavy history with synthesized wheel events inside the
offscreen window and checks, by counting rather than timing, that:

1. no row on screen is ever a loading placeholder while scrolling up or down;
2. inserting a laid-out group above the screen, or releasing far groups,
   leaves the first visible row at the same screen position;
3. streaming the last message does not recreate, resize or regroup any row
   of the groups above it;
4. opening the session creates no more row bodies than the screen and its
   usual margin need, i.e. grouping does not make opening load more.
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
base = Path(tempfile.mkdtemp(prefix='umeko-grouped-loading-'))
os.environ.update(UMEKO_DATA_DIR=str(base / 'profile'), QT_QPA_PLATFORM='offscreen',
                  QT_QUICK_BACKEND='software', PI_OFFLINE='1')
from PySide6.QtCore import QCoreApplication, QMetaObject, QPoint, QPointF, Q_ARG, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
import shiboken6
from main import create_application

WHEEL_EVENTS = 90
NOTCHES = 2  # 120 px per event: a fast wheel


def tool_heavy_history(turns, steps):
    """Native Pi entries: many alternating thinking blocks and tool calls per turn."""
    entries = [{'type': 'session', 'id': 'fixture', 'cwd': str(base)}]

    def add(role, content, **values):
        entries.append({'type': 'message', 'id': f'm{len(entries)}', 'parentId': entries[-1].get('id') if len(entries) > 1 else None,
                        'message': {'role': role, 'content': content, 'provider': 'test-provider', 'model': 'test-model', **values}})
    for turn in range(turns):
        add('user', f'Question {turn}: ' + 'inspect the project and explain. ' * (1 + turn % 5))
        for step in range(steps):
            content = [{'type': 'thinking', 'thinking': f'Reasoning {turn}.{step}\n' + 'Weigh the evidence first.\n' * (3 + step * 7 % 40)}]
            if step % 5 == 2:
                content.append({'type': 'text', 'text': f'Step {step}\n\n```python\n' + ''.join(f'x{j} = {j}\n' for j in range(4 + step % 9)) +
                                '```\n\n| a | b |\n| - | - |\n' + ''.join(f'| {j} | {j * j} |\n' for j in range(5))})
            call = f'call-{turn}-{step}'
            content.append({'type': 'toolCall', 'id': call, 'name': ('bash', 'read', 'grep')[step % 3],
                            'arguments': {'command': f'echo {step}', 'path': f'src/file{step}.py', 'pattern': 'x'}})
            add('assistant', content)
            add('toolResult', [{'type': 'text', 'text': 'output line\n' * (1 + step * 13 % 60)}], toolCallId=call, isError=step % 11 == 5)
        if turn % 4 == 3:
            add('assistant', [], stopReason='error', errorMessage='Provider request failed: 500 test failure')
        add('assistant', [{'type': 'thinking', 'thinking': 'Summarize.\n' * 6},
                          {'type': 'text', 'text': f'## Result {turn}\n\n' + 'The answer explains the change. ' * 12 + '\n\n```js\nconsole.log(1)\n```'}],
            stopReason='stop')
    return entries


app, engine, backend = create_application()
window = engine.rootObjects()[0]
window.resize(1200, 900)
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))


def find(name):
    todo = [window.contentItem()]
    while todo:
        item = todo.pop()
        if item.objectName() == name:
            return item
        todo.extend(item.childItems())
    raise AssertionError(name)


def wait(check, label, seconds=60):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QTest.qWait(10)
        time.sleep(.001)
        if check():
            return
    raise AssertionError(label)


def slots(view):
    return [item for item in view.property('contentItem').childItems() if item.property('messageSlot') is True]


def on_screen(view):
    top = view.property('contentY')
    return [item for item in slots(view) if item.y() + item.height() > top + 1 and item.y() < top + view.height() - 1]


def placeholders(view):
    return [item.property('index') for item in on_screen(view) if not item.property('bodyReady')]


def first_visible(view):
    rows = sorted(on_screen(view), key=lambda item: item.property('index'))
    return (rows[0].property('index'), rows[0].y() - view.property('contentY')) if rows else (None, 0)


def screen_y(view, row):
    item = next((item for item in slots(view) if item.property('index') == row), None)
    return None if item is None else item.y() - view.property('contentY')


def body(item):
    loader = next((child for child in item.childItems() if child.property('asynchronous') is not None), None)
    value = loader.property('item') if loader is not None else None
    return shiboken6.getCppPointer(value)[0] if value is not None else None


def wheel(view, notches):
    position = view.mapToScene(QPointF(view.width() / 2, view.height() / 2))
    event = QWheelEvent(position, QPointF(window.mapToGlobal(position.toPoint())), QPoint(0, 0), QPoint(0, 120 * notches),
                        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QCoreApplication.sendEvent(window, event)


def scroll(view, notches, events):
    """Wheel events with one frame between them; count frames showing placeholders."""
    frames = bad = 0
    for _ in range(events):
        wheel(view, notches)
        QTest.qWait(16)
        frames += 1
        bad += bool(placeholders(view))
        if view.property('atYBeginning' if notches > 0 else 'atYEnd'):
            break
    return frames, bad


def invoke(view, method, *args):
    assert QMetaObject.invokeMethod(view, method, Qt.DirectConnection, *[Q_ARG('QVariant', arg) for arg in args])


try:
    source = base / 'history.jsonl'
    source.write_text('\n'.join(json.dumps(entry) for entry in tool_heavy_history(20, 30)) + '\n', encoding='utf-8')
    backend._sessions = [{'id': 'fixture', 'file': str(source), 'title': 'Long history', 'workspace': str(base)}]
    backend.chatChanged.emit()
    backend.transcripts.open(str(source))  # build the index before measuring the open

    # 4. Opening loads only what the first screen and its margin need.
    created = set()

    def track(view):
        def scan():
            for item in slots(view):
                pointer = body(item)
                if pointer is not None:
                    created.add(pointer)
        view.property('contentItem').childrenChanged.connect(scan)
        return scan
    backend.openSession('fixture')
    wait(lambda: backend.activeSession == 'fixture' and backend.messageModel.paged, 'open indexed session')
    view = find('conversation')
    scan = track(view)
    while view.property('restoring'):
        QTest.qWait(5)
        scan()
    scan()
    model = backend.messageModel
    top, height = view.property('contentY'), view.height()
    margin = [item for item in slots(view) if item.y() + item.height() > top - height * 0.25 and item.y() < top + height * 1.25]
    print('OPEN', json.dumps({'bodies': len(created), 'screen_and_margin_rows': len(margin), 'rows': model.rowCount()}), flush=True)
    assert len(created) <= len(margin) + 1, (len(created), len(margin))
    assert view.property('followTail') and not placeholders(view)

    # 1. Fast wheel scrolling up through the history and back down.
    QTest.qWait(200)
    frames, bad = scroll(view, NOTCHES, WHEEL_EVENTS)
    print('SCROLL_UP', json.dumps({'frames': frames, 'placeholder_frames': bad, 'top_row': first_visible(view)[0]}), flush=True)
    assert frames >= 40 and bad == 0, (frames, bad)
    assert first_visible(view)[0] < model.rowCount() - 8, 'the wheel did not move through the history'
    up_row = first_visible(view)[0]
    frames, bad = scroll(view, -NOTCHES, WHEEL_EVENTS // 2)
    print('SCROLL_DOWN', json.dumps({'frames': frames, 'placeholder_frames': bad}), flush=True)
    assert bad == 0, bad

    # 2a. A laid-out group waiting above the screen is inserted: the reader's row stays put.
    # Rows far above the part scrolled through have never been measured, so
    # their real heights differ from the estimates and the position must be corrected.
    invoke(view, 'jumpToMessage', 40)
    wait(lambda: not view.property('restoring'), 'jump')
    # Keep one more group on each side so a group above loads in the background.
    view.setProperty('keepGroups', 2)
    for _ in range(400):
        QTest.qWait(10)
        invoke(view, 'requestVisibleRange')
        top = view.property('contentY')
        present = {item.property('index'): item for item in slots(view)}
        pending = []
        for item in present.values():
            row = item.property('index')
            if item.y() + item.height() > top or item.property('shown'):
                continue
            group = model.groupOf(row)
            members = [present.get(r) for r in range(max(min(present), model.groupFirst(group)), min(max(present), model.groupLast(group)) + 1)]
            if all(m is not None and m.property('bodyLoaded') for m in members):
                pending.append(item)
        if pending:
            break
    assert pending, 'no laid-out group was waiting above the screen'
    row, before = first_visible(view)
    heights = {item.property('index'): item.height() for item in pending}
    invoke(view, 'settleGroups', True)
    inserted = [item for item in pending if shiboken6.isValid(item) and item.property('shown')]
    changed = sum(1 for item in inserted if abs(item.height() - heights[item.property('index')]) > .5)
    after = screen_y(view, row)
    print('INSERT_ABOVE', json.dumps({'rows': len(inserted), 'resized': changed, 'anchor_before': round(before, 1), 'anchor_after': round(after, 1)}), flush=True)
    assert inserted and changed and abs(after - before) <= .5, (len(inserted), changed, before, after)

    # 2b. Far groups are released together: the reader's row stays put.
    view.setProperty('keepGroups', 0)
    row, before = first_visible(view)
    loaded = sum(1 for item in slots(view) if body(item) is not None)
    invoke(view, 'requestVisibleRange')
    released = loaded - sum(1 for item in slots(view) if body(item) is not None)
    after = screen_y(view, row)
    print('RELEASE', json.dumps({'released_bodies': released, 'anchor_before': round(before, 1), 'anchor_after': round(after, 1)}), flush=True)
    assert released > 0 and abs(after - before) <= .5, (released, before, after)
    view.setProperty('keepGroups', 1)

    # 3. Streaming the last message leaves the groups above it alone.
    invoke(view, 'jumpToLatest')
    wait(lambda: not view.property('restoring') and view.property('followTail'), 'latest')
    QTest.qWait(200)
    record = backend._view
    backend._handle_pi_event(record, {'type': 'user_start', 'text': 'Live question'})
    backend._handle_pi_event(record, {'type': 'assistant_start'})
    wait(lambda: view.property('atYEnd') and not placeholders(view), 'live row shown')
    tail = model.groupOf(model.rowCount() - 1)
    above_first = model.groupFirst(tail)
    snapshot = {item.property('index'): (body(item), round(item.height(), 1), model.groupOf(item.property('index')))
                for item in slots(view) if item.property('index') < above_first and item.property('bodyReady')}
    assert snapshot, 'no laid-out rows above the streaming group'
    for part in range(60):
        backend._handle_pi_event(record, {'type': 'thinking_delta' if part < 20 else 'delta',
                                          'text': f'streamed part {part} with some words\n' + ('\n```py\nx = 1\n```\n' if part == 40 else '')})
        QTest.qWait(4)
    QTest.qWait(100)
    now = {item.property('index'): (body(item), round(item.height(), 1), model.groupOf(item.property('index')))
           for item in slots(view) if item.property('index') in snapshot}
    # A body released because its group left the kept range is recycling;
    # a new body, another height or another group would be a re-layout.
    relaid = sorted(row for row, (pointer, size, group) in now.items()
                    if size != snapshot[row][1] or group != snapshot[row][2] or pointer not in (None, snapshot[row][0]))
    print('STREAM', json.dumps({'rows_above': len(snapshot), 'still_instantiated': len(now), 'relaid_out': relaid}), flush=True)
    assert len(now) and not relaid, relaid
    assert view.property('followTail') and view.property('atYEnd')
    assert not warnings, warnings[:5]
    print('GROUPED_LOADING_UI_OK', flush=True)
finally:
    backend.close()
    shiboken6.delete(engine)
    shutil.rmtree(base, ignore_errors=True)
