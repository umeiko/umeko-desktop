"""Exercise the conditional Windows Python Launcher guidance with a real child."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(sys.platform == "win32", "Windows Python Launcher guidance")
class WindowsPythonNoteTests(unittest.TestCase):
    def test_py3_starts_an_installed_python_interpreter(self):
        launcher = shutil.which("py")
        if launcher is None:
            self.skipTest("The documented py -3 alternative requires Python Launcher")
        with tempfile.TemporaryDirectory(prefix="umeko-python-note-") as temporary:
            root = Path(temporary)
            profile = root / "profile"
            agent = profile / "agent"
            workspace = root / "workspace"
            agent.mkdir(parents=True)
            workspace.mkdir()
            environment = dict(os.environ)
            environment["UMEKO_DATA_DIR"] = str(profile)
            environment["PI_CODING_AGENT_DIR"] = str(agent)
            environment["QT_QPA_PLATFORM"] = "offscreen"
            environment["QT_QUICK_BACKEND"] = "software"
            child = subprocess.run(
                [launcher, "-3", "-c", "import json, sys; print(json.dumps({'executable': sys.executable, 'version': list(sys.version_info[:3])}))"],
                cwd=workspace, env=environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=15,
            )
            self.assertEqual(child.returncode, 0, child.stderr)
            result = json.loads(child.stdout)
            self.assertTrue(Path(result["executable"]).is_file(), result)
            self.assertEqual(result["version"][0], 3, result)
            self.assertEqual(len(result["version"]), 3, result)
            self.assertTrue(all(isinstance(part, int) and part >= 0 for part in result["version"]), result)


if __name__ == "__main__":
    unittest.main()
