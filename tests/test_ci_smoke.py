"""The packaged verifier must work outside the application's Python venv."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import runpy
import shutil
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


class SmokeProfileTests(unittest.TestCase):
    def test_preview_waits_for_verifier_before_capture_and_exit(self):
        from PySide6.QtCore import QCoreApplication, QTimer
        from app.smoke_lifecycle import watch_smoke_finish
        app = QCoreApplication.instance() or QCoreApplication([])
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'finish'
            window = Mock()
            window.grabWindow.return_value.save.return_value = True
            timer = watch_smoke_finish(app, window, str(marker), 'preview.png')
            observed = []

            def verifier_ready():
                observed.append(not window.grabWindow.called)
                marker.write_text('ready', encoding='utf-8')

            QTimer.singleShot(150, verifier_ready)
            watchdog = QTimer()
            watchdog.setSingleShot(True)
            watchdog.timeout.connect(lambda: app.exit(7))
            watchdog.start(2000)
            try:
                self.assertEqual(app.exec(), 0)
                self.assertEqual(observed, [True])
                window.grabWindow.return_value.save.assert_called_once_with('preview.png')
                self.assertFalse(timer.isActive())
            finally:
                timer.stop()
                watchdog.stop()

    def test_preview_capture_failure_is_not_a_successful_exit(self):
        from PySide6.QtCore import QCoreApplication
        from app.smoke_lifecycle import watch_smoke_finish
        app = QCoreApplication.instance() or QCoreApplication([])
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'finish'
            marker.touch()
            window = Mock()
            window.grabWindow.return_value.save.return_value = False
            timer = watch_smoke_finish(app, window, str(marker), 'preview.png')
            try:
                self.assertEqual(app.exec(), 1)
                self.assertFalse(timer.isActive())
            finally:
                timer.stop()

    def test_packaged_preview_network_helper_runs_offline(self):
        verifier = runpy.run_path(str(ROOT / 'scripts/ci-smoke.py'), run_name='preview_network_fixture')
        with tempfile.TemporaryDirectory() as directory:
            resources = Path(directory)
            (resources / 'runtime').mkdir()
            for name in ('preview-network.mjs', 'update-engine.mjs', 'update-cleanup.mjs'):
                shutil.copy2(ROOT / 'runtime' / name, resources / 'runtime' / name)
            env = dict(os.environ, HOME=directory, USERPROFILE=directory, UMEKO_DATA_DIR=directory)
            verifier['verify_preview_network'](Path(shutil.which('node')), resources, env)

    def test_packaged_preview_network_helper_runs_through_resource_symlink(self):
        verifier = runpy.run_path(str(ROOT / 'scripts/ci-smoke.py'), run_name='preview_network_fixture')
        with tempfile.TemporaryDirectory() as directory:
            resources = Path(directory) / 'Resources'
            (resources / 'runtime').mkdir(parents=True)
            for name in ('preview-network.mjs', 'update-engine.mjs', 'update-cleanup.mjs'):
                shutil.copy2(ROOT / 'runtime' / name, resources / 'runtime' / name)
            frameworks = Path(directory) / 'Frameworks'
            frameworks.mkdir()
            node = Path(shutil.which('node'))
            if os.name == 'nt':
                # Junctions model the same resolved-directory alias without
                # requiring Windows' privileged symbolic-link permission.
                result = subprocess.run([str(node), '-e',
                    "require('node:fs').symlinkSync(process.argv[1],process.argv[2],'junction')",
                    str(resources / 'runtime'), str(frameworks / 'runtime')],
                    capture_output=True, text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
                self.assertEqual(result.returncode, 0, result.stderr)
            else:
                (frameworks / 'runtime').symlink_to(resources / 'runtime', target_is_directory=True)
            env = dict(os.environ, HOME=directory, USERPROFILE=directory, UMEKO_DATA_DIR=directory)
            verifier['verify_preview_network'](node, frameworks, env)

    def test_profile_isolation_needs_only_the_standard_library(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / 'profile'
            profile.mkdir()
            settings = profile / 'settings.json'
            settings.write_text(json.dumps({'ui': {'sidebarWidth': 300}, 'agent': {'instructions': 'preserve'}}))
            script = '''import runpy, sys
from pathlib import Path
verifier = runpy.run_path(sys.argv[1], run_name="smoke_fixture")
verifier["isolated_profile"](Path(sys.argv[2]))
assert not any(name.startswith("PySide6") for name in sys.modules)
'''
            result = subprocess.run([sys.executable, '-S', '-c', script,
                str(ROOT / 'scripts/ci-smoke.py'), str(profile)],
                capture_output=True, text=True, timeout=20,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            saved = json.loads(settings.read_text(encoding='utf-8'))
            self.assertEqual(saved['agent']['agentDir'], str((profile / 'agent').resolve()))
            self.assertEqual(saved['agent']['instructions'], 'preserve')
            self.assertEqual(saved['ui'], {'sidebarWidth': 300})
