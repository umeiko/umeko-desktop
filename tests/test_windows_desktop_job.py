import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCH_DESKTOP = """
import subprocess
import sys
import time
from pathlib import Path
from app.windows_job import contain_desktop_processes, handoff_creation_flag

contain_desktop_processes()
command = [sys.executable, '-B', 'plugin-runtime/worker.py']
worker = subprocess.Popen(command, stdin=sys.stdin)
installer = subprocess.Popen(command, stdin=sys.stdin, creationflags=handoff_creation_flag())
Path(sys.argv[1]).write_text(f'{worker.pid} {installer.pid}', encoding='ascii')
time.sleep(60)
"""


@unittest.skipUnless(sys.platform == "win32", "Windows Job Object")
class WindowsDesktopJobTests(unittest.TestCase):
    def test_worker_exits_with_desktop_and_update_handoff_can_finish(self):
        import _winapi

        with tempfile.TemporaryDirectory() as directory:
            ready = Path(directory) / "children.txt"
            with subprocess.Popen(
                [sys.executable, "-c", LAUNCH_DESKTOP, str(ready)],
                cwd=ROOT,
                stdin=subprocess.PIPE,
            ) as desktop:
                handles = []
                try:
                    deadline = time.monotonic() + 10
                    pids = []
                    while time.monotonic() < deadline and desktop.poll() is None:
                        if ready.exists():
                            pids = ready.read_text(encoding="ascii").split()
                            if len(pids) == 2:
                                break
                        time.sleep(0.02)
                    self.assertEqual(len(pids), 2, f"Desktop exit code: {desktop.poll()}")
                    synchronize_and_terminate = 0x00100001
                    for pid in pids:
                        handles.append(_winapi.OpenProcess(
                            synchronize_and_terminate, False, int(pid)))
                    worker, installer = handles
                    self.assertEqual(_winapi.WaitForSingleObject(worker, 0), _winapi.WAIT_TIMEOUT)
                    desktop.kill()
                    desktop.wait(timeout=5)
                    # The test still owns stdin. An EOF cannot explain the worker's exit.
                    self.assertEqual(_winapi.WaitForSingleObject(worker, 5000), _winapi.WAIT_OBJECT_0)
                    self.assertEqual(_winapi.WaitForSingleObject(installer, 0), _winapi.WAIT_TIMEOUT)
                finally:
                    if desktop.poll() is None:
                        desktop.kill()
                    for child in handles:
                        try:
                            if _winapi.WaitForSingleObject(child, 0) == _winapi.WAIT_TIMEOUT:
                                _winapi.TerminateProcess(child, 1)
                        finally:
                            _winapi.CloseHandle(child)
