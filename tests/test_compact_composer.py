"""Keep QML QApplication cases isolated from discovery's QCoreApplication."""
import os
import subprocess
import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CompactComposerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.pi_runtime import RELEASE_NAME
        source = ROOT / "runtime"
        release = source / "releases" / RELEASE_NAME
        # Project current adapters once; the cases exercise the native engine.
        for path in source.iterdir():
            if path.is_file() and path.suffix in (".mjs", ".json"):
                shutil.copy2(path, release / path.name)
        shutil.copytree(source / "umeko-docs", release / "umeko-docs", dirs_exist_ok=True)

    def run_ui_case(self, name):
        result = subprocess.run([sys.executable, str(ROOT / "tests/compact_composer_case.py"),
                                 "CompactComposerTests." + name, "-v"],
            cwd=ROOT, env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"},
            creationflags=0x08000000 if os.name == "nt" else 0,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_enter_dispatches_idle_compact_with_instructions(self):
        self.run_ui_case(self._testMethodName)

    def test_busy_enter_queues_compact_until_original_turn_finishes(self):
        self.run_ui_case(self._testMethodName)

    def test_compaction_failure_is_shown_as_plain_text(self):
        self.run_ui_case(self._testMethodName)
