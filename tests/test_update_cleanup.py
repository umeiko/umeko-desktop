"""Cleanup runs in a background worker only after a packaged application's startup."""
import json
import platform
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QProcess, QStandardPaths
from PySide6.QtTest import QTest
from app.update import start_update_cleanup

APP = QCoreApplication.instance() or QCoreApplication([])


class StartupCleanupTests(unittest.TestCase):
    def wait(self, process):
        for _ in range(500):
            QTest.qWait(10)
            if process not in getattr(APP, '_update_cleanup_workers', []): return
        self.fail('cleanup worker did not exit')

    def test_source_start_does_not_clean(self):
        with patch('app.update.sys.frozen', False, create=True):
            self.assertIsNone(start_update_cleanup(Path('.'), Path('.')))

    def test_packaged_start_cleans_legacy_files_and_preserves_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            install, profile, cache = base / 'Umeko', base / 'profile', base / 'cache'
            downloads = base / 'downloads' / 'Umeko'
            backup = base / 'Umeko.previous-12345678-1234-1234-1234-123456789abc'
            for directory in (install, profile, cache, downloads, backup): directory.mkdir(parents=True)
            metadata = dict(version='1.2.3', system=platform.system(), architecture=platform.machine())
            executable = Path('Contents/MacOS/Umeko') if sys.platform == 'darwin' else Path('Umeko.exe')
            for directory in (install, backup):
                (directory / 'build-info.json').write_text(json.dumps(metadata))
                (directory / executable).parent.mkdir(parents=True, exist_ok=True)
                (directory / executable).write_text('program')
            (profile / 'settings.json').write_text('settings')
            target = {'win32': 'windows', 'darwin': 'macos', 'linux': 'linux'}[sys.platform]
            architecture = 'arm64' if platform.machine().lower() in ('arm64', 'aarch64') else 'x64'
            package = downloads / f'Umeko-1.2.3-{target}-{architecture}-123abcd.zip'
            package.write_text('download')
            runtime = install / 'runtime'; runtime.mkdir()
            source = Path(__file__).resolve().parents[1] / 'runtime'
            for name in ('update-engine.mjs', 'update-cleanup.mjs'): shutil.copyfile(source / name, runtime / name)
            locations = {QStandardPaths.CacheLocation: str(cache), QStandardPaths.DownloadLocation: str(base / 'downloads')}
            with patch('app.update.sys.frozen', True, create=True), \
                    patch('app.update.sys.executable', str(install / executable)), \
                    patch('app.update.QStandardPaths.writableLocation', side_effect=locations.__getitem__), \
                    patch('app.update.node_executable', return_value=shutil.which('node')):
                worker = start_update_cleanup(install, profile)
                self.assertIsNotNone(worker)
                self.wait(worker)
            self.assertFalse(backup.exists())
            self.assertFalse(package.exists())
            self.assertEqual((profile / 'settings.json').read_text(), 'settings')
            self.assertTrue((install / executable).exists())
            self.assertFalse(list(cache.glob('cleanup-*.json')))

    def test_missing_runtime_is_logged_without_a_startup_exception(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            with patch('app.update.sys.frozen', True, create=True), self.assertLogs(level='ERROR'):
                self.assertIsNone(start_update_cleanup(base, base / 'profile'))


if __name__ == '__main__': unittest.main()
