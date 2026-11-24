"""Proxy only acceptance-owned SSH children and inject a scoped network outage.

No global process lookup, firewall change, SSH daemon control or proxy access.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def record(control, event, **fields):
    """Append one bounded lifecycle record, also when wrappers run concurrently."""
    row = {'event': event, 'at': time.monotonic(), 'unixTime': time.time(),
           'ownerPid': os.getpid(), **fields}
    descriptor = os.open(control / 'lifecycle.jsonl', os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(descriptor, (json.dumps(row) + '\n').encode('utf-8'))
    finally:
        os.close(descriptor)


def own_windows_client(process):
    """Close the exact SSH child if the app terminates the Python wrapper."""
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                    ('flags', wintypes.DWORD), ('min_working_set', ctypes.c_size_t),
                    ('max_working_set', ctypes.c_size_t), ('max_processes', wintypes.DWORD),
                    ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
                    ('scheduling_class', wintypes.DWORD)]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [('basic', BasicLimits), ('io_counters', ctypes.c_ulonglong * 6),
                    ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                    ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = ExtendedLimits()
    # Kill on close and let any configured ProxyCommand run outside this job.
    limits.basic.flags = 0x2000 | 0x1000
    if not (kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
            and kernel.AssignProcessToJobObject(job, int(process._handle))):
        error = ctypes.WinError(ctypes.get_last_error())
        kernel.CloseHandle(job)
        raise error
    return lambda: kernel.CloseHandle(job)


def main():
    control = Path(os.environ['UMEKO_SSH_TEST_CONTROL']).resolve()
    control.mkdir(parents=True, exist_ok=True)
    if (control / 'blocked').exists():
        # Scope the artificial outage to this test's next client launch. Never
        # manufacture SSH replies or touch a firewall, daemon or shared proxy.
        # Once released, the exact production-selected client really connects.
        record(control, 'injected-block-wait')
        while (control / 'blocked').exists():
            time.sleep(.1)
        record(control, 'injected-block-released')
    ssh = os.environ.get('UMEKO_REAL_SSH') or shutil.which('ssh')
    if not ssh:
        raise RuntimeError('OpenSSH client is missing')
    arguments = sys.argv[1:]
    process = subprocess.Popen([ssh, *arguments], stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    close_job = None
    try:
        if os.name == 'nt' and process.poll() is None:
            close_job = own_windows_client(process)
        # The transport's persistent client forwards the websocket port with -L.
        tunnel = any(arg == '-L' or arg.startswith('-L') for arg in arguments)
        with (control / 'clients.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps({'pid': process.pid, 'ownerPid': os.getpid(), 'tunnel': tunnel,
                                     'executable': str(Path(ssh).resolve()), 'argv': arguments}) + '\n')
        record(control, 'client-start', pid=process.pid, tunnel=tunnel,
               executable=str(Path(ssh).resolve()))
        status = process.wait()
        record(control, 'client-exit', pid=process.pid, tunnel=tunnel, exitCode=status)
        return status
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        if close_job:
            close_job()


if __name__ == '__main__':
    sys.exit(main())
