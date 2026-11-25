"""Exercise the standard conversation entry points with the shared workspace picker."""
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software')

from PySide6.QtCore import Qt, QMetaObject, Q_ARG
from PySide6.QtTest import QTest
from main import create_application


def test():
    with tempfile.TemporaryDirectory(prefix='umeko-session-workspace-') as temporary:
        base = Path(temporary).resolve()
        first, second = base / 'Folder A', base / 'Folder B #'
        first.mkdir()
        second.mkdir()
        os.environ.update(UMEKO_DATA_DIR=str(base / 'profile'), PI_CODING_AGENT_DIR=str(base / 'agent'), UMEKO_LANGUAGE='zh')
        app, engine, backend = create_application()
        window = engine.rootObjects()[0]
        window.resize(1320, 860)

        def find(name):
            pending = [window.contentItem()]
            while pending:
                item = pending.pop()
                if item.objectName() == name and item.isVisible():
                    return item
                pending.extend(item.childItems())
            return None

        def wait(predicate, detail):
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                QTest.qWait(25)
                if predicate():
                    return
            raise AssertionError(detail)

        def click(name):
            wait(lambda: find(name) and find(name).isEnabled(), name)
            item = find(name)
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, item.mapToScene(item.boundingRect().center()).toPoint())
            QTest.qWait(110)

        try:
            assert backend.setWorkspace(first.as_uri()) and backend.setWorkspace(second.as_uri())
            existing_view = backend._view
            click('newChatButton')
            wait(lambda: find('workspaceRecentLocal'), 'recent folders')
            assert backend._view is existing_view
            assert not find('workspaceTabRemote')
            assert backend.saveDesktopSettings('{"remoteWorkspaceEnabled":true}')
            click('workspaceTabRemote')
            wait(lambda: find('remoteHostCombo'), 'remote host picker')
            assert backend.saveDesktopSettings('{"remoteWorkspaceEnabled":false}')
            wait(lambda: find('workspaceRecentLocal') and not find('workspaceTabRemote'), 'local-only picker after disabling remote')
            chooser = find('workspaceRecentLocal')
            assert chooser.property('count') == 3
            assert QMetaObject.invokeMethod(chooser, 'activated', Qt.DirectConnection, Q_ARG(int, 1))
            wait(lambda: not find('workspaceRecentLocal'), 'picker closes on selection')
            assert backend._view.workspace == str(first) and backend._view is not existing_view
            project = next(row for row in backend.projectRows if row.get('path') == str(second))
            click('newProjectSession_' + project['id'])
            assert backend._view.workspace == str(second) and not find('workspaceTabLocal')
            print('SESSION_WORKSPACE_UI_OK: shared picker, recent folders, SSH entry and project plus')
        finally:
            window.hide()
            backend.close()
            app.quit()


if __name__ == '__main__':
    test()
