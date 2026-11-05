"""Issue #95: a long conversation must stay still at the bottom with no input.

Live rows (an unindexed session, or the streaming tail of an indexed one) used
to forget their measured heights. Following the bottom then recreated tall rows
from a 100 px guess; their real height pushed the tail out of view, the next
follow-tail pass recreated them again, and the view moved back and forth
forever. Each case counts movement over a fixed number of event-loop passes
with no input; nothing is time-based.
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
base = Path(tempfile.mkdtemp(prefix='umeko-scroll-oscillation-'))
os.environ.update(UMEKO_DATA_DIR=str(base / 'profile'), QT_QPA_PLATFORM='offscreen',
                  QT_QUICK_BACKEND='software', PI_OFFLINE='1')
from PySide6.QtCore import QMetaObject, Q_ARG, Qt
from PySide6.QtTest import QTest
import shiboken6
from main import create_application

PASSES = 200
MAX_REVERSALS = 2
MAX_TOP_CHANGES = 2


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


def live_rows(entries):
    """The rows Pi's state event sends for a session small enough to stay unindexed."""
    results = {e['message']['toolCallId']: e['message'] for e in entries[1:] if e['message']['role'] == 'toolResult'}
    rows = []
    for entry in entries[1:]:
        message = entry['message']
        if message['role'] == 'toolResult':
            continue
        content = message['content']
        if isinstance(content, str):
            rows.append({'role': message['role'], 'text': content, 'error': False})
            continue
        row = {'role': message['role'], 'text': ''.join(b.get('text', '') for b in content if b['type'] == 'text'),
               'error': bool(message.get('errorMessage')), 'stopReason': message.get('stopReason', '')}
        if message.get('errorMessage'):
            row.update(errorMessage=message['errorMessage'], text=row['text'] or message['errorMessage'])
        thinking = ''.join(b.get('thinking', '') for b in content if b['type'] == 'thinking')
        if thinking:
            row['thinking'] = thinking
        calls = [b for b in content if b['type'] == 'toolCall']
        if calls:
            row['tools'] = [{'id': b['id'], 'name': b['name'], 'arguments': b['arguments'], 'path': '',
                             'state': 'error' if results[b['id']].get('isError') else 'done',
                             'result': results[b['id']]['content'][0]['text']} for b in calls]
        rows.append(row)
    return rows


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


def top_row(view):
    top, best = view.property('contentY'), None
    for item in view.property('contentItem').childItems():
        if item.property('messageSlot') is True and item.y() + item.height() > top + 1:
            index = item.property('index')
            best = index if best is None else min(best, index)
    return best


def reversals(values):
    direction = count = 0
    for a, b in zip(values, values[1:]):
        if abs(b - a) <= .5:
            continue
        sign = 1 if b > a else -1
        count += bool(direction and sign != direction)
        direction = sign
    return count


def stays_still(view, label):
    """Count movement without input: contentY reversals and visible top-row changes."""
    positions, tops = [], []
    record = lambda: positions.append(view.property('contentY'))
    view.contentYChanged.connect(record)
    try:
        for _ in range(PASSES):
            QTest.qWait(8)
            tops.append(top_row(view))
    finally:
        view.contentYChanged.disconnect(record)
    changes = sum(a != b for a, b in zip(tops, tops[1:]))
    result = {'case': label, 'contentY_changes': len(positions), 'contentY_reversals': reversals(positions),
              'top_row_changes': changes, 'top_rows': sorted(set(t for t in tops if t is not None))[:8]}
    print('CASE', json.dumps(result), flush=True)
    return result['contentY_reversals'] <= MAX_REVERSALS and changes <= MAX_TOP_CHANGES, result


def jump(view, row):
    assert QMetaObject.invokeMethod(view, 'jumpToMessage', Qt.DirectConnection, Q_ARG('QVariant', row))
    wait(lambda: not view.property('restoring'), 'jump')


def latest(view):
    # Same handler as the "latest messages" button.
    assert QMetaObject.invokeMethod(view, 'jumpToLatest', Qt.DirectConnection)
    wait(lambda: not view.property('restoring') and view.property('followTail'), 'latest')


def stream_tool_turn(record, steps):
    """A long live turn: reasoning, prose and a tool round per step, via the Pi event path."""
    backend._handle_pi_event(record, {'type': 'user_start', 'text': 'Live question'})
    for step in range(steps):
        backend._handle_pi_event(record, {'type': 'assistant_start'})
        for part in range(8):
            backend._handle_pi_event(record, {'type': 'thinking_delta', 'text': f'thought {step}.{part} weighing the evidence\n'})
            QTest.qWait(2)
        if step % 4 == 1:
            for part in range(6):
                backend._handle_pi_event(record, {'type': 'delta', 'text': f'Line {part} of step {step}.\n\n' + ('```py\nx = 1\n```\n\n' if part == 3 else '')})
                QTest.qWait(2)
        call = f'live-{step}'
        backend._handle_pi_event(record, {'type': 'tool', 'id': call, 'name': 'bash', 'state': 'running', 'args': {'command': f'echo {step}'}})
        QTest.qWait(3)
        backend._handle_pi_event(record, {'type': 'tool', 'id': call, 'name': 'bash', 'state': 'done', 'args': {'command': f'echo {step}'},
                                          'result': 'ok\n' * (1 + step % 20)})
        backend._handle_pi_event(record, {'type': 'message', 'role': 'assistant', 'text': '', 'stopReason': 'toolUse'})
        QTest.qWait(3)


failures = []
try:
    entries = tool_heavy_history(7, 30)
    # 1. An unindexed session (Pi sends every row) opens following the bottom.
    backend._view.messages = live_rows(entries)
    backend._view.loaded = True
    backend.chatChanged.emit()
    backend.viewChanged.emit()
    view = find('conversation')
    wait(lambda: view.property('count') > 40 and not view.property('restoring'), 'live rows')
    QTest.qWait(80)
    ok, result = stays_still(view, 'live session at the bottom')
    ok or failures.append(result)
    # 2. History navigation back to the latest messages in the same session.
    jump(view, view.property('count') // 2)
    latest(view)
    QTest.qWait(80)
    ok, result = stays_still(view, 'live session after jumping to latest')
    ok or failures.append(result)
    assert view.property('followTail')

    # 3. An indexed history of over a thousand messages with a long streamed
    # tool-heavy turn: its live rows sit at the bottom the user returns to.
    source = base / 'history.jsonl'
    source.write_text('\n'.join(json.dumps(entry) for entry in tool_heavy_history(20, 30)) + '\n', encoding='utf-8')
    backend._sessions = [{'id': 'fixture', 'file': str(source), 'title': 'Long history', 'workspace': str(base)}]
    backend.chatChanged.emit()
    backend.openSession('fixture')
    wait(lambda: backend.activeSession == 'fixture' and backend.messageModel.paged, 'open indexed session')
    view = find('conversation')
    wait(lambda: not view.property('restoring'), 'restore indexed session')
    base_rows = backend.messageModel.rowCount()
    stream_tool_turn(backend._view, 40)
    wait(lambda: view.property('atYEnd'), 'streaming stays at the bottom')
    assert backend.messageModel.rowCount() > base_rows + 4
    jump(view, base_rows // 2)
    latest(view)
    QTest.qWait(80)
    ok, result = stays_still(view, 'indexed session with a streamed tail after jumping to latest')
    ok or failures.append(result)
    assert view.property('followTail') and view.property('atYEnd')
    assert not failures, failures
    assert not warnings, warnings[:5]
    print('SCROLL_OSCILLATION_UI_OK', flush=True)
finally:
    backend.close()
    shiboken6.delete(engine)
    shutil.rmtree(base, ignore_errors=True)
