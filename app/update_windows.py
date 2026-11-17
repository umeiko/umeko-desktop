"""Windows updater process wait and installation-directory occupancy helper.

This module deliberately uses only the standard library, so the packaged Python
runtime can invoke it before Qt starts. The parent process handle is opened once
at startup and held until the JSON-lines session ends.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import ntpath
import os
import struct
import sys


SYNCHRONIZE = 0x00100000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
WAIT_FAILED = 0xFFFFFFFF
ERROR_INVALID_PARAMETER = 87
ERROR_NO_MORE_FILES = 18
TH32CS_SNAPPROCESS = 0x00000002


def _normalized_path(path: str) -> str:
    path = path.replace("/", "\\")
    if path.lower().startswith("\\\\?\\unc\\"):
        path = "\\\\" + path[8:]
    elif path.startswith("\\\\?\\") or path.startswith("\\??\\"):
        path = path[4:]
    return ntpath.normcase(ntpath.normpath(path))


def _within_directory(path: str, directory: str) -> bool:
    if not path:
        return False
    candidate = _normalized_path(path)
    root = _normalized_path(directory)
    return candidate == root or candidate.startswith(root.rstrip("\\") + "\\")


def _read_current_directory(read_memory, peb_address: int, pointer_size: int) -> str:
    """Read only the documented-for-this-helper PEB/parameters layout."""
    pointer_format = "<Q" if pointer_size == 8 else "<I"
    params_offset, cwd_offset = (0x20, 0x38) if pointer_size == 8 else (0x10, 0x24)
    params = struct.unpack(pointer_format, read_memory(peb_address + params_offset, pointer_size))[0]
    if not params:
        return ""
    descriptor = read_memory(params + cwd_offset, 16 if pointer_size == 8 else 8)
    length, maximum_length = struct.unpack_from("<HH", descriptor)
    buffer = struct.unpack_from(pointer_format, descriptor, 8 if pointer_size == 8 else 4)[0]
    if not length:
        return ""
    if length % 2 or length > maximum_length or not buffer:
        raise OSError("Invalid process current-directory descriptor")
    return read_memory(buffer, length).decode("utf-16-le")


class _ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
    ]


class _ProcessBasicInformation(ctypes.Structure):
    _fields_ = [
        ("Reserved1", ctypes.c_void_p), ("PebBaseAddress", ctypes.c_void_p),
        ("Reserved2", ctypes.c_void_p * 2), ("UniqueProcessId", ctypes.c_size_t),
        ("Reserved3", ctypes.c_void_p),
    ]


class WindowsAPI:
    def __init__(self):
        if os.name != "nt":
            raise OSError("Windows update helper requires Windows")
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.ntdll = ctypes.WinDLL("ntdll")
        self.pointer_size = ctypes.sizeof(ctypes.c_void_p)
        self._bind("OpenProcess", [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE)
        self._bind("CloseHandle", [wintypes.HANDLE], wintypes.BOOL)
        self._bind("WaitForSingleObject", [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD)
        self._bind("CreateToolhelp32Snapshot", [wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE)
        self._bind("Process32FirstW", [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)], wintypes.BOOL)
        self._bind("Process32NextW", [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)], wintypes.BOOL)
        self._bind("QueryFullProcessImageNameW", [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL)
        self._bind("ReadProcessMemory", [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)], wintypes.BOOL)
        self._bind("IsWow64Process", [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)], wintypes.BOOL)
        self._bind("GetCurrentProcess", [], wintypes.HANDLE)
        self.ntdll.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
        self.ntdll.NtQueryInformationProcess.restype = wintypes.LONG

    def _bind(self, name, arguments, result):
        function = getattr(self.kernel32, name)
        function.argtypes = arguments
        function.restype = result

    def open_parent(self, pid: int):
        handle = self.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if handle:
            return handle
        error = ctypes.get_last_error()
        if error == ERROR_INVALID_PARAMETER:
            return None
        raise ctypes.WinError(error)

    def close(self, handle):
        if handle:
            self.kernel32.CloseHandle(handle)

    def wait(self, handle, timeout: int) -> str:
        if handle is None:
            return "exited"
        result = self.kernel32.WaitForSingleObject(handle, timeout)
        if result == WAIT_OBJECT_0:
            return "exited"
        if result == WAIT_TIMEOUT:
            return "timeout"
        if result == WAIT_FAILED:
            raise ctypes.WinError(ctypes.get_last_error())
        raise OSError(f"Unexpected process wait result: {result}")

    def _processes(self):
        snapshot = self.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = _ProcessEntry()
            entry.dwSize = ctypes.sizeof(entry)
            available = self.kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while available:
                yield entry.th32ProcessID, str(entry.szExeFile)
                available = self.kernel32.Process32NextW(snapshot, ctypes.byref(entry))
            error = ctypes.get_last_error()
            if error != ERROR_NO_MORE_FILES:
                raise ctypes.WinError(error)
        finally:
            self.close(snapshot)

    def _image_path(self, handle) -> str:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if not self.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        return buffer.value

    def _read_memory(self, handle, address: int, size: int) -> bytes:
        buffer = ctypes.create_string_buffer(size)
        copied = ctypes.c_size_t()
        if not self.kernel32.ReadProcessMemory(handle, address, buffer, size, ctypes.byref(copied)) or copied.value != size:
            raise ctypes.WinError(ctypes.get_last_error())
        return buffer.raw

    def _query_peb(self, handle, wow64: bool = False) -> int:
        result = ctypes.c_size_t() if wow64 else _ProcessBasicInformation()
        status = self.ntdll.NtQueryInformationProcess(handle, 26 if wow64 else 0, ctypes.byref(result), ctypes.sizeof(result), None)
        if status < 0:
            raise OSError(f"NtQueryInformationProcess failed: {status:#x}")
        return result.value if wow64 else result.PebBaseAddress

    def _current_directory(self, handle) -> str:
        if self.pointer_size == 4:
            # A 32-bit helper cannot read a native 64-bit PEB with pointer-sized
            # APIs. Preserve its image result and skip this inaccessible cwd.
            host_wow64, target_wow64 = wintypes.BOOL(), wintypes.BOOL()
            if not self.kernel32.IsWow64Process(self.kernel32.GetCurrentProcess(), ctypes.byref(host_wow64)):
                raise ctypes.WinError(ctypes.get_last_error())
            if host_wow64.value:
                if not self.kernel32.IsWow64Process(handle, ctypes.byref(target_wow64)):
                    raise ctypes.WinError(ctypes.get_last_error())
                if not target_wow64.value:
                    raise OSError("A 32-bit helper cannot read a native 64-bit process current directory")
        # A 64-bit host queries ProcessWow64Information to distinguish PEB32.
        wow64_peb = self._query_peb(handle, wow64=True) if self.pointer_size == 8 else 0
        pointer_size = 4 if wow64_peb else self.pointer_size
        peb = wow64_peb or self._query_peb(handle)
        if not peb:
            return ""
        return _read_current_directory(lambda address, size: self._read_memory(handle, address, size), peb, pointer_size)

    def blockers(self, install_directory: str) -> list[str]:
        names = {}
        for pid, process_name in self._processes():
            handle = self.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, False, pid)
            if not handle:
                # Image queries often remain permitted when VM_READ is denied.
                handle = self.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                continue
            try:
                occupied = False
                try:
                    image = self._image_path(handle)
                    occupied = _within_directory(image, install_directory)
                    process_name = ntpath.basename(image) or process_name
                except OSError:
                    pass
                if not occupied:
                    try:
                        occupied = _within_directory(self._current_directory(handle), install_directory)
                    except (OSError, UnicodeError, ValueError, struct.error):
                        pass
                if occupied:
                    name = ntpath.basename(process_name)
                    if name:
                        names.setdefault(name.casefold(), name)
            finally:
                self.close(handle)
        return sorted(names.values(), key=str.casefold)


def _emit(value):
    print(json.dumps(value, ensure_ascii=True), flush=True)


def main(argv=None) -> int:
    api = None
    parent_handle = None
    try:
        arguments = sys.argv[1:] if argv is None else argv
        if len(arguments) != 2:
            raise ValueError("Expected parent PID and installation directory")
        pid = int(arguments[0])
        if pid <= 0 or pid > 0xFFFFFFFF:
            raise ValueError("Invalid parent PID")
        install_directory = arguments[1]
        if not ntpath.isabs(install_directory):
            raise ValueError("Installation directory must be absolute")
        api = WindowsAPI()
        parent_handle = api.open_parent(pid)
        _emit({"state": "ready"})
        for line in sys.stdin:
            command = json.loads(line)
            if command.get("command") == "wait":
                timeout = command.get("timeout", 120000)
                if isinstance(timeout, bool) or not isinstance(timeout, int) or not 0 <= timeout < 0xFFFFFFFF:
                    raise ValueError("Invalid wait timeout")
                _emit({"state": api.wait(parent_handle, timeout)})
            elif command.get("command") == "blockers":
                _emit({"state": "blockers", "names": api.blockers(install_directory)})
            else:
                raise ValueError("Unknown Windows helper command")
        return 0
    except Exception as error:
        _emit({"state": "error", "message": str(error)})
        return 1
    finally:
        if api is not None:
            api.close(parent_handle)


if __name__ == "__main__":
    raise SystemExit(main())
