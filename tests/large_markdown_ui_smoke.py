"""Exercise virtual Markdown in a real window, including selection and full source copy."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QCoreApplication, QEvent, QMetaObject, Q_ARG, Q_RETURN_ARG, QRectF, QPointF, Qt, QTimer
from PySide6.QtTest import QTest
from main import create_application


def fixture():
    sections = ['# Large Markdown\n\nalpha beta gamma — 可以跨段选择与复制。\n\n[Last section](#section-599)\n\n']
    for i in range(600):
        sections.append(f'## Section {i}\n\n' + ('Markdown **formatted text** 与状态转移说明。 ' * 30) + '\n\n')
        sections.append('| Step | State | Description |\n| --- | --- | --- |\n')
        sections.extend(f'| row-{i}-{j} | `dp[{j}]` | **Take** or skip — 状态转移保留所有行与格式。 |\n' for j in range(40))
        sections.append('\n```rust\n' + 'let best = previous.max(earlier + value); // 示例𠮷\n' * 12 + '```\n\n')
    sections.append('## END-OF-DOCUMENT\n\nFinal **formatted** paragraph.\n')
    return ''.join(sections)


with tempfile.TemporaryDirectory(prefix='umeko-large-markdown-') as temporary:
    base = Path(temporary)
    os.environ['UMEKO_DATA_DIR'] = str(base / 'profile')
    path = base / 'large.md'
    source = fixture()
    path.write_text(source, encoding='utf-8')
    with patch('app.webview.configure'):
        app, engine, backend = create_application()
    window = engine.rootObjects()[0]
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))

    def items():
        stack = [window.contentItem()]
        while stack:
            item = stack.pop()
            yield item
            stack.extend(item.childItems())

    def find(name):
        return next((item for item in items() if item.objectName() == name), None)

    def wait(check, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            QTest.qWait(10)
            time.sleep(.001)  # Let Python's reader thread run as the real app.exec() does.
            if check():
                return
        raise AssertionError('Timeout: ' + str(warnings))

    def invoke(item, method):
        return QMetaObject.invokeMethod(item, method)

    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    try:
        timer.start(10)
        started = time.monotonic()
        backend._handle_pi_event(backend._view, {'type':'tool','id':'large-md','name':'submit_to_chatbox','state':'done',
            'args':{'items':[{'path':str(path)}]}, 'media':[{'path':str(path),'kind':'markdown','title':'Large Markdown'}]})
        wait(lambda: backend.documentPreview.state.get('chunked') and find('documentBlockList') is not None)
        wait(lambda: find('webPane') and not find('webPane').property('moving'))
        elapsed = time.monotonic() - started
        timer.stop()
        assert not backend.documentPreview.state.get('truncated')
        assert not backend.documentPreview.state.get('renderNote'), backend.documentPreview.state
        view = find('documentBlockList')
        wait(lambda: any(i.objectName().startswith('documentBlockText_') and i.property('length') for i in items()))
        editors = [i for i in items() if i.objectName().startswith('documentBlockText_')]
        assert backend.documentPreview.blocks.rowCount() > 1000
        assert len(editors) < 35, len(editors)
        assert backend.documentPreview.state['text'] == ''
        assert max(b-a for a,b in zip(ticks,ticks[1:])) < 1.0
        output = ROOT / 'artifacts/markdown-preview'
        output.mkdir(parents=True, exist_ok=True)
        window.grabWindow().save(str(output / 'large-markdown.png'))

        # Real pointer double-click, then asynchronous copy from the block model.
        editor = next(i for i in editors if 'alpha beta' in str(i.property('text')))
        plain = QMetaObject.invokeMethod(editor, 'getText', Qt.DirectConnection, Q_RETURN_ARG(str), Q_ARG(int,0), Q_ARG(int,editor.property('length')))
        rect = QMetaObject.invokeMethod(editor, 'positionToRectangle', Qt.DirectConnection, Q_RETURN_ARG(QRectF), Q_ARG(int,plain.index('beta')+2))
        point = editor.mapToScene(QPointF(rect.x()+1, rect.y()+rect.height()/2)).toPoint()
        QTest.mouseDClick(window, Qt.LeftButton, Qt.NoModifier, point)
        QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, point)
        selection = find('documentSelection')
        invoke(selection,'copy')
        wait(lambda: app.clipboard().text() == 'beta')
        invoke(selection,'selectAll');invoke(selection,'copy')
        wait(lambda: 'END-OF-DOCUMENT' in app.clipboard().text())
        assert 'row-599-39' in app.clipboard().text()

        # A native Markdown link passes through the selection overlay and jumps
        # directly to an uninstantiated heading near the end of the document.
        rect = QMetaObject.invokeMethod(editor, 'positionToRectangle', Qt.DirectConnection, Q_RETURN_ARG(QRectF), Q_ARG(int,plain.index('Last section')+3))
        point = editor.mapToScene(QPointF(rect.x()+1, rect.y()+rect.height()/2)).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
        wait(lambda: view.property('contentY') > 1000)
        wait(lambda: any('Section 599' in str(i.property('text')) for i in items() if i.objectName().startswith('documentBlockText_')))

        invoke(view, 'positionViewAtEnd')
        wait(lambda: any('END-OF-DOCUMENT' in str(i.property('text')) for i in items() if i.objectName().startswith('documentBlockText_')))
        backend.documentPreview.setMode('markdown','source')
        invoke(view, 'positionViewAtEnd')
        wait(lambda: any('END-OF-DOCUMENT' in str(i.property('text')) for i in items() if i.objectName().startswith('documentBlockText_')))
        assert ''.join(b['text'] for b in backend.documentPreview.blocks.rows) == source
        selection = find('documentSelection')
        invoke(selection,'selectAll');invoke(selection,'copy')
        wait(lambda: app.clipboard().text() == source)
        backend.documentPreview.copyAll()
        assert app.clipboard().text() == source
        invoke(selection,'selectAll');invoke(selection,'copy')
        backend.documentPreview.copyAll()  # Cancel an older asynchronous copy.
        QTest.qWait(100)
        assert app.clipboard().text() == source
        backend.documentPreview.setMode('markdown','rendered')
        invoke(view, 'positionViewAtBeginning')
        cached = time.monotonic()
        backend.documentPreview.load(str(path),'markdown')
        wait(lambda: not backend.documentPreview.state.get('busy'))
        cached = time.monotonic() - cached
        assert not [w for w in warnings if any(n in w for n in ('PagedDocument', 'DocumentSurface', 'ChatSelection'))], warnings
        metrics = {'bytes':path.stat().st_size,'blocks':backend.documentPreview.blocks.rowCount(),
            'liveEditors':len(editors),'openSeconds':round(elapsed,3),'cachedSeconds':round(cached,3),
            'maxGuiTimerGapMs':round(max(b-a for a,b in zip(ticks,ticks[1:]))*1000,1)}
        (output/'metrics.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
        print('LARGE_MARKDOWN_UI_OK: complete rendered tables/code, viewport reuse, source switch, real word selection, cross-block copy, full source copy, cached reopen; '+json.dumps(metrics))
    finally:
        backend.close()
        engine.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
