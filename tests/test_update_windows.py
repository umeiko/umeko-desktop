"""Focused native Windows updater tests; all child processes are hidden."""

import ctypes
from ctypes import wintypes
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from app import update_windows


class ProcessLayoutTests(unittest.TestCase):
    def test_peb64_and_peb32_current_directory_layouts(self):
        for pointer_size, params_offset, cwd_offset, pointer_offset in (
            (8, 0x20, 0x38, 8), (4, 0x10, 0x24, 4),
        ):
            with self.subTest(pointer_size=pointer_size):
                path = "C:\\UmekoTests\\issue171\\目录\\"
                encoded = path.encode("utf-16-le")
                pointer_format = "<Q" if pointer_size == 8 else "<I"
                descriptor = bytearray(16 if pointer_size == 8 else 8)
                struct.pack_into("<HH", descriptor, 0, len(encoded), len(encoded) + 2)
                struct.pack_into(pointer_format, descriptor, pointer_offset, 0x3000)
                memory = {
                    (0x1000 + params_offset, pointer_size): struct.pack(pointer_format, 0x2000),
                    (0x2000 + cwd_offset, len(descriptor)): bytes(descriptor),
                    (0x3000, len(encoded)): encoded,
                }
                reader = Mock(side_effect=lambda address, size: memory[(address, size)])
                self.assertEqual(update_windows._read_current_directory(reader, 0x1000, pointer_size), path)
                self.assertEqual(reader.call_count, 3)

    def test_selects_wow64_or_native_peb(self):
        api = object.__new__(update_windows.WindowsAPI)
        api.pointer_size = 8
        api._read_memory = Mock()
        for wow64_peb, expected_peb, expected_size in ((0x2000, 0x2000, 4), (0, 0x1000, 8)):
            with self.subTest(wow64_peb=wow64_peb):
                api._query_peb = Mock(side_effect=lambda handle, wow64=False: wow64_peb if wow64 else 0x1000)
                with patch.object(update_windows, "_read_current_directory", return_value="C:\\test") as reader:
                    self.assertEqual(api._current_directory(123), "C:\\test")
                    self.assertEqual(reader.call_args.args[1:], (expected_peb, expected_size))
                api._query_peb.assert_any_call(123, wow64=True)
                if not wow64_peb:
                    api._query_peb.assert_any_call(123)

    def test_install_directory_boundaries_and_prefixes(self):
        root = "C:\\UmekoTests\\issue171\\install"
        for path in (root, root.upper() + "\\nested\\python.exe", "\\\\?\\" + root, "\\??\\" + root + "\\child"):
            self.assertTrue(update_windows._within_directory(path, root), path)
        self.assertFalse(update_windows._within_directory(root + "-other\\python.exe", root))
        self.assertFalse(update_windows._within_directory("", root))
        self.assertTrue(update_windows._within_directory("\\\\?\\UNC\\server\\share\\child", "\\\\server\\share"))

    def test_32bit_host_does_not_read_native64_process_with_truncated_pointers(self):
        api = object.__new__(update_windows.WindowsAPI)
        api.pointer_size = 4
        api.kernel32 = Mock()
        api.kernel32.GetCurrentProcess.return_value = 111

        def is_wow64(handle, result):
            ctypes.cast(result, ctypes.POINTER(wintypes.BOOL)).contents.value = handle == 111
            return True

        api.kernel32.IsWow64Process.side_effect = is_wow64
        api._query_peb = Mock()
        with self.assertRaisesRegex(OSError, "32-bit helper"):
            api._current_directory(222)
        api._query_peb.assert_not_called()

    def test_exit_code_does_not_substitute_for_signaled_handle(self):
        api = object.__new__(update_windows.WindowsAPI)
        api.kernel32 = Mock()
        api.kernel32.WaitForSingleObject.return_value = update_windows.WAIT_TIMEOUT
        api.kernel32.GetExitCodeProcess.return_value = 0
        self.assertEqual(api.wait(123, 25), "timeout")
        api.kernel32.WaitForSingleObject.assert_called_once_with(123, 25)
        api.kernel32.GetExitCodeProcess.assert_not_called()

    def test_image_in_install_directory_blocks_with_external_cwd_and_deduplicates_names(self):
        api = object.__new__(update_windows.WindowsAPI)
        api.kernel32 = Mock()
        api.kernel32.OpenProcess.side_effect = lambda access, inherit, pid: pid
        api._processes = Mock(return_value=iter([
            (101, "Umeko.exe"), (102, "UMEKO.EXE"), (103, "neighbor.exe"),
        ]))
        images = {
            101: "C:\\UmekoTests\\issue171\\install\\Umeko.exe",
            102: "c:\\umekotests\\issue171\\INSTALL\\UMEKO.EXE",
            103: "C:\\UmekoTests\\issue171\\install-other\\neighbor.exe",
        }
        api._image_path = Mock(side_effect=images.__getitem__)
        api._current_directory = Mock(return_value="C:\\UmekoTests\\issue171\\outside")
        self.assertEqual(api.blockers("C:\\UmekoTests\\issue171\\install"), ["Umeko.exe"])
        # Matching executable paths suffice; only the nonmatching sibling needs cwd inspection.
        api._current_directory.assert_called_once_with(103)
        self.assertEqual(api.kernel32.CloseHandle.call_count, 3)

    @unittest.skipUnless(os.name == "nt", "Windows native error API")
    def test_missing_parent_is_finished_but_access_denial_fails_closed(self):
        api = object.__new__(update_windows.WindowsAPI)
        api.kernel32 = Mock()
        api.kernel32.OpenProcess.return_value = None
        with patch.object(ctypes, "get_last_error", return_value=87):
            self.assertIsNone(api.open_parent(123))
        with patch.object(ctypes, "get_last_error", return_value=5):
            with self.assertRaises(OSError):
                api.open_parent(123)

    def test_protocol_holds_original_handle_until_stdin_eof(self):
        api = Mock()
        api.open_parent.return_value = 123
        api.wait.return_value = "timeout"
        api.blockers.return_value = ["python.exe"]
        commands = '{"command":"wait","timeout":1}\n{"command":"blockers"}\n'
        output = io.StringIO()
        with patch.object(update_windows, "WindowsAPI", return_value=api), patch.object(sys, "stdin", io.StringIO(commands)), patch.object(sys, "stdout", output):
            self.assertEqual(update_windows.main(["321", "C:\\UmekoTests\\issue171\\install"]), 0)
        self.assertEqual([json.loads(line) for line in output.getvalue().splitlines()], [
            {"state": "ready"}, {"state": "timeout"}, {"state": "blockers", "names": ["python.exe"]},
        ])
        api.open_parent.assert_called_once_with(321)
        api.wait.assert_called_once_with(123, 1)
        api.close.assert_called_once_with(123)


@unittest.skipUnless(os.name == "nt", "Windows native process API")
class NativeProcessTests(unittest.TestCase):
    def setUp(self):
        root = Path("C:/UmekoTests/issue171")
        root.mkdir(parents=True, exist_ok=True)
        self.workspace = tempfile.TemporaryDirectory(prefix="native-helper-", dir=root)
        self.addCleanup(self.workspace.cleanup)
        self.api = update_windows.WindowsAPI()

    def _child(self, cwd):
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(120)"],
            cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.addCleanup(self._stop_child, child)
        return child

    @staticmethod
    def _stop_child(child):
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=10)

    def test_real_process_handle_waits_for_termination(self):
        child = self._child(self.workspace.name)
        handle = self.api.open_parent(child.pid)
        try:
            self.assertEqual(self.api.wait(handle, 25), "timeout")
            child.terminate()
            self.assertEqual(self.api.wait(handle, 10000), "exited")
        finally:
            self.api.close(handle)

    def test_real_cwd_occupies_install_directory_with_external_executable(self):
        # Python's executable lives outside the unique test install directory.
        self.assertFalse(update_windows._within_directory(sys.executable, self.workspace.name))
        child = self._child(self.workspace.name)
        # PEB parameters exist after interpreter startup; synchronize without input injection.
        query = self.api.kernel32.OpenProcess(update_windows.PROCESS_QUERY_LIMITED_INFORMATION | update_windows.PROCESS_VM_READ, False, child.pid)
        self.assertTrue(query)
        try:
            image = self.api._image_path(query)
            self.assertFalse(update_windows._within_directory(image, self.workspace.name))
            self.assertTrue(update_windows._within_directory(self.api._current_directory(query), self.workspace.name))
        finally:
            self.api.close(query)
        expected_name = Path(sys.executable).name.casefold()
        self.assertIn(expected_name, [name.casefold() for name in self.api.blockers(self.workspace.name)])
        child.terminate()
        child.wait(timeout=10)
        self.assertEqual(self.api.blockers(self.workspace.name), [])

    def test_real_wow64_current_directory_and_occupancy(self):
        executable = Path(os.environ.get("WINDIR", "C:/Windows")) / "SysWOW64" / "cmd.exe"
        if not executable.is_file():
            self.skipTest("SysWOW64/cmd.exe is unavailable; no real WOW64 evidence")
        if self.api.pointer_size != 8:
            self.skipTest("Real WOW64 PEB query requires a 64-bit host Python")
        child = subprocess.Popen(
            [str(executable), "/d", "/q"], cwd=self.workspace.name,
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.addCleanup(self._stop_child, child)
        self.addCleanup(child.stdin.close)
        handle = self.api.kernel32.OpenProcess(
            update_windows.PROCESS_QUERY_LIMITED_INFORMATION | update_windows.PROCESS_VM_READ,
            False, child.pid,
        )
        self.assertTrue(handle)
        try:
            # No stdin content is sent. An open pipe keeps hidden cmd waiting.
            self.assertIsNone(child.poll())
            self.assertNotEqual(self.api._query_peb(handle, wow64=True), 0,
                                "SysWOW64/cmd.exe did not expose a WOW64 PEB")
            self.assertTrue(update_windows._within_directory(
                self.api._current_directory(handle), self.workspace.name))
            self.assertIn("cmd.exe", [name.casefold() for name in self.api.blockers(self.workspace.name)])
        finally:
            self.api.close(handle)
            self._stop_child(child)
            child.stdin.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
