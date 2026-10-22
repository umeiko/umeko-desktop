"""Table cells survive HTML line breaks, streaming, copy and theme changes."""
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['UMEKO_DATA_DIR'] = tempfile.mkdtemp(prefix='umeko-markdown-table-')
os.environ['UMEKO_LANGUAGE'] = 'zh'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import Qt, QMetaObject, Q_ARG, Q_RETURN_ARG
from PySide6.QtGui import QTextTable
from PySide6.QtQml import QJSEngine
from PySide6.QtTest import QTest
from main import create_application

app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
script = QJSEngine()
assert not script.evaluate((ROOT/'app/qml/markdown.js').read_text(encoding='utf-8').replace('.pragma library', '', 1)).isError()
convert = script.globalObject().property('forQt')

def find(name):
    pending = [window.contentItem()]
    while pending:
        item = pending.pop()
        if item.objectName() == name and item.isVisible(): return item
        pending.extend(item.childItems())
    raise AssertionError(name)

def plain(item):
    return QMetaObject.invokeMethod(item, 'getText', Qt.DirectConnection, Q_RETURN_ARG(str),
                                   Q_ARG(int, 0), Q_ARG(int, item.property('length')))

fixture = '''## 状态转移

| 步数 | 金额<br>`nums[i]` | 决策 |
|:---:|:---:|:---:|
| 0 | **2** | 取当前值 |
| 1 | **7** | 跳过上一家 |
| 2 | **11** | 取累计最大值 |

最终结果 **12**。

| 后续表格 | 值 |
|---|---|
| second-cell | 42 |
'''

try:
    for original, expected in [
        ('a<br>b', 'a<br/>b'), ('a<BR >b', 'a<br/>b'), ('a<br/>b', 'a<br/>b'),
        ('`<br>` <br>', '`<br>` <br/>'),
        ('`` a ` <br> b `` <br>', '`` a ` <br> b `` <br/>'),
        (r'\<br> <br>', r'\<br> <br/>'),
        ('unmatched ` <br>', 'unmatched ` <br/>'),
        ('`a `` <br> b` <br>', '`a `` <br> b` <br/>'),
    ]:
        assert convert.call([original]).toString() == expected, original
    blocks = script.globalObject().property('blocks').call(['```html\n<br>\n```', True, False]).toVariant()
    assert blocks[0]['code'] and blocks[0]['text'] == '<br>', 'Fenced code was rewritten'
    backend.setFontScale(1.49)
    backend.setTheme('yanami')
    record = backend._view
    record.phase = 'running'
    record.messages = [{'role':'assistant', 'text':'', 'error':False}]
    backend.chatChanged.emit()
    for offset in range(0, len(fixture), 32):
        backend._handle_pi_event(record, {'type':'delta', 'text':fixture[offset:offset+32]})
        QTest.qWait(8)
    QTest.qWait(120)
    editor = find('selectText_0_0')
    quick = editor.property('textDocument')
    document = quick.textDocument()
    tables = [frame for frame in document.rootFrame().childFrames() if isinstance(frame, QTextTable)]
    assert record.busy and len(tables) == 2, 'Live table used a plain-text preview'
    assert (tables[0].rows(), tables[0].columns()) == (4, 3)
    assert tables[0].cellAt(1, 1).firstCursorPosition().block().text() == '2'
    assert tables[0].cellAt(3, 1).firstCursorPosition().block().text() == '11'
    assert tables[1].cellAt(1, 0).firstCursorPosition().block().text() == 'second-cell'
    assert '最终结果 12' in plain(editor), 'Text following the first table was lost'
    assert record.messages[-1]['text'] == fixture, 'Original Markdown was rewritten'
    selection = find('chatSelection')
    QMetaObject.invokeMethod(selection, 'selectAll')
    QMetaObject.invokeMethod(selection, 'copy')
    assert 'second-cell' in app.clipboard().text() and '取累计最大值' in app.clipboard().text()
    QMetaObject.invokeMethod(selection, 'clear')
    backend._handle_pi_event(record, {'type':'done'})
    QTest.qWait(100)
    assert 'second-cell' in plain(editor)
    out = ROOT/'artifacts/screenshots'; out.mkdir(parents=True, exist_ok=True)
    window.grabWindow().save(str(out/'table-live-yanami-v034.png'))
    backend.setTheme('dark'); QTest.qWait(100)
    assert 'second-cell' in plain(editor)
    window.grabWindow().save(str(out/'table-live-dark-v034.png'))
    assert not warnings, '\n'.join(warnings)
    print('MARKDOWN_TABLE_UI_OK: real-time cells, br compatibility, copy, themes and unchanged source')
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
