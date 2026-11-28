"""Quote selected chat text into the composer through the real selection menu."""
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
os.environ['UMEKO_DATA_DIR'] = tempfile.mkdtemp(prefix='umeko-selection-quote-')
os.environ['UMEKO_LANGUAGE'] = 'zh'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QMetaObject, QPointF, Qt
from PySide6.QtTest import QTest
from app.chat_copy import selected_text
from main import create_application

app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))


def find(name):
    stack = [window.contentItem()]
    fallback = None
    while stack:
        item = stack.pop()
        if item.objectName() == name:
            if item.isVisible():
                return item
            fallback = fallback or item
        stack.extend(item.childItems())
    if fallback is not None:
        return fallback
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


def prompt_text():
    return find('promptInput').property('text')


def quote(selection):
    QMetaObject.invokeMethod(selection, 'quoteToChat')
    wait(lambda: not backend.selectionQuoteBusy)


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
    app.clipboard().setText('clipboard stays intact')
    selection = find('chatSelection')
    start, end = {'row': 0, 'block': 0, 'offset': 0}, {'row': 0, 'block': 2, 'offset': 5}
    select(selection, start, end)
    # Open the real selection menu and click the quote action.
    editor = find('selectText_0_0')
    QTest.mouseClick(window, Qt.RightButton, Qt.NoModifier, editor.mapToScene(QPointF(8, 6)).toPoint())
    QTest.qWait(100)
    action = find('quoteSelectedText')
    assert action.isVisible() and action.isEnabled()
    out = ROOT / 'artifacts/screenshots'
    out.mkdir(parents=True, exist_ok=True)
    window.grabWindow().save(str(out / 'selection-quote-menu.png'))
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, action.mapToScene(action.boundingRect().center()).toPoint())
    expected = ('existing draft question\n\n> 中文𠮷 selected words\n>\n> print("preserved")\n>\n> Last\n\n')
    wait(lambda: prompt_text() == expected)
    assert not backend.selectionQuoteBusy
    assert not selection.property('hasSelection')
    assert backend._view.draft == expected
    assert find('promptInput').property('activeFocus')
    assert app.clipboard().text() == 'clipboard stays intact'
    assert len(backend._view.messages) == 1
    window.grabWindow().save(str(out / 'selection-quote-composer.png'))
    # Quoting another passage keeps the earlier quote and separates blocks.
    select(selection, {'row': 0, 'block': 0, 'offset': 0}, {'row': 0, 'block': 0, 'offset': 4})
    quote(selection)
    assert prompt_text().endswith('\n\n> 中文𠮷\n\n'), prompt_text()
    assert backend._view.draft == prompt_text()
    # A paged selection is extracted in the background, never from delegates.
    history = workspace / 'history.jsonl'
    with history.open('w', encoding='utf-8') as stream:
        stream.write(json.dumps({'type': 'session', 'id': 'quote-history', 'cwd': str(workspace)}) + '\n')
        for i in range(400):
            stream.write(json.dumps({'type': 'message', 'id': str(i), 'parentId': str(i - 1) if i else None,
                'message': {'role': 'assistant' if i % 2 else 'user', 'content': f'History {i} 中文𠮷\n\n**Detail** {i}'}}, ensure_ascii=False) + '\n')
    snapshot = backend.transcripts.open(str(history))
    backend._view.messages = []
    backend._view.transcript = snapshot
    backend.chatChanged.emit()
    wait(lambda: backend._chat_model.snapshot is snapshot)
    backend.setDraft('')
    backend.editorText.emit('')
    wait(lambda: prompt_text() == '')
    backend.quoteChatSelection(json.dumps({'anchor': {'row': 101, 'block': 0, 'offset': 16},
                                           'cursor': {'row': 101, 'block': 0, 'offset': 0}, 'expanded': {}}))
    wait(lambda: not backend.selectionQuoteBusy)
    assert prompt_text() == '> History 101 中文𠮷\n\n', prompt_text()
    assert backend._view.draft == prompt_text()
    # A quote that finishes after navigation must not touch the new chat.
    entered, release = threading.Event(), threading.Event()
    def delayed(*args, **kwargs):
        entered.set()
        if not release.wait(10):
            raise TimeoutError('test gate')
        return selected_text(*args, **kwargs)
    with patch('app.chat_copy.selected_text', delayed):
        backend.quoteChatSelection(json.dumps({'anchor': {'row': 101, 'block': 0, 'offset': 0},
                                               'cursor': {'row': 101, 'block': 0, 'offset': 16}, 'expanded': {}}))
        wait(entered.is_set)
        backend.newSession()
        release.set()
        wait(lambda: not backend.selectionQuoteBusy)
    assert prompt_text() == '' and backend._view.draft == ''
    # A select-all-sized quote is rejected before it can reach the composer.
    toasts = []
    backend.toast.connect(toasts.append)
    backend._view.messages = [{'role': 'assistant', 'text': 'x' * 20000, 'error': False}]
    backend.chatChanged.emit()
    QTest.qWait(150)
    backend.quoteChatSelection(json.dumps({'anchor': {'row': 0, 'block': 0, 'offset': 0},
                                           'cursor': {'row': 0, 'block': 0, 'offset': 20000}, 'expanded': {}}))
    wait(lambda: not backend.selectionQuoteBusy)
    assert prompt_text() == '' and backend._view.draft == ''
    assert any('所选内容过长' in message for message in toasts), toasts
    assert not warnings, warnings
    print('SELECTION_QUOTE_UI_OK: menu, Markdown quote, draft retention, cursor focus, paged history and stale navigation')
finally:
    backend.close()
    engine.deleteLater()
    QTest.qWait(150)
