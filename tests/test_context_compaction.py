"""Run real QML/Pi acceptance cases outside discovery's QCoreApplication."""
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ContextCompactionTests(unittest.TestCase):
    def run_ui_case(self, name):
        result = subprocess.run([sys.executable, str(ROOT / "tests/context_compaction_case.py"),
                                 "ContextCompactionTests." + name, "-v"],
            cwd=ROOT, env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"},
            creationflags=0x08000000 if os.name == "nt" else 0,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_circle_compacts_in_place_and_busy_action_is_disabled(self):
        self.run_ui_case(self._testMethodName)

    def test_failure_updates_the_running_row(self):
        self.run_ui_case(self._testMethodName)

    def test_process_interruption_finishes_live_and_cold_history(self):
        self.run_ui_case(self._testMethodName)

    def test_process_interruption_finishes_live_tail(self):
        self.run_ui_case(self._testMethodName)
