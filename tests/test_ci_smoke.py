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

ROOT = Path(__file__).resolve().parents[1]


class SmokeProfileTests(unittest.TestCase):
    def test_packaged_preview_network_helper_runs_offline(self):
        verifier = runpy.run_path(str(ROOT / 'scripts/ci-smoke.py'), run_name='preview_network_fixture')
        with tempfile.TemporaryDirectory() as directory:
            resources = Path(directory)
            (resources / 'runtime').mkdir()
            for name in ('preview-network.mjs', 'update-engine.mjs'):
                shutil.copy2(ROOT / 'runtime' / name, resources / 'runtime' / name)
            env = dict(os.environ, HOME=directory, USERPROFILE=directory, UMEKO_DATA_DIR=directory)
            verifier['verify_preview_network'](Path(shutil.which('node')), resources, env)

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
