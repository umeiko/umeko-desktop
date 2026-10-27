"""IDE metadata must not steal code pastes; real file/image pastes still work."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['UMEKO_DATA_DIR'] = tempfile.mkdtemp(prefix='umeko-clipboard-ui-')
os.environ['QT_QPA_PLATFORM'] = 'offscreen'  # Keep the desktop clipboard untouched.
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QMimeData, Qt, QUrl
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from main import create_application

app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))

def find(name):
    pending = [window.contentItem()]
    while pending:
        item = pending.pop()
        if item.objectName() == name:
            return item
        pending.extend(item.childItems())
    raise AssertionError(name)

def paste(data, expected):
    prompt.setProperty('text', '')
    app.clipboard().setMimeData(data)
    prompt.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_V, Qt.ControlModifier)
    QTest.qWait(40)
    assert prompt.property('text') == expected, repr(prompt.property('text'))

try:
    assert app.platformName() == 'offscreen'
    QTest.qWait(150)
    prompt = find('promptInput')
    code = 'def hello():\n\treturn "中文𠮷 <tag>"\n'
    file = Path(os.environ['UMEKO_DATA_DIR'])/'copied file.txt'
    file.write_text('synthetic file fixture', encoding='utf-8')
    url = QUrl.fromLocalFile(str(file))
    image = QImage(8, 8, QImage.Format_RGB32)
    image.fill(0x668877)

    for metadata in ('plain', 'rich', 'empty-uri', 'remote-uri', 'local-uri', 'image'):
        data = QMimeData()
        data.setText(code)
        if metadata == 'rich':
            data.setHtml('<pre><span style="color:red">IDE code</span></pre>')
            data.setData('text/rtf', b'{\\rtf1\\ansi synthetic fixture}')
            data.setData('application/x-java-jvm-local-objectref', b'fixture')
        elif metadata == 'empty-uri':
            data.setData('text/uri-list', b'')
            assert data.hasUrls() and not data.urls()
        elif metadata == 'remote-uri':
            data.setUrls([QUrl('https://example.invalid/source.py')])
        elif metadata == 'local-uri':
            data.setUrls([url])
        elif metadata == 'image':
            data.setImageData(image)
        paste(data, code)
        assert not backend.attachments, metadata

    # File-only data can synthesize text from its URL. Both that representation
    # and the native path used by our file-card Copy action must remain files.
    for text in (None, url.toString(), str(file)):
        data = QMimeData()
        data.setUrls([url])
        if text is not None:
            data.setText(text)
        paste(data, '')
        assert len(backend.attachments) == 1
        assert Path(backend.attachments[0]['path']).samefile(file)
    backend.removeAttachment(backend.attachments[0]['id'])

    data = QMimeData()
    data.setImageData(image)
    paste(data, '')
    assert len(backend.attachments) == 1 and backend.attachments[0]['kind'] == 'image'
    backend.removeAttachment(backend.attachments[0]['id'])

    for urls in ([], [QUrl('https://example.invalid/source.py')],
                 [QUrl.fromLocalFile(str(file.with_name('missing.txt')))]):
        data = QMimeData()
        data.setUrls(urls)
        app.clipboard().setMimeData(data)
        assert not backend.pasteAttachments(), urls
        assert not backend.attachments

    backend._view.attachments = [
        {'id':str(i), 'path':str(file.with_name(f'occupied-{i}.txt')), 'kind':'file', 'name':str(i)}
        for i in range(20)
    ]
    data = QMimeData()
    data.setUrls([url])
    app.clipboard().setMimeData(data)
    assert not backend.pasteAttachments()
    assert len(backend.attachments) == 20
    backend._view.attachments.clear()
    backend.attachmentsChanged.emit()
    assert not warnings, '\n'.join(warnings)
    print('CLIPBOARD_PASTE_UI_OK: mixed IDE formats, empty/invalid URIs, file copies, duplicate files, screenshots and rejected attachments')
finally:
    app.clipboard().clear()
    backend.close()
    window.hide()
    QTest.qWait(100)
    import shiboken6
    shiboken6.delete(engine)
