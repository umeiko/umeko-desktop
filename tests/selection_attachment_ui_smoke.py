"""Real selection menu, paged extraction, drafts and stale async completions."""
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
os.environ['UMEKO_DATA_DIR'] = tempfile.mkdtemp(prefix='umeko-selection-attachment-')
os.environ['UMEKO_LANGUAGE'] = 'zh'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QMetaObject, QPointF, Qt
from PySide6.QtTest import QTest
from app.chat_copy import selected_text
from app.message_attachments import attachment_prompt
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


def wait(check, timeout=15):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        QTest.qWait(10)
        time.sleep(.001)
        if check():
            return
    raise AssertionError(('timeout', warnings))


def select(selection, start, end):
    selection.setProperty('anchor', start)
    selection.setProperty('cursor', end)
    QMetaObject.invokeMethod(selection, 'refresh')


def attach(selection):
    QMetaObject.invokeMethod(selection, 'attachToChat')
    wait(lambda: not backend.selectionAttachmentBusy)


try:
    base = Path(os.environ['UMEKO_DATA_DIR'])
    workspace = base / 'project'
    workspace.mkdir()
    backend.setWorkspace(workspace.as_uri())
    text = '中文𠮷 selected words\n\n```python\nprint("preserved")\n```\n\nLast paragraph.'
    backend._view.messages = [{'role': 'assistant', 'text': text, 'error': False}]
    backend.chatChanged.emit()
    QTest.qWait(300)
    find('promptInput').setProperty('text', 'existing draft question')
    backend.setDraft('existing draft question')
    existing = workspace / 'existing.txt'
    existing.write_text('keep this attachment')
    assert backend.addAttachments(json.dumps([existing.as_uri()]))
    app.clipboard().setText('clipboard stays intact')
    selection = find('chatSelection')
    start, end = {'row': 0, 'block': 0, 'offset': 0}, {'row': 0, 'block': 2, 'offset': 5}
    select(selection, start, end)
    # Open the actual menu over selected text and click the new action.
    editor = find('selectText_0_0')
    QTest.mouseClick(window, Qt.RightButton, Qt.NoModifier, editor.mapToScene(QPointF(8, 6)).toPoint())
    QTest.qWait(100)
    action = find('attachSelectedText')
    assert action.isVisible() and action.isEnabled()
    out = ROOT / 'artifacts/screenshots'
    out.mkdir(parents=True, exist_ok=True)
    window.grabWindow().save(str(out / 'issue135-selection-menu.png'))
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, action.mapToScene(action.boundingRect().center()).toPoint())
    wait(lambda: len(backend.attachments) == 2)
    expected = '中文𠮷 selected words\n\nprint("preserved")\n\nLast '
    item = backend.attachments[-1]
    assert Path(item['path']).read_text(encoding='utf-8') == expected, item
    assert item['kind'] == 'file' and item['name'] == '中文𠮷 selected words p.md', item
    assert Path(item['path']).parent == workspace.resolve() / '.umeko'
    assert backend._view.draft == 'existing draft question'
    assert find('promptInput').property('text') == 'existing draft question'
    assert backend.attachments[0]['path'] == str(existing.resolve())
    assert app.clipboard().text() == 'clipboard stays intact'
    assert len(backend._view.messages) == 1  # Attaching never sends a message.
    assert item['path'] in attachment_prompt('follow up', backend.attachments)
    window.grabWindow().save(str(out / 'issue135-text-attachment.png'))
    # A second attachment must not change the bytes referenced by the first.
    attach(selection)
    assert len(backend.attachments) == 3
    assert backend.attachments[-1]['name'].endswith(' (2).md')
    assert Path(item['path']).read_text(encoding='utf-8') == expected
    # Hold extraction to test navigation and refresh races deterministically.
    for mutate in ('navigation', 'refresh'):
        entered, release = threading.Event(), threading.Event()
        def delayed(*args):
            entered.set()
            if not release.wait(10):
                raise TimeoutError('test gate')
            return selected_text(*args)
        before = len(backend.attachments)
        with patch('app.chat_copy.selected_text', delayed):
            QMetaObject.invokeMethod(selection, 'attachToChat')
            wait(entered.is_set)
            if mutate == 'navigation':
                backend.newSession()
            else:
                backend._view.messages = [{'role': 'assistant', 'text': 'replacement', 'error': False}]
                backend.chatChanged.emit()
            release.set()
            wait(lambda: not backend.selectionAttachmentBusy)
        assert not backend.attachments
        assert app.clipboard().text() == 'clipboard stays intact'
        if mutate == 'navigation':
            backend._view.messages = [{'role': 'assistant', 'text': text, 'error': False}]
            backend.chatChanged.emit()
            QTest.qWait(100)
            selection = find('chatSelection')
            select(selection, start, end)
    # Fetch an unloaded section from a real indexed transcript, not its delegates.
    history = workspace / 'history.jsonl'
    with history.open('w', encoding='utf-8') as stream:
        stream.write(json.dumps({'type':'session','id':'quote-history','cwd':str(workspace)}) + '\n')
        for i in range(400):
            stream.write(json.dumps({'type':'message','id':str(i),'parentId':str(i-1) if i else None,
                'message':{'role':'assistant' if i % 2 else 'user','content':f'History {i} 中文𠮷\n\n**Detail** {i}'}}, ensure_ascii=False) + '\n')
    snapshot = backend.transcripts.open(str(history))
    backend._view.messages = []
    backend._view.transcript = snapshot
    backend.chatChanged.emit()
    wait(lambda: backend._chat_model.snapshot is snapshot)
    start = {'row': 101, 'block': 0, 'offset': 0}
    end = {'row': 101, 'block': 0, 'offset': 16}
    backend.attachChatSelection(json.dumps({'anchor': end, 'cursor': start, 'expanded': {}}))
    wait(lambda: not backend.selectionAttachmentBusy)
    assert len(backend.attachments) == 1
    assert Path(backend.attachments[0]['path']).read_text(encoding='utf-8') == 'History 101 中文𠮷'
    # Limit and write failures keep existing data intact and leave no phantom chip.
    backend._view.attachments *= 20
    backend.attachChatSelection(json.dumps({'anchor': start, 'cursor': end}))
    assert not backend.selectionAttachmentBusy and len(backend.attachments) == 20
    backend._view.attachments.clear()
    blocked = base / 'blocked-project'
    blocked.mkdir()
    (blocked / '.umeko').write_text('keep existing file')
    backend._view.workspace = str(blocked)
    backend.attachChatSelection(json.dumps({'anchor': start, 'cursor': end}))
    wait(lambda: not backend.selectionAttachmentBusy)
    assert not backend.attachments
    assert (blocked / '.umeko').read_text() == 'keep existing file'
    assert not warnings, warnings
    print('Selection attachment UI passed: menu, Unicode, multi-block and paged selection, collisions, drafts, clipboard, navigation/refresh races, attachment limit and write errors.')
finally:
    backend.close()
    engine.deleteLater()
    QTest.qWait(150)
