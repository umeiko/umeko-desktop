"""Actual main Qt composer: permanent shortcut hint, layout, and input events."""
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QSystemTrayIcon
from shiboken6 import delete
from tests.chat_input_keys import check_newline_and_ime

phase = sys.argv[1] if len(sys.argv) > 1 else 'after'
assert phase in ('before', 'after')
with tempfile.TemporaryDirectory(prefix='umeko-composer-195-') as folder:
    os.environ.update(UMEKO_DATA_DIR=folder + '/profile', PI_CODING_AGENT_DIR=folder + '/agent',
                      QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software', UMEKO_LANGUAGE='zh')
    QSystemTrayIcon.show = lambda *args: None
    from main import create_application
    app, engine, backend = create_application()
    window = engine.rootObjects()[0]

    def find(name):
        pending = [window.contentItem()]
        while pending:
            item = pending.pop()
            if item.objectName() == name:
                return item
            pending.extend(item.childItems())
        raise AssertionError(name)

    try:
        window.show()
        window.requestActivate()
        out = ROOT / 'build/issue195'
        out.mkdir(parents=True, exist_ok=True)
        for size, width in (('wide', 1450), ('narrow', 860)):
            window.resize(width, 800)
            QTest.qWait(300)
            composer = find('composer')
            field = find('promptInput')
            field.setProperty('text', '验证主聊天输入栏布局')
            field.forceActiveFocus()
            send = find('sendButton')
            status = find('composerStatus')
            row = find('composerSendControls')
            QTest.qWait(180)
            assert send.isVisible()
            if phase == 'after':
                assert not status.isVisible()
                assert abs(row.width() - send.width()) <= 0.5, (row.width(), send.width())
            elif size == 'wide':
                assert status.isVisible() and 'Alt+Enter' in status.property('text')
                assert row.width() > send.width()
            bounds = composer.mapRectToScene(composer.boundingRect()).toAlignedRect().adjusted(-12, -8, 12, 12)
            capture = window.grabWindow()
            assert capture.copy(bounds).save(str(out / f'{phase}-{size}.png'))
            print(f'{phase} {size}: window={window.width()} composer={composer.width():.1f} '
                  f'trailing={row.width():.1f} send={send.width():.1f} '
                  f'status={status.property("text")!r} visible={status.isVisible()}')

        field.forceActiveFocus()
        check_newline_and_ime(window, field)
        submitted = QSignalSpy(field.submitted)
        field.setProperty('text', '发送键验收')
        QTest.keyClick(window, Qt.Key_Return)
        assert submitted.count() == 1, 'Enter did not reach the main composer submit handler'
        print('PASS actual ChatInput: Enter submit signal, Ctrl/Alt/Shift Enter newline, synthetic Chinese preedit guard and commit')
    finally:
        backend.close()
        delete(engine)
        app.processEvents()
