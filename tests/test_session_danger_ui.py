"""Discoverable offscreen checks for the dangerous-approval dialog and menu."""
import os
import subprocess
import sys
import unittest
from pathlib import Path


class SessionDangerUITests(unittest.TestCase):
    def test_chinese_and_english(self):
        root = Path(__file__).resolve().parents[1]
        for language in ("zh", "en"):
            with self.subTest(language=language):
                result = subprocess.run([sys.executable, str(root / "tests/session_danger_ui.py"), language],
                    cwd=root, env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"},
                    capture_output=True, text=True, encoding="utf-8", timeout=60,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("SESSION_DANGER_UI_OK " + language, result.stdout)
