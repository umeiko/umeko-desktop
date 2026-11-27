"""Run one local shell in an unnamed Windows Job and report its cleanup."""

import base64
import ctypes
from ctypes import wintypes as w
import json
import msvcrt
import os
import queue
import subprocess
import sys
import threading
import time
from contextlib import ExitStack

from .update_windows import _open_inherited_stream


class BasicLimits(ctypes.Structure):
    _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                ("flags", w.DWORD), ("min_working_set", ctypes.c_size_t),
                ("max_working_set", ctypes.c_size_t), ("active_limit", w.DWORD),
                ("affinity", ctypes.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [("basic", BasicLimits), ("io_counters", ctypes.c_ulonglong * 6),
                ("memory", ctypes.c_size_t * 4)]


class ProcessInfo(ctypes.Structure):
    _fields_ = [("process", w.HANDLE), ("thread", w.HANDLE), ("pid", w.DWORD), ("tid", w.DWORD)]


class StartupInfoEx(ctypes.Structure):
    _fields_ = [("size", w.DWORD), ("reserved", w.LPWSTR), ("desktop", w.LPWSTR), ("title", w.LPWSTR),
                ("position_and_size", w.DWORD * 7), ("flags", w.DWORD), ("show_window", w.WORD),
                ("reserved_size", w.WORD), ("reserved_data", ctypes.c_void_p),
                ("stdin", w.HANDLE), ("stdout", w.HANDLE), ("stderr", w.HANDLE),
                ("attributes", ctypes.c_void_p)]


def api(name, result, *arguments):
    function = getattr(ctypes.WinDLL("kernel32", use_last_error=True), name)
    function.restype, function.argtypes = result, arguments
    return function


handle, pointer, dword, boolean = w.HANDLE, ctypes.c_void_p, w.DWORD, w.BOOL
create_job = api("CreateJobObjectW", handle, pointer, w.LPCWSTR)
set_job = api("SetInformationJobObject", boolean, handle, ctypes.c_int, pointer, dword)
query_job = api("QueryInformationJobObject", boolean, handle, ctypes.c_int, pointer, dword, pointer)
terminate_job = api("TerminateJobObject", boolean, handle, ctypes.c_uint)
close_handle = api("CloseHandle", boolean, handle)
init_attributes = api("InitializeProcThreadAttributeList", boolean, pointer, dword, dword, pointer)
update_attribute = api("UpdateProcThreadAttribute", boolean, pointer, dword, ctypes.c_size_t,
                       pointer, ctypes.c_size_t, pointer, pointer)
delete_attributes = api("DeleteProcThreadAttributeList", None, pointer)
create_process = api("CreateProcessW", boolean, w.LPCWSTR, w.LPWSTR, pointer, pointer, boolean,
                     dword, pointer, w.LPCWSTR, pointer, pointer)
wait_process = api("WaitForSingleObject", dword, handle, dword)
exit_code = api("GetExitCodeProcess", boolean, handle, pointer)


def expect(result):
    if not result:
        raise ctypes.WinError(ctypes.get_last_error())
    return result


def launch(request, job, stdin, stdout, stderr=None):
    stderr = stdout if stderr is None else stderr
    size = ctypes.c_size_t()
    init_attributes(None, 2, 0, ctypes.byref(size))
    attributes = ctypes.create_string_buffer(size.value)
    expect(init_attributes(attributes, 2, 0, ctypes.byref(size)))
    try:
        # Assign the job at creation, before Bash can start any descendants.
        jobs = (handle * 1)(job)
        inherited = tuple(dict.fromkeys((stdin, stdout, stderr)))
        handles = (handle * len(inherited))(*inherited)
        expect(update_attribute(attributes, 0, 0x0002000D, jobs, ctypes.sizeof(jobs), None, None))
        expect(update_attribute(attributes, 0, 0x00020002, handles, ctypes.sizeof(handles), None, None))
        startup = StartupInfoEx()
        startup.size = ctypes.sizeof(startup)
        startup.flags = 0x100  # STARTF_USESTDHANDLES
        startup.stdin, startup.stdout, startup.stderr = stdin, stdout, stderr
        startup.attributes = ctypes.addressof(attributes)
        info = ProcessInfo()
        args = ctypes.create_unicode_buffer(subprocess.list2cmdline(request["args"]))
        flags = subprocess.CREATE_NO_WINDOW | 0x00080000  # EXTENDED_STARTUPINFO_PRESENT
        expect(create_process(request["args"][0], args, None, None, True, flags,
                              None, request["cwd"], ctypes.byref(startup), ctypes.byref(info)))
        close_handle(info.thread)
        return info
    finally:
        delete_attributes(attributes)


def members(job):
    capacity = 16
    while True:
        class PidList(ctypes.Structure):
            _fields_ = [("assigned", dword), ("size", dword), ("pids", ctypes.c_size_t * capacity)]

        result = PidList()
        if query_job(job, 3, ctypes.byref(result), ctypes.sizeof(result), None):
            return list(result.pids[:result.size])
        if ctypes.get_last_error() != 234:  # ERROR_MORE_DATA
            raise ctypes.WinError(ctypes.get_last_error())
        capacity = max(result.assigned, capacity * 2)


def cleanup(job):
    remaining = members(job)
    if not remaining:
        return {"cleanup": "done", "remaining": []}
    if not terminate_job(job, 1):
        remaining = members(job)
        return {"cleanup": "failed" if remaining else "done", "remaining": remaining}
    deadline = time.monotonic() + 1.0
    while remaining and time.monotonic() < deadline:
        time.sleep(0.01)
        remaining = members(job)
    return {"cleanup": "timed_out" if remaining else "done", "remaining": remaining}


def supervise(request, job, cancelled, emit, stack):
    read_fd, write_fd = os.pipe()
    try:
        with open(os.devnull, "rb") as stdin:
            os.set_inheritable(stdin.fileno(), True)
            os.set_inheritable(write_fd, True)
            if cancelled.is_set():
                os.close(read_fd)
                return {"exitCode": 1, "cleanup": "done", "remaining": []}
            info = launch(request, job, msvcrt.get_osfhandle(stdin.fileno()), msvcrt.get_osfhandle(write_fd))
    except BaseException:
        os.close(read_fd)
        raise
    finally:
        os.close(write_fd)
    stack.callback(close_handle, info.process)
    emit({"pid": info.pid, "ppid": os.getpid()})
    output = queue.Queue(maxsize=16)

    def read_output():
        try:
            while data := os.read(read_fd, 8192):
                output.put(base64.b64encode(data).decode("ascii"))
        except OSError:
            pass
        finally:
            os.close(read_fd)
            output.put(None)

    threading.Thread(target=read_output, daemon=True).start()
    eof = False
    while not cancelled.is_set():
        if eof:
            wait = wait_process(info.process, 25)
            if wait == 0:
                break
            if wait == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
        else:
            try:
                data = output.get(timeout=0.025)
            except queue.Empty:
                continue
            eof = data is None
            if not eof:
                emit({"output": data})
    code = dword(1)
    if not cancelled.is_set():
        expect(exit_code(info.process, ctypes.byref(code)))
    return {"exitCode": code.value, **cleanup(job)}


def supervise_session(request, job, cancelled, incoming, emit, stack):
    write_fd = None
    if request.get("stdinOpen") is True:
        read_fd, write_fd = os.pipe()
        stack.callback(os.close, write_fd)
    else:
        # Codex rust-v0.172.0, codex-rs/core/src/spawn.rs uses a null
        # device for ordinary commands (including ripgrep with no path).
        read_fd = os.open(os.devnull, os.O_RDONLY | os.O_BINARY)
    try:
        with open(request["stdoutPath"], "wb") as stdout, open(request["stderrPath"], "wb") as stderr:
            for fd in (read_fd, stdout.fileno(), stderr.fileno()):
                os.set_inheritable(fd, True)
            if cancelled.is_set():
                return {"exitCode": 1, "cleanup": "done", "remaining": []}
            info = launch(request, job, msvcrt.get_osfhandle(read_fd),
                          msvcrt.get_osfhandle(stdout.fileno()), msvcrt.get_osfhandle(stderr.fileno()))
    finally:
        os.close(read_fd)
    stack.callback(close_handle, info.process)
    emit({"pid": info.pid, "ppid": os.getpid()})

    def write_input():
        while not cancelled.is_set():
            try:
                message = incoming.get(timeout=0.1)
            except queue.Empty:
                continue
            reply = {"writeId": message["writeId"]}
            try:
                pending = memoryview(message["input"].encode("utf-8"))
                while pending:
                    pending = pending[os.write(write_fd, pending):]
            except OSError:
                reply["error"] = "Standard input is closed for this command."
            emit(reply)

    writer = None
    if write_fd is not None:
        writer = threading.Thread(target=write_input, daemon=True)
        writer.start()
    code = dword(1)
    while not cancelled.is_set():
        wait = wait_process(info.process, 25)
        if wait == 0:
            expect(exit_code(info.process, ctypes.byref(code)))
            break
        if wait == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
    cancelled.set()
    result = cleanup(job)
    if writer is not None:
        writer.join(timeout=0.15)
    return {"exitCode": code.value, **result}


def main():
    # Windowed PyInstaller executables have no Python standard streams even
    # when their parent redirected the Win32 standard handles.
    control = sys.stdin or _open_inherited_stream(-10, "r")
    if sys.stdin is not None:
        # Node writes UTF-8 JSON; source runs must not use the system code page.
        control.reconfigure(encoding="utf-8")
    replies = sys.stdout or _open_inherited_stream(-11, "w")

    reply_lock = threading.Lock()

    def emit(value):
        with reply_lock:
            print(json.dumps(value, ensure_ascii=True), file=replies, flush=True)

    try:
        request = json.loads(control.readline())
        cancelled = threading.Event()
        incoming = queue.Queue(maxsize=8)

        def listen():
            try:
                for line in control:
                    if line.strip() == "stop":
                        break
                    message = json.loads(line)
                    if request.get("stdinOpen") is not True:
                        emit({"writeId": message["writeId"], "error": "Standard input is closed for this command."})
                        continue
                    try:
                        incoming.put_nowait(message)
                    except queue.Full:
                        emit({"writeId": message["writeId"], "error": "Command input queue is full"})
            finally:
                cancelled.set()

        threading.Thread(target=listen, daemon=True).start()
        with ExitStack() as stack:
            job = expect(create_job(None, None))
            stack.callback(close_handle, job)
            limits = ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            expect(set_job(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
            try:
                if "stdoutPath" in request:
                    result = supervise_session(request, job, cancelled, incoming, emit, stack)
                else:
                    result = supervise(request, job, cancelled, emit, stack)
            except OSError as error:
                result = {"exitCode": 1, "error": getattr(error, "winerror", None), **cleanup(job)}
        emit(result)
        return 0
    except (OSError, ValueError, KeyError):
        # No command, paths, or output are part of cleanup diagnostics.
        emit({"exitCode": 1, "cleanup": "failed", "remaining": None})
        return 1
