"""Discoverable offscreen checks for readable approvals, the dsh stop line and dsh settings."""
import os
import subprocess
import sys
import unittest
from pathlib import Path


class DshApprovalUITests(unittest.TestCase):
    def test_languages_and_themes(self):
        root = Path(__file__).resolve().parents[1]
        for language, theme in (("zh", "white"), ("en", "dark")):
            with self.subTest(language=language, theme=theme):
                result = subprocess.run([sys.executable, str(root / "tests/dsh_approval_ui.py"), language, theme],
                    cwd=root, env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"},
                    capture_output=True, text=True, encoding="utf-8", timeout=90,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(f"DSH_APPROVAL_UI_OK {language} {theme}", result.stdout)


if __name__ == "__main__":
    unittest.main()
