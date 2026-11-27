"""Windows Job Objects for managed desktop children and supervised commands."""
from __future__ import annotations

import ctypes
import logging
import subprocess
import sys
import threading
import weakref
from ctypes import wintypes as w

_log = logging.getLogger(__name__)

JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x0800
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100
ERROR_INVALID_PARAMETER = 87

_job_lock = threading.Lock()
_managed_job = None
_managed_job_unavailable = False

if sys.platform == "win32":
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
    assign_job = api("AssignProcessToJobObject", boolean, handle, handle)
    open_process = api("OpenProcess", handle, dword, boolean, dword)

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


def _get_managed_job():
    """Return the non-inheritable Job owned by this host for managed children."""
    global _managed_job, _managed_job_unavailable
    if sys.platform != "win32":
        return None
    with _job_lock:
        if _managed_job is not None:
            return _managed_job
        if _managed_job_unavailable:
            return None
        try:
            # Omit SILENT_BREAKAWAY_OK so descendants of managed children
            # (plugin commands, Pi search tools, terminal shells) inherit the
            # Job. The desktop process itself is never assigned to it, so
            # user-opened external programs and handoffs stay independent.
            job = create_kill_on_close_job()
        except OSError as error:
            _managed_job_unavailable = True
            _log.warning("Windows managed-child job unavailable; falling back to standard cleanup: %s", error)
            return None
        _managed_job = job
        return job


def ensure_managed_job():
    """Initialize the managed-child Job without blocking startup on failure."""
    return _get_managed_job() is not None


def assign_process_handle(process_handle):
    """Explicitly assign a managed child process handle to the desktop Job."""
    if sys.platform != "win32" or not process_handle:
        return False
    job = _get_managed_job()
    if job is None:
        return False
    try:
        if assign_job(job, process_handle):
            return True
        error = ctypes.get_last_error()
        _log.warning("Could not assign managed child process to Windows job (winerror=%s)", error)
        return False
    except OSError as error:
        _log.warning("Could not assign managed child process to Windows job: %s", error)
        return False


def assign_process_id(pid):
    """Explicitly assign a managed child PID to the desktop Job."""
    if sys.platform != "win32" or not isinstance(pid, int) or pid <= 0:
        return False
    if _get_managed_job() is None:
        return False
    process_handle = open_process(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
    if not process_handle:
        error = ctypes.get_last_error()
        if error != ERROR_INVALID_PARAMETER:
            _log.warning("Could not open managed child PID %s for Windows job (winerror=%s)", pid, error)
        return False
    try:
        return assign_process_handle(process_handle)
    finally:
        close_handle(process_handle)


def assign_subprocess(process):
    """Assign a managed subprocess.Popen instance to the desktop Job."""
    if sys.platform != "win32" or process is None:
        return False
    handle_value = getattr(process, "_handle", None)
    if isinstance(handle_value, int) and handle_value:
        return assign_process_handle(int(handle_value))
    return False


def manage_qprocess(process):
    """Assign a managed QProcess child as soon as Qt starts it.

    PySide6 6.10.2 does not expose QProcess.setCreateProcessArgumentsModifier,
    so assignment runs synchronously in the started signal emitted right after
    CreateProcessW, before initialization messages are written to the worker.
    """
    if sys.platform == "win32" and process is not None:
        ref = weakref.ref(process)

        def on_started():
            proc = ref()
            if proc is not None:
                assign_process_id(proc.processId())

        process.started.connect(on_started)
        pid = process.processId()
        if isinstance(pid, int) and pid > 0:
            assign_process_id(pid)
    return process


def run_managed(*popenargs, input=None, capture_output=False, timeout=None, check=False, **kwargs):
    """Drop-in subprocess.run equivalent that assigns Windows children to the Job."""
    if sys.platform != "win32":
        return subprocess.run(
            *popenargs, input=input, capture_output=capture_output,
            timeout=timeout, check=check, **kwargs,
        )
    if input is not None:
        if kwargs.get("stdin") is not None:
            raise ValueError("stdin and input arguments may not both be used.")
        kwargs["stdin"] = subprocess.PIPE
    if capture_output:
        if kwargs.get("stdout") is not None or kwargs.get("stderr") is not None:
            raise ValueError("stdout and stderr arguments may not be used with capture_output.")
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    with subprocess.Popen(*popenargs, **kwargs) as process:
        assign_subprocess(process)
        try:
            stdout, stderr = process.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            exc.output, exc.stderr = process.communicate()
            raise
        except BaseException:
            process.kill()
            raise
        retcode = process.poll()
        if check and retcode:
            raise subprocess.CalledProcessError(retcode, process.args, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(process.args, retcode, stdout, stderr)


def detach_subprocess(process):
    """Release an intentionally detached Popen without emitting ResourceWarning."""
    popen_type = subprocess.Popen
    if not isinstance(popen_type, type) or not isinstance(process, popen_type):
        return
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        handle_value = getattr(process, "_handle", None)
        if handle_value is not None and hasattr(handle_value, "Close"):
            handle_value.Close()
    # Mark the wrapper non-owning so GC does not warn or retain it in _active.
    process._child_created = False
