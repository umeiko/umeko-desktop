"""Include the session-danger Node behavior suite in Python test discovery."""
from pathlib import Path
import shutil
import subprocess
import unittest


class SessionDangerRuntimeTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_session_danger_runtime(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [shutil.which("node"), "--require", "./tests/tool-permissions-windowless.cjs",
             "--test", "tests/session-danger-permissions.test.mjs"],
            cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
