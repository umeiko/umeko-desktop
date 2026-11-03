"""File-backed smoke output must not wait for a descendant's inherited pipe."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from scripts.ci_process import run_logged


def process_running(pid):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:
                return False
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return kernel.WaitForSingleObject(handle, 0) == 258
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class LoggedProcessTests(unittest.TestCase):
    def wait_for(self, predicate):
        deadline = time.monotonic() + 5
        while not predicate():
            if time.monotonic() >= deadline:
                self.fail("Owned fixture did not finish its requested transition")
            time.sleep(0.02)

    def temporary(self):
        root = os.environ.get("UMEKO_CI_PROCESS_TEST_ROOT")
        if root:
            Path(root).mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(prefix="ci-process-", dir=root)
        self.addCleanup(directory.cleanup)
        return Path(directory.name)

    def test_parent_exit_does_not_wait_for_descendant_output_handle(self):
        root = self.temporary()
        release, ready, done = (root / name for name in ("release", "child.pid", "done"))
        output = root / "application-output.log"
        descendant = '''import os, pathlib, sys, time
release, ready, done = map(pathlib.Path, sys.argv[1:])
pending = ready.with_suffix(".tmp")
pending.write_text(str(os.getpid()))
pending.replace(ready)
print("DESCENDANT_READY", flush=True)
deadline = time.monotonic() + 15
while not release.exists() and time.monotonic() < deadline:
    time.sleep(0.02)
done.touch()
'''
        parent = '''import pathlib, subprocess, sys, time
subprocess.Popen([sys.executable, "-S", "-c", sys.argv[1], *sys.argv[2:]],
    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
ready = pathlib.Path(sys.argv[3])
deadline = time.monotonic() + 5
while not ready.exists():
    if time.monotonic() >= deadline:
        raise RuntimeError("Descendant did not start")
    time.sleep(0.02)
print("EXIT:0", flush=True)
'''
        try:
            result = run_logged([sys.executable, "-S", "-c", parent, descendant,
                str(release), str(ready), str(done)], output, timeout=5)
            self.assertEqual(result.returncode, 0)
            self.assertTrue(process_running(int(ready.read_text())))
            self.assertFalse(done.exists())
            self.assertIn("EXIT:0", output.read_text(encoding="utf-8"))
        finally:
            release.touch()
            if ready.exists():
                self.wait_for(done.exists)
                if os.name == "nt":
                    self.wait_for(lambda: not process_running(int(ready.read_text())))

    def test_running_parent_still_times_out_and_keeps_output(self):
        output = self.temporary() / "application-output.log"
        with self.assertRaises(subprocess.TimeoutExpired):
            run_logged([sys.executable, "-S", "-c",
                'import time; print("PARENT_STILL_RUNNING", flush=True); time.sleep(30)'],
                output, timeout=1)
        self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()
