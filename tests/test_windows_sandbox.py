import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QObject

from app import windows_sandbox


class WindowsSandboxStartupTests(unittest.TestCase):
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
