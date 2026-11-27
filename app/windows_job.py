"""Windows Job Objects for the desktop and its supervised commands."""

import ctypes
import subprocess
from ctypes import wintypes as w


class BasicLimits(ctypes.Structure):
    _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                ("flags", w.DWORD), ("min_working_set", ctypes.c_size_t),
                ("max_working_set", ctypes.c_size_t), ("active_limit", w.DWORD),
                ("affinity", ctypes.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [("basic", BasicLimits), ("io_counters", ctypes.c_ulonglong * 6),
                ("memory", ctypes.c_size_t * 4)]


def api(name, result, *arguments):
    function = getattr(ctypes.WinDLL("kernel32", use_last_error=True), name)
    function.restype, function.argtypes = result, arguments
    return function


handle, pointer, dword, boolean = w.HANDLE, ctypes.c_void_p, w.DWORD, w.BOOL
create_job = api("CreateJobObjectW", handle, pointer, w.LPCWSTR)
set_job = api("SetInformationJobObject", boolean, handle, ctypes.c_int, pointer, dword)
close_handle = api("CloseHandle", boolean, handle)
current_process = api("GetCurrentProcess", handle)
assign_job = api("AssignProcessToJobObject", boolean, handle, handle)

JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x0800
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_desktop_job = None


def expect(result):
    if not result:
        raise ctypes.WinError(ctypes.get_last_error())
    return result


def create_kill_on_close_job(*, allow_breakaway=False):
    job = expect(create_job(None, None))
    limits = ExtendedLimits()
    limits.basic.flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if allow_breakaway:
        limits.basic.flags |= JOB_OBJECT_LIMIT_BREAKAWAY_OK
    try:
        expect(set_job(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                       ctypes.byref(limits), ctypes.sizeof(limits)))
    except OSError:
        close_handle(job)
        raise
    return job


def contain_desktop_processes():
    """Assign the desktop before it launches children so they inherit the job."""
    global _desktop_job
    if _desktop_job is not None:
        return
    job = create_kill_on_close_job(allow_breakaway=True)
    try:
        expect(assign_job(job, current_process()))
    except OSError:
        close_handle(job)
        raise
    # Windows closes this non-inheritable handle when the desktop exits.
    _desktop_job = job


def handoff_creation_flag():
    """Let an installer or replacement desktop outlive this desktop."""
    return subprocess.CREATE_BREAKAWAY_FROM_JOB if _desktop_job is not None else 0
