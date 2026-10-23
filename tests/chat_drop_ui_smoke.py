"""Exercise native drop events across the chat page and project-specific creation."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['UMEKO_DATA_DIR'] = tempfile.mkdtemp(prefix='umeko-chat-drop-')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
os.environ['UMEKO_LANGUAGE'] = 'zh'
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtTest import QTest
from main import create_application

app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda messages: warnings.extend(item.toString() for item in messages))

def find(name):
    stack = [window.contentItem()]
    while stack:
        item = stack.pop()
        if item.objectName() == name: return item
        stack.extend(item.childItems())
    raise AssertionError(name)

def drop_at(point, path, screenshot=False):
    mime = QMimeData(); mime.setUrls([QUrl.fromLocalFile(str(path))])
    app.sendEvent(window, QDragEnterEvent(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
    app.sendEvent(window, QDragMoveEvent(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
    assert find('chatFileDropOverlay').isVisible(), 'Chat-wide drop overlay did not appear'
    if screenshot:
        QTest.qWait(150)
        assert window.grabWindow().save(str(ROOT/'artifacts/screenshots/chat-file-catch.png'))
    event = QDropEvent(QPointF(point), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    app.sendEvent(window, event); QTest.qWait(180)
    assert event.isAccepted()
    assert find('promptInput').hasActiveFocus()
    if app.platformName() == 'windows':
        import ctypes
        ctypes.windll.user32.GetForegroundWindow.restype = ctypes.c_void_p
        assert ctypes.windll.user32.GetForegroundWindow() == int(window.winId()), 'Dropped files did not bring the native window to the foreground'
    assert not find('chatFileDropOverlay').isVisible()

try:
    QTest.qWait(300)
    backend.setTheme('yanami')
    folder = backend.store.directory/'project'; folder.mkdir()
    backend.setWorkspace(folder.as_uri())
    project = backend.store.data['projects'][0]
    button = find('newProjectSession_'+project['id'])
    assert button.isVisible(), 'New-project conversation button should be discoverable without hovering'
    backend._view.messages = [{'role':'user','text':'Existing conversation','error':False}]
    backend.chatChanged.emit(); QTest.qWait(150)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, button.mapToScene(button.boundingRect().center()).toPoint())
    QTest.qWait(150)
    assert not backend.messages and Path(backend._view.workspace).samefile(folder)
    first = folder/'drop one.txt'; first.write_text('file drop fixture')
    page = find('chatPage')
    drop_at(page.mapToScene(QPointF(90,90)).toPoint(), first, screenshot=True)
    assert len(backend.attachments)==1
    for character in 'ready to type': QTest.keyClick(window, Qt.Key(ord(character.upper())))
    assert find('promptInput').property('text')=='ready to type'
    second = folder/'drop two.txt'; second.write_text('second file drop fixture')
    composer = find('composer')
    drop_at(composer.mapToScene(QPointF(100,35)).toPoint(), second)
    assert len(backend.attachments)==2
    assert not warnings, '\n'.join(warnings)
    print('CHAT_DROP_UI_OK: whole chat, composer, catch overlay, direct typing, project plus button')
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
