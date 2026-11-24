"""Verify the New conversation chooser and the project's existing plus action."""
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software')

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from app import session_workspace
from main import create_application


def test():
    with tempfile.TemporaryDirectory(prefix='umeko-session-workspace-') as temporary:
        base = Path(temporary).resolve()
        first, second, remote = (base / name for name in ('Folder A', 'Folder B', "Remote 'folder'"))
        for folder in (first, second, remote / 'Subfolder'):
            folder.mkdir(parents=True)
        os.environ.update(UMEKO_DATA_DIR=str(base / 'profile'), PI_CODING_AGENT_DIR=str(base / 'agent'), UMEKO_LANGUAGE='zh')
        app, engine, backend = create_application()
        window = engine.rootObjects()[0]
        window.resize(1320, 860)

        def find(name, title=None):
            pending = [window.contentItem()]
            while pending:
                item = pending.pop()
                if item.objectName() == name and (title is None or item.property('title') == title):
                    return item
                pending.extend(item.childItems())

        def wait(condition, detail):
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                QTest.qWait(25)
                if condition():
                    return
            raise AssertionError(detail)

        def click(name, title=None):
            def ready():
                item = find(name, title)
                return item and item.isVisible() and item.isEnabled()
            wait(ready, (name, title))
            item = find(name, title)
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, item.mapToScene(item.boundingRect().center()).toPoint())
            QTest.qWait(160)

        try:
            backend.setWorkspace(first.as_uri())
            backend.setWorkspace(second.as_uri())
            before = backend._view
            backend.setDraft('Keep this draft')
            click('newChatButton')
            assert find('sessionWorkspaceSelectedPath').property('text') == str(second)
            click('sessionWorkspaceCancel')
            assert backend._view is before and before.draft == 'Keep this draft'
            click('newChatButton')
            click('sessionWorkspaceLocalFolder', 'Folder A')
            click('sessionWorkspaceConfirm')
            assert backend._view.workspace == str(first) and backend._view is not before
            first_draft = backend._view
            first_row = next(row for row in backend.projectRows if row['path'] == str(first))
            click('newProjectSession_' + first_row['id'])
            assert backend._view is not first_draft and backend._view.workspace == str(first)
            assert not find('sessionWorkspaceConfirm')

            if os.name == 'nt':
                return
            fixture_ssh = base / 'ssh-fixture'
            fixture_ssh.write_text('#!/bin/sh\nfor arg do command=$arg; done\nexec /bin/sh -c "$command"\n')
            fixture_ssh.chmod(0o700)
            live = os.environ.get('UMEKO_TEST_SSH_CONFIG')
            executable = session_workspace.ssh_client() if live else str(fixture_ssh)
            options = ['-F', live, *session_workspace.SSH_OPTIONS] if live else session_workspace.SSH_OPTIONS
            with patch.object(session_workspace, 'ssh_client', return_value=executable), patch.object(session_workspace, 'SSH_OPTIONS', options):
                click('newChatButton')
                click('sessionWorkspaceSsh')
                find('sessionWorkspaceSshHost').setProperty('text', 'umeko-loopback')
                find('sessionWorkspaceSshPath').setProperty('text', str(remote))
                click('sessionWorkspaceBrowseSsh')
                click('sessionWorkspaceRemoteFolder', 'Subfolder')
                wait(lambda: find('sessionWorkspaceSelectedPath').property('text') == str(remote / 'Subfolder'), 'SSH child folder')
                click('sessionWorkspaceSshParent')
                wait(lambda: find('sessionWorkspaceSelectedPath').property('text') == str(remote), 'SSH parent folder')
                click('sessionWorkspaceConfirm')
                remote_project = next(row for row in backend.projectRows if row.get('ssh'))
                assert remote_project['ssh'] == {'host': 'umeko-loopback', 'path': str(remote)}
                assert backend.sshWorkspace and backend._view.workspace == remote_project['path']
                assert backend.sessionWorkspace.runtime(backend._view.workspace)['path'] == str(remote)
                click('newChatButton')
                assert find('sessionWorkspaceSshHost').property('text') == 'umeko-loopback'
                assert find('sessionWorkspaceSshPath').property('text') == str(remote)
                QTest.keyClick(window, Qt.Key_Escape)
                wait(lambda: not find('sessionWorkspaceConfirm'), 'Escape closes the chooser')
            print('SESSION_WORKSPACE_UI_OK', 'live OpenSSH' if live else 'fixture SSH')
        finally:
            backend.close()
            window.hide()
            engine.deleteLater()
            app.processEvents()


if __name__ == '__main__':
    test()
