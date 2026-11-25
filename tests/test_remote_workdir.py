from __future__ import annotations

import base64
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / 'plugin-runtime') not in sys.path:
    sys.path.insert(0, str(ROOT / 'plugin-runtime'))

from app.platform_support import normalize_projects
from app.workspace_executor import WorkspaceExecutor


def _load_plugin_package(plugin_name: str, submodule: str = 'plugin'):
    pkg_name = f'_umeko_test_pkg_{plugin_name.replace("-", "_")}'
    scripts_dir = ROOT / 'umeko-plugins' / plugin_name / 'scripts'
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(scripts_dir)]
        sys.modules[pkg_name] = pkg
    full_name = f'{pkg_name}.{submodule}'
    path = scripts_dir / f'{submodule}.py'
    spec = importlib.util.spec_from_file_location(full_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


class _FakeRemoteService:
    def __init__(self, handlers=None):
        self.handlers = handlers or {}
        self.calls = []

    def call(self, method: str, params: dict | None = None, *, timeout: float = 120.0) -> dict:
        self.calls.append((method, dict(params or {})))
        if method == 'workspaceOp':
            op = (params or {}).get('op')
            fn = self.handlers.get(op)
            if callable(fn):
                return fn(params or {})
        fn = self.handlers.get(method)
        if callable(fn):
            return fn(params or {})
        return {'ok': False, 'error': f'Unhandled {method}'}


class WorkspaceExecutorAndModelTests(unittest.TestCase):
    def test_normalize_projects_preserves_remote_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            mirror = str(Path(tmp) / 'remote-workspaces' / 'dev' / 'app-12345678')
            data = {
                'projects': [
                    {'id': 'p1', 'name': 'dev:/home/dev/app', 'path': mirror,
                     'environment': 'dev', 'remotePath': '/home/dev/app', 'remoteHost': 'dev-host', 'remotePlatform': 'linux'},
                    {'id': 'p2', 'name': 'dup', 'path': mirror},
                ],
                'activeProject': 'p1',
                'removedProjects': [],
            }
            normalize_projects(data)
            rows = data['projects']
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['environment'], 'dev')
            self.assertEqual(rows[0]['remotePath'], '/home/dev/app')
            self.assertEqual(rows[0]['remoteHost'], 'dev-host')
            self.assertEqual(rows[0]['remotePlatform'], 'linux')

    def test_workspace_executor_local_and_remote_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            local_dir = Path(tmp) / 'local'
            local_dir.mkdir()
            (local_dir / 'hello.txt').write_text('local content', encoding='utf-8')
            mirror_dir = Path(tmp) / 'mirror'
            mirror_dir.mkdir()
            cache_root = Path(tmp) / 'cache'

            remote_meta = {
                'environment': 'srv',
                'host': 'dev-host',
                'platform': 'linux',
                'remotePath': '/home/dev/app',
            }
            fake_service = _FakeRemoteService({
                'readDir': lambda p: {'ok': True, 'entries': [{'name': 'src', 'path': '/home/dev/app/src', 'isDirectory': True, 'isFile': False}]},
                'readFile': lambda p: {'ok': True, 'dataBase64': base64.b64encode(b'remote bytes').decode('ascii'), 'size': 12},
                'exec': lambda p: {'ok': True, 'stdout': 'ok\n', 'stderr': '', 'exitCode': 0},
                'sshTarget': lambda p: {'ok': True, 'sshClient': 'ssh', 'host': 'dev-host', 'platform': 'linux', 'remotePath': '/home/dev/app'},
            })
            controller = SimpleNamespace(
                _remote_service=fake_service,
                store=SimpleNamespace(directory=cache_root),
                _remote_project_for_workspace=lambda ws: remote_meta if Path(ws).resolve() == mirror_dir.resolve() else None,
            )
            executor = WorkspaceExecutor(controller)

            # Local workspace reads local files directly
            local_session = {'workspace': str(local_dir)}
            local_entries = executor.execute(local_session, 'workspace.readDir', {})
            self.assertTrue(local_entries['ok'])
            self.assertEqual([e['name'] for e in local_entries['entries']], ['hello.txt'])

            local_read = executor.execute(local_session, 'workspace.readFile', {'path': 'hello.txt'})
            self.assertTrue(local_read['ok'])
            self.assertEqual(base64.b64decode(local_read['dataBase64']), b'local content')

            # Remote workspace delegates to RemoteServiceClient
            remote_session = {'workspace': str(mirror_dir), 'remoteWorkspace': remote_meta}
            remote_entries = executor.execute(remote_session, 'workspace.readDir', {'path': ''})
            self.assertTrue(remote_entries['ok'])
            self.assertEqual(remote_entries['entries'][0]['name'], 'src')
            self.assertEqual(fake_service.calls[-1][0], 'workspaceOp')
            self.assertEqual(fake_service.calls[-1][1]['op'], 'readDir')

            # Preview downloads remote file into cache/remote-previews
            preview = executor.execute(remote_session, 'workspace.previewFile', {'path': 'README.md'})
            self.assertTrue(preview['ok'])
            cached_file = Path(preview['localPath'])
            self.assertTrue(cached_file.is_file())
            self.assertEqual(cached_file.read_bytes(), b'remote bytes')
            self.assertIn('remote-previews', str(cached_file))

    def test_controller_remote_project_persistence_and_reopen(self):
        from PySide6.QtWidgets import QApplication
        from app.controller import Controller

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / 'profile'
            agent_dir = Path(tmp) / 'agent'
            profile.mkdir()
            agent_dir.mkdir()
            with patch.dict(os.environ, {'UMEKO_DATA_DIR': str(profile), 'PI_CODING_AGENT_DIR': str(agent_dir)}):
                ctrl = Controller(ROOT)
                try:
                    ctrl._remote_environments.add('lab', 'dev-host', 'linux')
                    ok = ctrl.setRemoteWorkspace('lab', '/home/dev/demo')
                    self.assertTrue(ok)
                    mirror = ctrl.store.data['workspace']
                    self.assertTrue(Path(mirror).is_dir())
                    self.assertEqual(ctrl.activeRemoteWorkspace.get('environment'), 'lab')
                    self.assertEqual(ctrl.activeRemoteWorkspace.get('remotePath'), '/home/dev/demo')
                    rows = ctrl.projectRows
                    remote_row = next(r for r in rows if r.get('environment') == 'lab')
                    self.assertEqual(remote_row['name'], 'dev-host:/home/dev/demo')
                    self.assertTrue(remote_row['isRemote'])
                    project_id = remote_row['id']
                finally:
                    ctrl.close()

                # Reopen on a fresh Controller instance (simulating app restart)
                ctrl2 = Controller(ROOT)
                try:
                    rows2 = ctrl2.projectRows
                    remote_row2 = next(r for r in rows2 if r.get('id') == project_id)
                    self.assertEqual(remote_row2['remotePath'], '/home/dev/demo')
                    self.assertEqual(remote_row2['remoteHost'], 'dev-host')
                    ctrl2.openProject(project_id)
                    self.assertEqual(ctrl2.activeRemoteWorkspace.get('remotePath'), '/home/dev/demo')
                finally:
                    ctrl2.close()
        self.assertIsNotNone(app)


class RemotePluginsBehaviorTests(unittest.TestCase):
    def _mock_ctx(self, *, remote_ws, calls, exec_fn=None, read_dir_fn=None, stat_fn=None, preview_fn=None, ssh_fn=None):
        import threading

        def _workspace_exec(argv, cwd='.', env=None, timeout_ms=30000, max_output_bytes=None, stdin_text=None, allow_outside=False, session=None):
            calls.append(('exec', list(argv), cwd))
            if exec_fn:
                return exec_fn(argv, cwd, env, stdin_text)
            return {'ok': True, 'stdout': '', 'stderr': '', 'exitCode': 0}

        def _workspace_read_dir(path='.', with_metadata=False, session=None):
            calls.append(('readDir', path))
            return read_dir_fn(path) if read_dir_fn else {'ok': True, 'entries': []}

        def _workspace_stat(path='.', session=None):
            calls.append(('stat', path))
            return stat_fn(path) if stat_fn else {'ok': True, 'exists': True, 'isFile': True, 'isDirectory': False, 'size': 10}

        def _workspace_preview_file(path, session=None):
            calls.append(('previewFile', path))
            return preview_fn(path) if preview_fn else {'ok': True, 'localPath': '/tmp/cache/x.txt'}

        def _workspace_ssh_target(session=None):
            calls.append(('sshTarget', session))
            return ssh_fn() if ssh_fn else {'ok': True, 'sshClient': 'ssh', 'host': remote_ws['host'],
                                            'platform': remote_ws['platform'], 'remotePath': remote_ws['remotePath']}

        return SimpleNamespace(
            workspace=Path('/local/mirror'),
            remote_workspace=remote_ws,
            is_remote=True,
            session={'id': 's1', 'workspace': '/local/mirror', 'remoteWorkspace': remote_ws},
            settings={},
            config={},
            cancelled=threading.Event(),
            require=lambda *a, **k: None,
            workspace_exec=_workspace_exec,
            workspace_read_dir=_workspace_read_dir,
            workspace_stat=_workspace_stat,
            workspace_preview_file=_workspace_preview_file,
            workspace_ssh_target=_workspace_ssh_target,
            workspace_home=lambda session=None: {'ok': True, 'home': '/home/dev', 'tempDir': '/tmp'},
            workspace_rename=lambda src, dst, session=None: calls.append(('rename', src, dst)) or {'ok': True},
            workspace_remove=lambda path, recursive=False, force=False, allow_outside=False, session=None: calls.append(('remove', path, recursive)) or {'ok': True},
            workspace_mkdir=lambda path, recursive=True, allow_outside=False, session=None: calls.append(('mkdir', path)) or {'ok': True},
            workspace_write_file=lambda path, data_b64, session=None: calls.append(('writeFile', path)) or {'ok': True},
            workspace_read_file=lambda path, session=None: calls.append(('readFile', path)) or {'ok': True, 'dataBase64': ''},
            preview_file=lambda p: calls.append(('preview_ui', p)) or {'ok': True},
            attach_file=lambda p: calls.append(('attach_ui', p)) or {'ok': True},
            emit=lambda ev: calls.append(('emit', ev)),
            capture_session=lambda: {'id': 's1', 'workspace': '/local/mirror', 'remoteWorkspace': remote_ws},
            publish=lambda *a, **k: None,
            notify=lambda *a, **k: None,
        )

    def test_file_tree_plugin_remote_listing_preview_and_copy_path(self):
        ft = _load_plugin_package('file-tree', 'plugin')
        calls = []
        ctx = self._mock_ctx(
            remote_ws={'environment': 'dev', 'host': 'dev-host', 'platform': 'linux', 'remotePath': '/home/dev/repo'},
            calls=calls,
            read_dir_fn=lambda p: {'ok': True, 'entries': [
                {'name': 'src', 'path': '/home/dev/repo/src', 'isDirectory': True, 'isFile': False},
                {'name': 'README.md', 'path': '/home/dev/repo/README.md', 'isDirectory': False, 'isFile': True},
            ]} if p in ('', '.') else {'ok': True, 'entries': []},
            preview_fn=lambda p: {'ok': True, 'localPath': '/cache/README.md'},
        )
        plugin = ft.Explorer(ctx)
        res = plugin.handle('list', {})
        names = [row['name'] for row in res['entries']]
        self.assertEqual(names, ['src', 'README.md'])
        self.assertEqual(res['entries'][1]['path'], 'README.md')

        opened = plugin.handle('preview', {'path': 'README.md'})
        self.assertTrue(opened.get('opened'))
        self.assertIn(('previewFile', 'README.md'), calls)
        self.assertTrue(any(c[0] == 'emit' and c[1].get('event') == 'preview.file' and c[1]['arguments']['path'] == '/cache/README.md' for c in calls))

        copied = plugin.handle('copyPath', {'path': 'README.md'})
        self.assertEqual(copied['path'], '/home/dev/repo/README.md')

    def test_git_viewer_plugin_remote_status_and_branches(self):
        gv = _load_plugin_package('git-viewer', 'plugin')
        calls = []

        def fake_git(argv, cwd, env, stdin_text):
            cmd = ' '.join(argv)
            if 'rev-parse --show-toplevel' in cmd:
                return {'ok': True, 'stdout': '/home/dev/repo\n', 'stderr': '', 'exitCode': 0}
            if 'rev-parse --show-prefix' in cmd:
                return {'ok': True, 'stdout': '\n', 'stderr': '', 'exitCode': 0}
            if 'symbolic-ref' in cmd or 'rev-parse --abbrev-ref HEAD' in cmd:
                return {'ok': True, 'stdout': 'main\n', 'stderr': '', 'exitCode': 0}
            if 'status --porcelain=v1 -z' in cmd:
                return {'ok': True, 'stdout': ' M app.py\0?? notes.txt\0', 'stderr': '', 'exitCode': 0}
            if 'rev-list --left-right --count' in cmd:
                return {'ok': True, 'stdout': '0\t0\n', 'stderr': '', 'exitCode': 0}
            if 'for-each-ref' in cmd:
                return {'ok': True, 'stdout': 'main\t*\t\n', 'stderr': '', 'exitCode': 0}
            return {'ok': True, 'stdout': '', 'stderr': '', 'exitCode': 0}

        ctx = self._mock_ctx(
            remote_ws={'environment': 'dev', 'host': 'dev-host', 'platform': 'linux', 'remotePath': '/home/dev/repo'},
            calls=calls,
            exec_fn=fake_git,
        )
        plugin = gv.GitViewer(ctx)
        status = plugin.handle('status', {})
        self.assertTrue(status['repository'])
        self.assertEqual(status['branch'], 'main')
        paths = [e['path'] for e in status['entries']]
        self.assertIn('app.py', paths)
        self.assertIn('notes.txt', paths)
        self.assertTrue(any(c[0] == 'exec' and c[1][0] == 'git' for c in calls))

    def test_change_review_remote_snapshot_runs_private_git_on_remote(self):
        _load_plugin_package('change-review', 'snapshots')
        rs = _load_plugin_package('change-review', 'remote_snapshots')
        calls = []
        tree_counter = {'n': 0}

        def fake_exec(argv, cwd, env, stdin_text):
            cmd = ' '.join(argv)
            if 'write-tree' in cmd:
                tree_counter['n'] += 1
                ch = 'a' if tree_counter['n'] == 1 else 'b'
                return {'ok': True, 'stdout': ch * 40 + '\n', 'stderr': '', 'exitCode': 0}
            if 'ls-tree' in cmd:
                return {'ok': True, 'stdout': '100644 blob ' + ('1' * 40) + '\tsrc/app.py\0', 'stderr': '', 'exitCode': 0}
            if 'diff-tree' in cmd and '--name-status' in cmd:
                return {'ok': True, 'stdout': 'M\0src/app.py\0', 'stderr': '', 'exitCode': 0}
            if 'diff-tree' in cmd and '--numstat' in cmd:
                return {'ok': True, 'stdout': '1\t1\tsrc/app.py\0', 'stderr': '', 'exitCode': 0}
            if 'diff --no-color' in cmd or 'diff ' in cmd:
                return {'ok': True, 'stdout': '@@ -1 +1 @@\n-old\n+new\n', 'stderr': '', 'exitCode': 0}
            return {'ok': True, 'stdout': '', 'stderr': '', 'exitCode': 0}

        with tempfile.TemporaryDirectory() as tmp:
            session = {
                'id': 's1',
                'workspace': tmp,
                'remoteWorkspace': {'environment': 'dev', 'host': 'dev-host', 'platform': 'linux', 'remotePath': '/home/dev/repo'},
            }
            ctx = self._mock_ctx(remote_ws=session['remoteWorkspace'], calls=calls, exec_fn=fake_exec)
            snap = rs.RemoteSnapshot(ctx, session, Path(tmp))
            snap.begin()
            summary = snap.finish()
            self.assertEqual(len(summary['entries']), 1)
            self.assertEqual(summary['entries'][0]['path'], 'src/app.py')
            diff_res = snap.diff('src/app.py')
            self.assertIn('+new', diff_res['text'])
            snap.close()
            self.assertTrue(any(c[0] == 'remove' for c in calls))

    def test_terminal_remote_ssh_argv_linux_and_windows(self):
        vendor = str(ROOT / 'umeko-plugins/terminal/vendor')
        if vendor not in sys.path:
            sys.path.insert(0, vendor)
        _load_plugin_package('terminal', 'terminal')
        tm = _load_plugin_package('terminal', 'plugin')
        linux_argv = tm._remote_ssh_argv('/usr/bin/ssh', 'dev-host', 'linux', "/home/dev/my'app")
        self.assertEqual(linux_argv[0], '/usr/bin/ssh')
        self.assertIn('-tt', linux_argv)
        self.assertIn('dev-host', linux_argv)
        self.assertIn('exec "${SHELL:-/bin/bash}" -l', linux_argv[-1])

        win_argv = tm._remote_ssh_argv('C:\\Program Files\\Git\\usr\\bin\\ssh.exe', 'win-host', 'windows', 'C:\\work\\app')
        self.assertEqual(win_argv[0], 'C:\\Program Files\\Git\\usr\\bin\\ssh.exe')
        self.assertIn('-tt', win_argv)
        self.assertIn('win-host', win_argv)
        self.assertIn('-EncodedCommand', win_argv[-1])


class WorkspacePickerQmlTests(unittest.TestCase):
    def test_workspace_picker_cache_retry_host_check_and_reconnecting(self):
        from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer, QUrl
        from PySide6.QtQml import QQmlApplicationEngine
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])

        class MockBackend(QObject):
            remoteEnvironmentsChanged = Signal()
            remoteHostsChanged = Signal()
            remoteAddHostFinished = Signal(str, 'QVariantMap')
            remoteHomeFinished = Signal(str, 'QVariantMap')
            remoteBrowseFinished = Signal(str, 'QVariantMap')
            remoteMkdirFinished = Signal(str, 'QVariantMap')
            appearanceChanged = Signal()
            chatChanged = Signal()
            changed = Signal()

            def __init__(self):
                super().__init__()
                self._envs = [{'name': 'dev-box', 'host': 'dev-box', 'platform': 'linux', 'state': 'connected'}]
                self._hosts = [{'alias': 'dev-box', 'hostName': '10.0.0.10', 'user': 'dev', 'port': 22}]
                self._browse_calls = []
                self._fail_once = True
                self._chosen = None

            @Property('QVariantList', notify=remoteEnvironmentsChanged)
            def remoteEnvironments(self):
                return list(self._envs)

            @Property('QVariantList', notify=remoteHostsChanged)
            def sshConfigHosts(self):
                return list(self._hosts)

            @Property(str, notify=appearanceChanged)
            def language(self):
                return 'zh'

            @Property(float, notify=appearanceChanged)
            def fontScale(self):
                return 1.0

            @Property(str, notify=appearanceChanged)
            def lineSpacing(self):
                return 'standard'

            @Property(str, notify=chatChanged)
            def workspace(self):
                return str(ROOT)

            @Property('QVariantMap', notify=chatChanged)
            def activeRemoteWorkspace(self):
                return {}

            @Property('QVariantMap', notify=changed)
            def config(self):
                return {'theme': 'dark', 'fontFamily': ''}

            @Property('QVariantMap', notify=changed)
            def themeStyle(self):
                return {'base': 'dark', 'colors': {}}

            @Slot()
            def refreshSshConfigHosts(self):
                self.remoteHostsChanged.emit()

            @Slot(str, str, result=str)
            def ensureRemoteHost(self, alias, platform=''):
                rid = 'e-1'
                QTimer.singleShot(5, lambda: self.remoteAddHostFinished.emit(
                    rid, {'ok': True, 'environment': {'name': alias, 'host': alias, 'platform': platform or 'linux'}}))
                return rid

            @Slot(str, str, result=str)
            def browseRemoteDirectory(self, name, path):
                rid = f'b-{len(self._browse_calls) + 1}'
                self._browse_calls.append((name, path, rid))
                if self._fail_once:
                    self._fail_once = False
                    res = {'ok': False, 'error': 'temporary network blip', 'name': name, 'host': name, 'path': path}
                else:
                    entries = [
                        {'name': 'alpha', 'path': '/home/dev/alpha', 'isDirectory': True},
                        {'name': 'beta', 'path': '/home/dev/beta', 'isDirectory': True},
                    ]
                    res = {
                        'ok': True, 'name': name, 'host': name, 'path': path or '/home/dev',
                        'parent': '/home', 'platform': 'linux', 'isDriveList': False,
                        'directories': entries, 'entries': entries,
                    }
                QTimer.singleShot(10, lambda: self.remoteBrowseFinished.emit(rid, res))
                return rid

            @Slot(str, result=str)
            def fetchRemoteHome(self, name):
                rid = 'h-1'
                QTimer.singleShot(10, lambda: self.remoteHomeFinished.emit(rid, {'ok': True, 'name': name, 'host': name, 'home': '/home/dev'}))
                return rid

            @Slot(str, str, result=str)
            def createRemoteDirectory(self, name, path):
                rid = 'm-1'
                QTimer.singleShot(10, lambda: self.remoteMkdirFinished.emit(rid, {'ok': True, 'name': name, 'host': name, 'path': path}))
                return rid

            @Slot(str, str, result=bool)
            def setRemoteWorkspace(self, name, path):
                self._chosen = (name, path)
                return True

            @Slot(str)
            def setWorkspace(self, path):
                self._chosen = ('local', path)

        backend = MockBackend()
        qml_text = """
import QtQuick
import QtQuick.Controls
ApplicationWindow {
    width: 820; height: 720; visible: true
    WorkspacePicker {
        id: picker
        objectName: "picker"
        allowRemote: true
    }
}
"""
        warnings = []
        engine = QQmlApplicationEngine()
        engine.addImportPath(str(ROOT / 'app/qml'))
        engine.warnings.connect(lambda errs: warnings.extend(e.toString() for e in errs))
        engine.rootContext().setContextProperty('backend', backend)
        engine.loadData(qml_text.encode('utf-8'), QUrl.fromLocalFile(str(ROOT / 'app/qml/_test_picker.qml')))
        self.assertTrue(engine.rootObjects(), f'Harness QML failed to load: {warnings}')
        root_win = engine.rootObjects()[0]
        picker = root_win.findChild(QObject, 'picker')
        self.assertIsNotNone(picker)

        picker.openPicker('remote')
        picker.openBrowserFresh('/home/dev')
        QTest.qWait(150)
        # First browse failed -> auto-retried once and populated 2 dirs!
        self.assertEqual(len(backend._browse_calls), 2)
        entries_val = picker.property('browserEntries')
        entries_list = entries_val.toVariant() if hasattr(entries_val, 'toVariant') else entries_val
        self.assertEqual(len(entries_list), 2)

        # Second browse of same path within 30s hits cache (no extra RPC)
        picker.requestDirListing('/home/dev', {'fresh': False, 'purpose': 'browse'})
        QTest.qWait(50)
        self.assertEqual(len(backend._browse_calls), 2)

        # Fresh bypass (e.g. after mkdir) forces a new RPC
        picker.requestDirListing('/home/dev', {'fresh': True, 'purpose': 'browse'})
        QTest.qWait(60)
        self.assertEqual(len(backend._browse_calls), 3)

        # Host-match check: a result from another host must be ignored
        picker.requestDirListing('/home/dev/other', {'fresh': True, 'purpose': 'browse'})
        backend.remoteBrowseFinished.emit('stale', {'ok': True, 'host': 'different-host', 'path': '/wrong', 'directories': []})
        QTest.qWait(60)
        self.assertNotEqual(picker.property('currentBrowsePath'), '/wrong')

        # Reconnecting state surfaces as non-error status
        backend._envs[0]['state'] = 'reconnecting'
        backend.remoteEnvironmentsChanged.emit()
        QTest.qWait(30)
        self.assertTrue(picker.property('isReconnecting'))

        import shiboken6
        shiboken6.delete(engine)
        self.assertIsNotNone(app)


if __name__ == '__main__':
    unittest.main()
