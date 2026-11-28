import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QObject

from app import windows_sandbox
from app.git_for_windows import find_git_bash
from app.sandbox_git_bash import VERSION, component_archive


class WindowsSandboxStartupTests(unittest.TestCase):
    def test_finds_git_bash_on_path_or_at_the_configured_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            git = root / 'Git'
            shell = git / 'bin/bash.exe'
            for path in (shell, git / 'cmd/git.exe', git / 'usr/bin/msys-2.0.dll'):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            other = root / 'bash.exe'
            other.touch()
            self.assertEqual(find_git_bash(environment={'PATH': str(root) + os.pathsep + str(shell.parent)}), str(shell.resolve()))
            self.assertEqual(find_git_bash(str(shell)), str(shell.resolve()))
            self.assertIsNone(find_git_bash(str(other)))

    def test_component_is_hash_checked_and_reused_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = b'patched archive'
            sha256 = hashlib.sha256(content).hexdigest()
            archive = root / f'{VERSION}-{sha256[:12]}.tar.xz'
            manifest = root / 'component.json'
            manifest.write_text(json.dumps(dict(name=archive.name, sha256=sha256, size=len(content))), encoding='utf-8')
            archive.write_bytes(content)
            with patch('app.update_download.download_asset') as download:
                self.assertEqual(component_archive(manifest, root, lambda _: None), archive)
                download.assert_not_called()
                archive.write_bytes(b'x' * len(content))
                download.return_value = str(root / 'verified-download')
                self.assertEqual(component_archive(manifest, root, lambda _: None), root / 'verified-download')
                asset = download.call_args.args[0]
                self.assertEqual((asset['size'], asset['sha256']), (len(content), sha256))
                self.assertTrue(asset['url'].endswith('/' + archive.name))

    def test_enabling_sandbox_does_not_prepare_git_bash_until_requested(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = QObject()
            backend.root = root
            backend.store = SimpleNamespace(directory=root / 'profile', data={'agent': {'windowsSandboxEnabled': True}})
            with patch.object(windows_sandbox, 'os', SimpleNamespace(name='nt')), \
                 patch.object(windows_sandbox.WindowsSandbox, '_prepare') as prepare:
                sandbox = windows_sandbox.WindowsSandbox(backend)
                self.assertTrue(sandbox.state['enabled'])
                prepare.assert_not_called()
                sandbox.prepare_for_command()
                prepare.assert_called_once()

    def test_only_existing_state_requires_a_startup_status_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = QObject()
            backend.root = root
            backend.store = SimpleNamespace(directory=root / 'profile', data={'agent': {}})
            launcher = root / f'runtime/releases/{windows_sandbox.RELEASE_NAME}/bin/windows-sandbox/umeko-sandbox.exe'
            launcher.parent.mkdir(parents=True)
            launcher.touch()
            with patch.object(windows_sandbox, 'os', SimpleNamespace(name='nt')):
                with patch.object(windows_sandbox.WindowsSandbox, '_launch') as launch:
                    self.assertEqual(windows_sandbox.WindowsSandbox(backend).state['level'], 'off')
                    launch.assert_not_called()
                    (backend.store.directory / 'windows-sandbox').mkdir(parents=True)
                    windows_sandbox.WindowsSandbox(backend)
                    launch.assert_called_once_with('status')
