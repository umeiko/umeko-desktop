"""Windows managed-child Job Object regressions using real product launch paths."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SYNCHRONIZE_AND_TERMINATE = 0x00100001


def _write_blocking_plugin(profile: Path, plugin_id: str, marker: Path, *, lifecycle: str = "session") -> None:
    """Create a valid desktop plugin whose worker blocks on close/call and spawns a grandchild."""
    version = "1.0.0"
    pkg_dir = profile / "desktop-plugins" / "packages" / plugin_id / version
    scripts_dir = pkg_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "kind": "umeko-plugin",
        "apiVersion": 1,
        "id": plugin_id,
        "version": version,
        "name": plugin_id,
        "summary": "Lifetime test",
        "description": "Disposable lifetime test plugin",
        "lifecycle": lifecycle,
        "entrypoint": "scripts/plugin.py:create_plugin",
        "permissions": [],
        "agent": {"document": "AGENT.md", "methods": {}},
    }
    if lifecycle == "session":
        manifest["page"] = "index.html"
        (pkg_dir / "index.html").write_text("<!doctype html><title>probe</title>", encoding="utf-8")
    (pkg_dir / "README.md").write_text("# Lifetime probe\n", encoding="utf-8")
    (pkg_dir / "AGENT.md").write_text("# Lifetime probe agent doc\n", encoding="utf-8")
    (pkg_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (pkg_dir / "config.json").write_text("{}", encoding="utf-8")
    (pkg_dir / "config.schema.json").write_text(
        json.dumps({"type": "object", "properties": {}, "additionalProperties": False}),
        encoding="utf-8",
    )
    plugin_code = f"""import json, os, subprocess, sys, time
from pathlib import Path
from umeko_plugin_sdk import Plugin

MARKER = Path({str(marker)!r})

class ProbePlugin(Plugin):
    def __init__(self, context):
        super().__init__(context)
        self.grandchild = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        payload = {{"worker_pid": os.getpid(), "grandchild_pid": self.grandchild.pid}}
        tmp = MARKER.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(MARKER)

    def handle(self, method, arguments):
        if method == "block":
            # Block the worker main thread so stdin EOF alone cannot make it exit.
            time.sleep(60)
            return {{"done": True}}
        return {{"pid": os.getpid(), "grandchild_pid": self.grandchild.pid}}

    def close(self):
        # Block EOF shutdown so only OS Job termination can reap this worker quickly.
        time.sleep(60)

def create_plugin(context):
    return ProbePlugin(context)
"""
    (scripts_dir / "plugin.py").write_text(plugin_code, encoding="utf-8")
    registry = profile / "desktop-plugins" / "settings.json"
    data = json.loads(registry.read_text(encoding="utf-8")) if registry.exists() else {}
    data.setdefault("installed", {})[plugin_id] = manifest
    data.setdefault("enabled", {})[plugin_id] = True
    registry.write_text(json.dumps(data), encoding="utf-8")


def _write_sleeper_cmd(directory: Path, name: str, pid_file: Path) -> Path:
    """Create a .cmd wrapper that spawns a sleeping Python process and writes its PID."""
    script = directory / (name + ".py")
    script.write_text(
        "import os, time\n"
        "from pathlib import Path\n"
        f"target = Path({str(pid_file)!r})\n"
        "tmp = target.with_suffix('.tmp')\n"
        "tmp.write_text(str(os.getpid()), encoding='ascii')\n"
        "tmp.replace(target)\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    wrapper = directory / (name + ".cmd")
    wrapper.write_text(f'@echo off\r\n"{sys.executable}" "{script}"\r\n', encoding="ascii")
    return wrapper


def _wait_json(path: Path, timeout: float = 20.0, process: subprocess.Popen | None = None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        if process is not None and process.poll() is not None:
            break
        time.sleep(0.05)
    return None


def _wait_int(path: Path, timeout: float = 15.0) -> int | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            try:
                text = path.read_text(encoding="ascii").strip()
                if text:
                    return int(text)
            except (OSError, ValueError):
                pass
        time.sleep(0.05)
    return None


def _open_handles(pids):
    import _winapi
    handles = {}
    for key, pid in pids.items():
        if pid:
            handles[key] = _winapi.OpenProcess(SYNCHRONIZE_AND_TERMINATE, False, int(pid))
    return handles


def _cleanup_handles(handles):
    import _winapi
    for handle in handles.values():
        if not handle:
            continue
        try:
            if _winapi.WaitForSingleObject(handle, 0) == _winapi.WAIT_TIMEOUT:
                _winapi.TerminateProcess(handle, 1)
        except OSError:
            pass
        finally:
            try:
                _winapi.CloseHandle(handle)
            except OSError:
                pass


class _StartupInfoW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _ProcessInfo(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


def _spawn_inside_restricted_job(command, *, cwd, env, stdout_path: Path, stderr_path: Path):
    """Spawn a child suspended inside an outer Windows Job WITHOUT BREAKAWAY_OK.

    Uses sys._base_executable when running inside a Windows Python venv so the
    venv redirector stub (venvlauncher.exe) does not insert an intermediate
    SILENT_BREAKAWAY_OK (0x3000) Job that masks the restricted outer Job.
    """
    import msvcrt
    from app.windows_job import (
        ExtendedLimits,
        JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        assign_job,
        close_handle,
        create_job,
        expect,
        set_job,
    )

    CREATE_SUSPENDED = 0x00000004
    CREATE_UNICODE_ENVIRONMENT = 0x00000400
    STARTF_USESTDHANDLES = 0x00000100

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateProcessW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.POINTER(_StartupInfoW),
        ctypes.POINTER(_ProcessInfo),
    )
    kernel32.CreateProcessW.restype = wintypes.BOOL
    kernel32.ResumeThread.argtypes = (wintypes.HANDLE,)
    kernel32.ResumeThread.restype = wintypes.DWORD

    launch_cmd = list(command)
    launch_env = dict(env)
    base_exe = getattr(sys, "_base_executable", "")
    if launch_cmd and launch_cmd[0] == sys.executable and base_exe and Path(base_exe).is_file():
        if Path(base_exe).resolve() != Path(sys.executable).resolve():
            launch_cmd[0] = base_exe
            existing_pp = [p for p in launch_env.get("PYTHONPATH", "").split(os.pathsep) if p]
            extra_pp = [p for p in sys.path if p and Path(p).exists() and p not in existing_pp]
            launch_env["PYTHONPATH"] = os.pathsep.join([*existing_pp, *extra_pp])

    outer_job = expect(create_job(None, None))
    process_handle = None
    try:
        # Explicitly NO JOB_OBJECT_LIMIT_BREAKAWAY_OK (0x0800) and NO SILENT_BREAKAWAY_OK (0x1000).
        limits = ExtendedLimits()
        limits.basic.flags = 0
        expect(set_job(outer_job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                       ctypes.byref(limits), ctypes.sizeof(limits)))

        with open(os.devnull, "rb") as stdin_f, stdout_path.open("wb") as out_f, stderr_path.open("wb") as err_f:
            for fd in (stdin_f.fileno(), out_f.fileno(), err_f.fileno()):
                os.set_inheritable(fd, True)
            startup = _StartupInfoW()
            startup.cb = ctypes.sizeof(startup)
            startup.dwFlags = STARTF_USESTDHANDLES
            startup.hStdInput = msvcrt.get_osfhandle(stdin_f.fileno())
            startup.hStdOutput = msvcrt.get_osfhandle(out_f.fileno())
            startup.hStdError = msvcrt.get_osfhandle(err_f.fileno())
            proc_info = _ProcessInfo()
            cmdline = ctypes.create_unicode_buffer(subprocess.list2cmdline(launch_cmd))
            env_block = ctypes.create_unicode_buffer(
                "\0".join(f"{k}={v}" for k, v in launch_env.items()) + "\0\0"
            )
            flags = subprocess.CREATE_NO_WINDOW | CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT
            expect(kernel32.CreateProcessW(
                None, cmdline, None, None, True, flags, env_block, str(cwd),
                ctypes.byref(startup), ctypes.byref(proc_info),
            ))
            process_handle = proc_info.hProcess
            try:
                expect(assign_job(outer_job, process_handle))
                if kernel32.ResumeThread(proc_info.hThread) == 0xFFFFFFFF:
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                close_handle(proc_info.hThread)
        return outer_job, process_handle, proc_info.dwProcessId
    except BaseException:
        if process_handle:
            try:
                import _winapi
                _winapi.TerminateProcess(process_handle, 1)
            except OSError:
                pass
            close_handle(process_handle)
        close_handle(outer_job)
        raise


HOST_PLUGINS_AND_APPS = r"""
import ctypes, json, os, subprocess, sys, time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QCoreApplication, QObject, QTimer, Signal
from app.desktop_plugins import DesktopPlugins
from app.windows_job import ensure_managed_job

mode = sys.argv[1]
work = Path(sys.argv[2])
profile = work / "profile"
workspace = work / "workspace"
workspace.mkdir(parents=True, exist_ok=True)
ready_file = work / "host-ready.json"
plugin_marker = work / "plugin-marker.json"
negative_control_winerror = None

if mode == "restricted":
    # Negative control: prove this process is directly constrained by an outer
    # Job that rejects CREATE_BREAKAWAY_FROM_JOB with ERROR_ACCESS_DENIED (5).
    try:
        bad_proc = subprocess.Popen(
            [sys.executable, "-c", "pass"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_BREAKAWAY_FROM_JOB,
        )
        bad_proc.wait(timeout=5)
        raise AssertionError("CREATE_BREAKAWAY_FROM_JOB unexpectedly succeeded inside restricted outer Job")
    except PermissionError as exc:
        assert getattr(exc, "winerror", None) == 5, f"Unexpected breakaway error: {exc!r}"
        negative_control_winerror = exc.winerror

assert ensure_managed_job(), "ensure_managed_job() unexpectedly returned False"

app = QCoreApplication([])

class Pool(QObject):
    event = Signal(object, object)
    def __init__(self, record):
        super().__init__()
        self.records = {record.key: record}
    def write(self, record, event):
        pass
    def find(self, identifier):
        return next((row for row in self.records.values() if row.id == identifier), None)

class Host(QObject):
    viewChanged = Signal()
    chatChanged = Signal()
    toast = Signal(str)
    documentRequested = Signal(str, str, str)
    widgetDocumentRequested = Signal(str, str, str, str)
    editorText = Signal(str)
    def __init__(self):
        super().__init__()
        self.root = Path.cwd()
        self.store = SimpleNamespace(directory=profile, data={"selectedModel": "fixture"})
        self.characterStyle = {"id": "yanami"}
        self._view = SimpleNamespace(
            key="token-job", id="session-job", workspace=str(workspace), title="JobTest",
            busy=False, global_agent="", failed=False, cancelled=False, messages=[],
        )
        self._pool = Pool(self._view)

host = Host()
manager = DesktopPlugins(host)
manager.setSessionEnabled("job-probe", True)
assert manager.openPage("job-probe"), "openPage(job-probe) failed"

deadline = time.monotonic() + 20
while time.monotonic() < deadline and not manager.workers.get("job-probe", {}).get("ready"):
    app.processEvents()
    time.sleep(0.02)
assert manager.workers.get("job-probe", {}).get("ready"), "job-probe worker never became ready"

# Invoke the blocking call so stdin EOF cannot cause worker.py to exit on its own.
manager.call_for("job-probe", "block", "{}")
for _ in range(10):
    app.processEvents()
    time.sleep(0.02)

info = json.loads(plugin_marker.read_text(encoding="utf-8"))
info["host_pid"] = os.getpid()
if negative_control_winerror is not None:
    info["negative_control_winerror"] = negative_control_winerror

if mode == "external":
    from app.pi_terminal import launch_terminal
    term_pid_file = work / "term.pid"
    term_proc = launch_terminal([
        sys.executable, "-c",
        f"import os, time; from pathlib import Path; Path({str(term_pid_file)!r}).write_text(str(os.getpid()), encoding='ascii'); time.sleep(60)",
    ])
    info["terminal_pid"] = term_proc.pid

    shell_pid_file = work / "shell.pid"
    shell_script = work / "shell_open.py"
    shell_script.write_text(
        "import os, time\nfrom pathlib import Path\n"
        f"p = Path({str(shell_pid_file)!r}); t = p.with_suffix('.tmp'); t.write_text(str(os.getpid()), encoding='ascii'); t.replace(p)\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ret = shell32.ShellExecuteW(None, "open", sys.executable, f'"{shell_script}"', str(work), 0)
    assert ret > 32, f"ShellExecuteW failed: {ret}"
    end = time.monotonic() + 10
    while not shell_pid_file.is_file() and time.monotonic() < end:
        time.sleep(0.05)
    assert shell_pid_file.is_file(), "ShellExecuteW external process did not start"
    info["shell_pid"] = int(shell_pid_file.read_text(encoding="ascii").strip())

    # Unmanaged Popen matching app/group_chat.py open_attachment()
    browser_proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    info["browser_pid"] = browser_proc.pid

elif mode in ("handoff", "restricted"):
    from app.update import AppUpdater
    from app import preview_launch
    from app.preview_channel import PreviewChannel

    installer_pid_file = work / "installer.pid"
    installer_cmd = Path(sys.argv[3])
    job_file = work / "update-job.json"
    job_file.write_text(json.dumps({"helperExe": str(installer_cmd)}), encoding="utf-8")
    updater = AppUpdater(host)
    updater.job_file = job_file
    updater.launch_installer()
    assert updater.state != "error", f"AppUpdater.launch_installer failed: {getattr(updater, '_error', '')}"

    end = time.monotonic() + 15
    while not installer_pid_file.is_file() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.05)
    assert installer_pid_file.is_file(), "Installer helper did not start"
    info["installer_pid"] = int(installer_pid_file.read_text(encoding="ascii").strip())

    channel_pid_file = work / "channel.pid"
    channel_cmd = Path(sys.argv[4])
    state = {"channel": "release", "releaseExecutable": str(channel_cmd)}
    # Exercise PreviewChannel.restart() path directly in both handoff and restricted modes.
    class _ChannelHost(QObject):
        jobDone = Signal(str, object)
        def __init__(self):
            super().__init__()
            self.store = SimpleNamespace(directory=profile, data={"agent": {}}, save=lambda: None)
            self._closing = False
        def close(self):
            pass
    ch_host = _ChannelHost()
    ch = PreviewChannel(ch_host)
    ch._state = state
    ch._status = {"state": "restart-required"}
    # Prevent quit from ending before we flush ready_file; quit runs only after restart() succeeds.
    orig_quit = QCoreApplication.instance().quit
    QCoreApplication.instance().quit = lambda: None
    try:
        ch.restart()
    finally:
        QCoreApplication.instance().quit = orig_quit
    assert ch.status.get("state") != "error", f"PreviewChannel.restart failed: {ch.status}"

    end = time.monotonic() + 15
    while not channel_pid_file.is_file() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.05)
    assert channel_pid_file.is_file(), "Channel handoff process did not start"
    info["channel_pid"] = int(channel_pid_file.read_text(encoding="ascii").strip())

tmp = ready_file.with_suffix(".tmp")
tmp.write_text(json.dumps(info), encoding="utf-8")
tmp.replace(ready_file)
if mode == "handoff_clean_exit":
    sys.exit(0)
time.sleep(60)
"""


HOST_NESTED_JOBS = r"""
import json, os, subprocess, sys, time
from pathlib import Path
from PySide6.QtCore import QCoreApplication
from app.pi_runtime import node_executable
from app.pi_sessions import PiSessionPool, SessionState
from app.windows_job import assign_subprocess, ensure_managed_job

work = Path(sys.argv[1])
ready_file = work / "nested-ready.json"
assert ensure_managed_job(), "ensure_managed_job() failed"

app = QCoreApplication([])

# 1. Real PiSessionPool QProcess starting Node, which runs real app/bash_job_windows.py nested jobs.
node_script = work / "pi_nested_fixture.mjs"
node_script.write_text(r'''
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import fs from "node:fs";

const work = process.env.UMEKO_TEST_WORK;
const py = process.env.UMEKO_TEST_PY;
const mainPy = process.env.UMEKO_TEST_MAIN;

function startBashJob(markerPath) {
  const child = spawn(py, [mainPy, "--umeko-bash-job"], {
    stdio: ["pipe", "pipe", "pipe"],
    windowsHide: true,
  });
  const lines = createInterface({ input: child.stdout });
  const req = {
    args: [py, "-c", `import os, time; from pathlib import Path; Path(${JSON.stringify(markerPath)}).write_text(str(os.getpid()), encoding="ascii"); time.sleep(60)`],
    cwd: work,
  };
  child.stdin.write(JSON.stringify(req) + "\n");
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("bash_job timeout")), 15000);
    lines.on("line", (line) => {
      const msg = JSON.parse(line);
      if (msg.pid) {
        clearTimeout(timer);
        resolve({ helper: child, grandchildPid: msg.pid, lines });
      }
    });
  });
}

(async () => {
  // First nested bash job: verify single-command stop cleans up its grandchild while desktop lives.
  const first = await startBashJob(work + "\\bash1.pid");
  const doneFirst = new Promise((resolve) => {
    first.lines.on("line", (line) => {
      const msg = JSON.parse(line);
      if (msg.cleanup) resolve(msg);
    });
  });
  first.helper.stdin.write("stop\n");
  const firstCleanup = await doneFirst;

  // Second nested bash job: keep running until desktop is TerminateProcess'd.
  const second = await startBashJob(work + "\\bash2.pid");
  const info = {
    node_pid: process.pid,
    first_grandchild_pid: first.grandchildPid,
    first_cleanup: firstCleanup.cleanup,
    bash_helper_pid: second.helper.pid,
    bash_grandchild_pid: second.grandchildPid,
  };
  fs.writeFileSync(work + "\\pi-info.tmp", JSON.stringify(info));
  fs.renameSync(work + "\\pi-info.tmp", work + "\\pi-info.json");
  // Deliberately ignore stdin EOF so only OS Job termination can kill this Node process.
  setInterval(() => {}, 1000);
})().catch((err) => {
  fs.writeFileSync(work + "\\pi-error.txt", String(err));
  process.exit(1);
});
''', encoding="utf-8")

os.environ["UMEKO_TEST_WORK"] = str(work)
os.environ["UMEKO_TEST_PY"] = sys.executable
os.environ["UMEKO_TEST_MAIN"] = str(Path.cwd() / "main.py")

pool = PiSessionPool()
record = SessionState(id="nested-pi", workspace=str(work))
pool.touch(record, current=True)
pool.start(record, node_executable(), node_script, {"type": "init"})

pi_info_file = work / "pi-info.json"
deadline = time.monotonic() + 20
while not pi_info_file.is_file() and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.05)
assert pi_info_file.is_file(), f"Pi nested fixture failed: {(work / 'pi-error.txt').read_text() if (work / 'pi-error.txt').exists() else 'timeout'}"
pi_info = json.loads(pi_info_file.read_text(encoding="utf-8"))
assert pi_info["first_cleanup"] == "done", pi_info

# 2. Real terminal pty_backend NativePty nested ConPTY Job inside a managed worker child.
term_script = work / "term_nested_fixture.py"
term_script.write_text(r'''
import json, os, shutil, sys, time
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "umeko-plugins/terminal/scripts"))
from pty_backend import NativePty

work = Path(sys.argv[1])
shell = shutil.which("powershell.exe") or shutil.which("cmd.exe")
env = os.environ.copy()

# First ConPTY shell: verify normal close() stops it while desktop is alive.
pty1 = NativePty([shell, "-NoLogo", "-NoProfile"], work, env, 80, 24)
pid1 = pty1.pid
pty1.close()
assert not pty1.isalive(), "pty1 survived close()"

# Second ConPTY shell: keep running until desktop is TerminateProcess'd.
pty2 = NativePty([shell, "-NoLogo", "-NoProfile"], work, env, 80, 24)
info = {"term_worker_pid": os.getpid(), "closed_shell_pid": pid1, "live_shell_pid": pty2.pid}
tmp = work / "term-info.tmp"
tmp.write_text(json.dumps(info), encoding="utf-8")
tmp.replace(work / "term-info.json")
time.sleep(60)
''', encoding="utf-8")

term_worker = subprocess.Popen(
    [sys.executable, str(term_script), str(work)],
    cwd=Path.cwd(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    creationflags=subprocess.CREATE_NO_WINDOW,
)
assign_subprocess(term_worker)

term_info_file = work / "term-info.json"
deadline = time.monotonic() + 20
while not term_info_file.is_file() and time.monotonic() < deadline:
    time.sleep(0.05)
assert term_info_file.is_file(), f"Terminal nested fixture failed: {term_worker.stderr.read().decode('utf-8', 'replace') if term_worker.poll() is not None else 'timeout'}"
term_info = json.loads(term_info_file.read_text(encoding="utf-8"))

combined = {**pi_info, **term_info}
tmp = ready_file.with_suffix(".tmp")
tmp.write_text(json.dumps(combined), encoding="utf-8")
tmp.replace(ready_file)
time.sleep(60)
"""


HOST_SUPERVISE_SESSION = r"""
import json, os, sys, time
from pathlib import Path
from PySide6.QtCore import QCoreApplication
from app.pi_runtime import node_executable
from app.pi_sessions import PiSessionPool, SessionState
from app.windows_job import ensure_managed_job

work = Path(sys.argv[1])
stdin_open = sys.argv[2].lower() == "true"
ready_file = work / "session-ready.json"
assert ensure_managed_job(), "ensure_managed_job() failed"

app = QCoreApplication([])

node_script = work / "pi_supervise_session_fixture.mjs"
node_script.write_text(r'''
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import fs from "node:fs";
import path from "node:path";

const work = process.env.UMEKO_TEST_WORK;
const py = process.env.UMEKO_TEST_PY;
const mainPy = process.env.UMEKO_TEST_MAIN;
const stdinOpen = process.env.UMEKO_TEST_STDIN_OPEN === "true";

function startSession(name, childCode) {
  const stdoutPath = path.join(work, `${name}.out`);
  const stderrPath = path.join(work, `${name}.err`);
  const child = spawn(py, [mainPy, "--umeko-bash-job"], {
    stdio: ["pipe", "pipe", "pipe"],
    windowsHide: true,
  });
  const lines = createInterface({ input: child.stdout });
  const req = {
    args: [py, "-c", childCode],
    cwd: work,
    stdoutPath,
    stderrPath,
    stdinOpen,
  };
  const writeReplies = new Map();
  let resolveReady, resolveDone;
  const ready = new Promise((res, rej) => {
    const timer = setTimeout(() => rej(new Error(`supervise_session ${name} timeout`)), 15000);
    resolveReady = (v) => { clearTimeout(timer); res(v); };
  });
  const done = new Promise((res) => { resolveDone = res; });
  lines.on("line", (line) => {
    const msg = JSON.parse(line);
    if (msg.pid) resolveReady({ cmdPid: msg.pid, helperPid: child.pid });
    if (msg.writeId !== undefined && writeReplies.has(msg.writeId)) {
      const fn = writeReplies.get(msg.writeId);
      writeReplies.delete(msg.writeId);
      fn(msg);
    }
    if (msg.cleanup) resolveDone(msg);
  });
  child.stdin.write(JSON.stringify(req) + "\n");
  function writeInput(writeId, text) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`write ${writeId} timeout`)), 10000);
      writeReplies.set(writeId, (msg) => { clearTimeout(timer); resolve(msg); });
      child.stdin.write(JSON.stringify({ writeId, input: text }) + "\n");
    });
  }
  return { child, ready, done, writeInput, stdoutPath, stderrPath };
}

async function waitFile(filePath, pred, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (fs.existsSync(filePath)) {
      const text = fs.readFileSync(filePath, "utf8");
      if (pred(text)) return text;
    }
    await new Promise((r) => setTimeout(r, 40));
  }
  throw new Error(`Timed out waiting for ${filePath}`);
}

(async () => {
  const gc1File = path.join(work, "gc1.pid");
  const gc2File = path.join(work, "gc2.pid");

  // 1. First command: verify stdinOpen=false uses os.devnull (EOF) / stdinOpen=true reads pipe,
  //    and single-command stop cleans up both command and grandchild.
  const firstCode = stdinOpen
    ? `import os, subprocess, sys, time
from pathlib import Path
gc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
Path(${JSON.stringify(gc1File)}).write_text(str(gc.pid), encoding="ascii")
line = sys.stdin.readline().strip()
print("GOT:" + line, flush=True)
time.sleep(60)`
    : `import os, subprocess, sys, time
from pathlib import Path
gc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
Path(${JSON.stringify(gc1File)}).write_text(str(gc.pid), encoding="ascii")
data = sys.stdin.read()
assert data == "", f"expected empty EOF from os.devnull, got {data!r}"
print("STDIN_EOF_OK", flush=True)
time.sleep(60)`;

  const first = startSession("first", firstCode);
  const firstIds = await first.ready;
  const gc1Pid = parseInt((await waitFile(gc1File, (t) => t.trim().length > 0)).trim(), 10);
  let stdinCheckOk = false;
  if (stdinOpen) {
    const reply = await first.writeInput(1, "hello-pipe\n");
    if (reply.error) throw new Error("Unexpected write error for stdinOpen=true: " + reply.error);
    const out1 = await waitFile(first.stdoutPath, (t) => t.includes("GOT:hello-pipe"));
    stdinCheckOk = out1.includes("GOT:hello-pipe");
  } else {
    const out1 = await waitFile(first.stdoutPath, (t) => t.includes("STDIN_EOF_OK"));
    const reply = await first.writeInput(1, "should-fail\n");
    stdinCheckOk = out1.includes("STDIN_EOF_OK") && reply.error === "Standard input is closed for this command.";
  }
  first.child.stdin.write("stop\n");
  const firstCleanup = await first.done;

  // 2. Second command: stays active with a grandchild until desktop host is TerminateProcess'd.
  const secondCode = `import os, subprocess, sys, time
from pathlib import Path
gc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
Path(${JSON.stringify(gc2File)}).write_text(str(gc.pid), encoding="ascii")
print("SECOND_LIVE", flush=True)
time.sleep(60)`;
  const second = startSession("second", secondCode);
  const secondIds = await second.ready;
  const gc2Pid = parseInt((await waitFile(gc2File, (t) => t.trim().length > 0)).trim(), 10);
  await waitFile(second.stdoutPath, (t) => t.includes("SECOND_LIVE"));

  const info = {
    stdin_open: stdinOpen,
    stdin_check_ok: stdinCheckOk,
    node_pid: process.pid,
    first_cmd_pid: firstIds.cmdPid,
    first_grandchild_pid: gc1Pid,
    first_cleanup: firstCleanup.cleanup,
    bash_helper_pid: secondIds.helperPid,
    cmd_pid: secondIds.cmdPid,
    grandchild_pid: gc2Pid,
  };
  const tmp = path.join(work, "session-ready.tmp");
  fs.writeFileSync(tmp, JSON.stringify(info));
  fs.renameSync(tmp, path.join(work, "session-ready.json"));
  setInterval(() => {}, 1000);
})().catch((err) => {
  fs.writeFileSync(path.join(work, "session-error.txt"), String(err && err.stack || err));
  process.exit(1);
});
''', encoding="utf-8")

os.environ["UMEKO_TEST_WORK"] = str(work)
os.environ["UMEKO_TEST_PY"] = sys.executable
os.environ["UMEKO_TEST_MAIN"] = str(Path.cwd() / "main.py")
os.environ["UMEKO_TEST_STDIN_OPEN"] = "true" if stdin_open else "false"

pool = PiSessionPool()
record = SessionState(id=f"supervise-session-{stdin_open}", workspace=str(work))
pool.touch(record, current=True)
pool.start(record, node_executable(), node_script, {"type": "init"})

deadline = time.monotonic() + 25
while not ready_file.is_file() and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.05)
assert ready_file.is_file(), f"supervise_session fixture failed: {(work / 'session-error.txt').read_text(encoding='utf-8', errors='replace') if (work / 'session-error.txt').exists() else 'timeout'}"
time.sleep(60)
"""


@unittest.skipUnless(sys.platform == "win32", "Windows Job Object")
class WindowsDesktopJobTests(unittest.TestCase):
    def _run_host_scenario(self, mode: str, *, extra_args=(), warning_error: bool = False):
        with tempfile.TemporaryDirectory(prefix=f"umeko-job-{mode}-") as temp:
            work = Path(temp)
            profile = work / "profile"
            marker = work / "plugin-marker.json"
            _write_blocking_plugin(profile, "job-probe", marker, lifecycle="session")
            cmd = [sys.executable]
            if warning_error:
                cmd.extend(["-W", "error::ResourceWarning"])
            cmd.extend(["-c", HOST_PLUGINS_AND_APPS, mode, str(work), *map(str, extra_args)])
            env = {
                **os.environ,
                "QT_QPA_PLATFORM": "offscreen",
                "QT_QUICK_BACKEND": "software",
                "UMEKO_DATA_DIR": str(profile),
            }
            handles = {}
            proc = None
            try:
                proc = subprocess.Popen(
                    cmd, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                ready = _wait_json(work / "host-ready.json", timeout=25.0, process=proc)
                if ready is None:
                    stderr_text = proc.stderr.read().decode("utf-8", "replace") if proc.poll() is not None else "still running"
                    self.fail(f"Host scenario {mode!r} did not become ready (rc={proc.poll()}): {stderr_text}")
                yield work, proc, ready, handles
            finally:
                if proc is not None and proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
                if proc is not None:
                    if proc.stdout:
                        proc.stdout.close()
                    if proc.stderr:
                        proc.stderr.close()
                _cleanup_handles(handles)

    def test_desktop_plugins_qprocess_reaps_blocked_worker_and_grandchild_on_terminate(self):
        import _winapi

        for _, proc, ready, handles in self._run_host_scenario("basic"):
            handles.update(_open_handles({
                "worker": ready["worker_pid"],
                "grandchild": ready["grandchild_pid"],
            }))
            self.assertEqual(_winapi.WaitForSingleObject(handles["worker"], 0), _winapi.WAIT_TIMEOUT)
            self.assertEqual(_winapi.WaitForSingleObject(handles["grandchild"], 0), _winapi.WAIT_TIMEOUT)
            proc.kill()
            proc.wait(timeout=5)
            self.assertEqual(_winapi.WaitForSingleObject(handles["worker"], 5000), _winapi.WAIT_OBJECT_0)
            self.assertEqual(_winapi.WaitForSingleObject(handles["grandchild"], 5000), _winapi.WAIT_OBJECT_0)

    def test_main_py_reaps_builtin_workers_and_plugin_descendant_on_terminate(self):
        import _winapi

        with tempfile.TemporaryDirectory(prefix="umeko-job-main-") as temp:
            work = Path(temp)
            profile = work / "profile"
            marker = work / "main-plugin-marker.json"
            diag = work / "diagnostics.log"
            _write_blocking_plugin(profile, "job-main-probe", marker, lifecycle="application")
            env = {
                **os.environ,
                "QT_QPA_PLATFORM": "offscreen",
                "QT_QUICK_BACKEND": "software",
                "UMEKO_DATA_DIR": str(profile),
                "UMEKO_DIAGNOSTICS": str(diag),
            }
            handles = {}
            proc = subprocess.Popen(
                [sys.executable, str(ROOT / "main.py")],
                cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                ready = _wait_json(marker, timeout=30.0, process=proc)
                if ready is None:
                    err = proc.stderr.read().decode("utf-8", "replace") if proc.poll() is not None else "still running"
                    self.fail(f"main.py did not initialize probe plugin (rc={proc.poll()}): {err}")
                deadline = time.monotonic() + 20.0
                while time.monotonic() < deadline and proc.poll() is None:
                    if diag.is_file() and "QML_READY" in diag.read_text(encoding="utf-8", errors="replace"):
                        break
                    time.sleep(0.05)
                self.assertTrue(diag.is_file() and "QML_READY" in diag.read_text(encoding="utf-8", errors="replace"))
                handles.update(_open_handles({
                    "worker": ready["worker_pid"],
                    "grandchild": ready["grandchild_pid"],
                }))
                self.assertEqual(_winapi.WaitForSingleObject(handles["worker"], 0), _winapi.WAIT_TIMEOUT)
                self.assertEqual(_winapi.WaitForSingleObject(handles["grandchild"], 0), _winapi.WAIT_TIMEOUT)
                proc.kill()
                proc.wait(timeout=5)
                self.assertEqual(_winapi.WaitForSingleObject(handles["worker"], 5000), _winapi.WAIT_OBJECT_0)
                self.assertEqual(_winapi.WaitForSingleObject(handles["grandchild"], 5000), _winapi.WAIT_OBJECT_0)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
                proc.stdout.close()
                proc.stderr.close()
                _cleanup_handles(handles)

    def test_pi_session_and_nested_jobs_reaped_on_desktop_terminate(self):
        import _winapi

        with tempfile.TemporaryDirectory(prefix="umeko-job-nested-") as temp:
            work = Path(temp)
            env = {
                **os.environ,
                "QT_QPA_PLATFORM": "offscreen",
                "QT_QUICK_BACKEND": "software",
            }
            handles = {}
            proc = subprocess.Popen(
                [sys.executable, "-c", HOST_NESTED_JOBS, str(work)],
                cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                ready = _wait_json(work / "nested-ready.json", timeout=30.0, process=proc)
                if ready is None:
                    err = proc.stderr.read().decode("utf-8", "replace") if proc.poll() is not None else "still running"
                    self.fail(f"Nested Job host did not become ready (rc={proc.poll()}): {err}")
                handles.update(_open_handles({
                    "node": ready["node_pid"],
                    "bash_helper": ready["bash_helper_pid"],
                    "bash_grandchild": ready["bash_grandchild_pid"],
                    "term_worker": ready["term_worker_pid"],
                    "live_shell": ready["live_shell_pid"],
                }))
                for name, handle in handles.items():
                    self.assertEqual(_winapi.WaitForSingleObject(handle, 0), _winapi.WAIT_TIMEOUT, name)
                proc.kill()
                proc.wait(timeout=5)
                for name, handle in handles.items():
                    self.assertEqual(_winapi.WaitForSingleObject(handle, 5000), _winapi.WAIT_OBJECT_0,
                                     f"{name} survived desktop TerminateProcess")
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
                proc.stdout.close()
                proc.stderr.close()
                _cleanup_handles(handles)

    def test_external_apps_outlive_desktop_exit(self):
        import _winapi

        for _, proc, ready, handles in self._run_host_scenario("external"):
            handles.update(_open_handles({
                "worker": ready["worker_pid"],
                "grandchild": ready["grandchild_pid"],
                "terminal": ready["terminal_pid"],
                "shell": ready["shell_pid"],
                "browser": ready["browser_pid"],
            }))
            proc.kill()
            proc.wait(timeout=5)
            # Managed plugin worker and its grandchild must exit promptly.
            self.assertEqual(_winapi.WaitForSingleObject(handles["worker"], 5000), _winapi.WAIT_OBJECT_0)
            self.assertEqual(_winapi.WaitForSingleObject(handles["grandchild"], 5000), _winapi.WAIT_OBJECT_0)
            # User-opened external apps must survive desktop termination.
            time.sleep(0.5)
            for name in ("terminal", "shell", "browser"):
                self.assertEqual(_winapi.WaitForSingleObject(handles[name], 0), _winapi.WAIT_TIMEOUT,
                                 f"External app {name} was killed when desktop exited")

    def test_update_installer_and_preview_channel_handoff_outlive_desktop_without_resource_warning(self):
        import _winapi

        with tempfile.TemporaryDirectory(prefix="umeko-job-handoff-bins-", ignore_cleanup_errors=True) as bins:
            bins_dir = Path(bins)
            # The host writes installer.pid and channel.pid inside its own work dir;
            # pass explicit work-scoped files by creating them via a shared temp dir.
            installer_pid = bins_dir / "installer.pid"
            channel_pid = bins_dir / "channel.pid"
            # Wait: the host script reads work / "installer.pid", so run directly in one temp dir.
            installer_cmd = _write_sleeper_cmd(bins_dir, "installer-helper", installer_pid)
            channel_cmd = _write_sleeper_cmd(bins_dir, "channel-helper", channel_pid)
            # Rewrite HOST_PLUGINS_AND_APPS work paths by running a dedicated check directly:
            script = (
                "import json, os, sys, time\n"
                "from pathlib import Path\n"
                "from types import SimpleNamespace\n"
                "os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')\n"
                "os.environ.setdefault('QT_QUICK_BACKEND', 'software')\n"
                "from PySide6.QtCore import QCoreApplication, QObject, Signal\n"
                "from app.desktop_plugins import DesktopPlugins\n"
                "from app.preview_channel import PreviewChannel\n"
                "from app.update import AppUpdater\n"
                "from app.windows_job import ensure_managed_job\n"
                "work = Path(sys.argv[1])\n"
                "profile = work / 'profile'\n"
                "workspace = work / 'workspace'; workspace.mkdir(parents=True, exist_ok=True)\n"
                "assert ensure_managed_job()\n"
                "app = QCoreApplication([])\n"
                "class Pool(QObject):\n"
                "    event = Signal(object, object)\n"
                "    def __init__(self, r): super().__init__(); self.records = {r.key: r}\n"
                "    def write(self, *a): pass\n"
                "    def find(self, i): return next((r for r in self.records.values() if r.id == i), None)\n"
                "class Host(QObject):\n"
                "    viewChanged = Signal(); chatChanged = Signal(); toast = Signal(str)\n"
                "    documentRequested = Signal(str, str, str); widgetDocumentRequested = Signal(str, str, str, str)\n"
                "    editorText = Signal(str); jobDone = Signal(str, object)\n"
                "    def __init__(self):\n"
                "        super().__init__()\n"
                "        self.root = Path.cwd(); self._closing = False\n"
                "        self.store = SimpleNamespace(directory=profile, data={'selectedModel': 'f', 'agent': {}}, save=lambda: None)\n"
                "        self.characterStyle = {'id': 'yanami'}\n"
                "        self._view = SimpleNamespace(key='k', id='s', workspace=str(workspace), title='t', busy=False, global_agent='', failed=False, cancelled=False, messages=[])\n"
                "        self._pool = Pool(self._view)\n"
                "    def close(self): pass\n"
                "host = Host()\n"
                "manager = DesktopPlugins(host)\n"
                "manager.setSessionEnabled('job-probe', True)\n"
                "assert manager.openPage('job-probe')\n"
                "end = time.monotonic() + 20\n"
                "while time.monotonic() < end and not manager.workers.get('job-probe', {}).get('ready'):\n"
                "    app.processEvents(); time.sleep(0.02)\n"
                "manager.call_for('job-probe', 'block', '{}')\n"
                "for _ in range(10): app.processEvents(); time.sleep(0.02)\n"
                "job_file = work / 'job.json'\n"
                "job_file.write_text(json.dumps({'helperExe': sys.argv[2]}), encoding='utf-8')\n"
                "updater = AppUpdater(host); updater.job_file = job_file; updater.launch_installer()\n"
                "assert updater.state != 'error', getattr(updater, '_error', '')\n"
                "channel = PreviewChannel(host)\n"
                "channel._state = {'channel': 'release', 'releaseExecutable': sys.argv[3]}\n"
                "channel._status = {'state': 'restart-required'}\n"
                "orig_quit = app.quit; app.quit = lambda: None\n"
                "try: channel.restart()\n"
                "finally: app.quit = orig_quit\n"
                "assert channel.status.get('state') != 'error', channel.status\n"
                "import gc; gc.collect()\n"
                "end = time.monotonic() + 15\n"
                "while time.monotonic() < end and not (Path(sys.argv[4]).is_file() and Path(sys.argv[5]).is_file()):\n"
                "    app.processEvents(); time.sleep(0.05)\n"
                "assert Path(sys.argv[4]).is_file() and Path(sys.argv[5]).is_file()\n"
                "info = json.loads((work / 'plugin-marker.json').read_text(encoding='utf-8'))\n"
                "info['installer_pid'] = int(Path(sys.argv[4]).read_text(encoding='ascii').strip())\n"
                "info['channel_pid'] = int(Path(sys.argv[5]).read_text(encoding='ascii').strip())\n"
                "tmp = work / 'ready.tmp'; tmp.write_text(json.dumps(info), encoding='utf-8'); tmp.replace(work / 'ready.json')\n"
                "go_end = time.monotonic() + 20\n"
                "while time.monotonic() < go_end and not (work / 'go').is_file():\n"
                "    app.processEvents(); time.sleep(0.02)\n"
                "if sys.argv[6] == 'exit': sys.exit(0)\n"
                "time.sleep(60)\n"
            )
            profile = bins_dir / "profile"
            _write_blocking_plugin(profile, "job-probe", bins_dir / "plugin-marker.json", lifecycle="session")
            handles = {}
            stdout_path = bins_dir / "handoff-stdout.log"
            stderr_path = bins_dir / "handoff-stderr.log"
            with stdout_path.open("wb") as out_f, stderr_path.open("wb") as err_f:
                proc = subprocess.Popen(
                    [sys.executable, "-W", "error::ResourceWarning", "-c", script,
                     str(bins_dir), str(installer_cmd), str(channel_cmd),
                     str(installer_pid), str(channel_pid), "exit"],
                    cwd=ROOT, env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software",
                                   "UMEKO_DATA_DIR": str(profile)},
                    stdin=subprocess.DEVNULL, stdout=out_f, stderr=err_f,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            try:
                ready_file = bins_dir / "ready.json"
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline and proc.poll() is None and not ready_file.is_file():
                    time.sleep(0.05)
                stderr_early = stderr_path.read_text(encoding="utf-8", errors="replace") if stderr_path.is_file() else ""
                self.assertTrue(ready_file.is_file(), f"Handoff host did not reach ready (rc={proc.poll()}): {stderr_early}")
                ready = json.loads(ready_file.read_text(encoding="utf-8"))
                handles.update(_open_handles({
                    "worker": ready["worker_pid"],
                    "grandchild": ready["grandchild_pid"],
                    "installer": ready["installer_pid"],
                    "channel": ready["channel_pid"],
                }))
                for name, handle in handles.items():
                    self.assertEqual(_winapi.WaitForSingleObject(handle, 0), _winapi.WAIT_TIMEOUT, f"{name} exited early")
                (bins_dir / "go").write_text("exit", encoding="ascii")
                proc.wait(timeout=30)
                stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")
                self.assertEqual(proc.returncode, 0, stderr_text)
                # Even without calling manager.close(), exiting the host closes _managed_job and reaps managed workers.
                self.assertEqual(_winapi.WaitForSingleObject(handles["worker"], 5000), _winapi.WAIT_OBJECT_0)
                self.assertEqual(_winapi.WaitForSingleObject(handles["grandchild"], 5000), _winapi.WAIT_OBJECT_0)
                time.sleep(0.5)
                self.assertEqual(_winapi.WaitForSingleObject(handles["installer"], 0), _winapi.WAIT_TIMEOUT)
                self.assertEqual(_winapi.WaitForSingleObject(handles["channel"], 0), _winapi.WAIT_TIMEOUT)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
                _cleanup_handles(handles)

    def test_restricted_outer_job_without_breakaway_allows_startup_reap_and_handoff(self):
        import _winapi

        with tempfile.TemporaryDirectory(prefix="umeko-job-restricted-") as temp:
            work = Path(temp)
            profile = work / "profile"
            _write_blocking_plugin(profile, "job-probe", work / "plugin-marker.json", lifecycle="session")
            installer_cmd = _write_sleeper_cmd(work, "installer-helper", work / "installer.pid")
            channel_cmd = _write_sleeper_cmd(work, "channel-helper", work / "channel.pid")
            env = {
                **os.environ,
                "QT_QPA_PLATFORM": "offscreen",
                "QT_QUICK_BACKEND": "software",
                "UMEKO_DATA_DIR": str(profile),
            }
            outer_job = None
            proc_handle = None
            handles = {}
            stdout_path = work / "restricted-stdout.log"
            stderr_path = work / "restricted-stderr.log"
            try:
                outer_job, proc_handle, _ = _spawn_inside_restricted_job(
                    [sys.executable, "-c", HOST_PLUGINS_AND_APPS, "restricted", str(work),
                     str(installer_cmd), str(channel_cmd)],
                    cwd=ROOT, env=env, stdout_path=stdout_path, stderr_path=stderr_path,
                )
                deadline = time.monotonic() + 25.0
                ready = None
                while time.monotonic() < deadline:
                    if (work / "host-ready.json").is_file():
                        try:
                            ready = json.loads((work / "host-ready.json").read_text(encoding="utf-8"))
                            break
                        except (OSError, ValueError):
                            pass
                    if _winapi.WaitForSingleObject(proc_handle, 0) == _winapi.WAIT_OBJECT_0:
                        break
                    time.sleep(0.05)
                if ready is None:
                    err = stderr_path.read_text(encoding="utf-8", errors="replace") if stderr_path.is_file() else ""
                    out = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.is_file() else ""
                    self.fail(f"Restricted outer-Job desktop failed:\nSTDOUT:\n{out}\nSTDERR:\n{err}")
                self.assertEqual(ready.get("negative_control_winerror"), 5)
                handles.update(_open_handles({
                    "worker": ready["worker_pid"],
                    "grandchild": ready["grandchild_pid"],
                    "installer": ready["installer_pid"],
                    "channel": ready["channel_pid"],
                }))
                _winapi.TerminateProcess(proc_handle, 1)
                self.assertEqual(_winapi.WaitForSingleObject(proc_handle, 5000), _winapi.WAIT_OBJECT_0)
                self.assertEqual(_winapi.WaitForSingleObject(handles["worker"], 5000), _winapi.WAIT_OBJECT_0)
                self.assertEqual(_winapi.WaitForSingleObject(handles["grandchild"], 5000), _winapi.WAIT_OBJECT_0)
                time.sleep(0.5)
                self.assertEqual(_winapi.WaitForSingleObject(handles["installer"], 0), _winapi.WAIT_TIMEOUT)
                self.assertEqual(_winapi.WaitForSingleObject(handles["channel"], 0), _winapi.WAIT_TIMEOUT)
            finally:
                if proc_handle:
                    try:
                        if _winapi.WaitForSingleObject(proc_handle, 0) == _winapi.WAIT_TIMEOUT:
                            _winapi.TerminateProcess(proc_handle, 1)
                            _winapi.WaitForSingleObject(proc_handle, 5000)
                    except OSError:
                        pass
                    from app.windows_job import close_handle
                    close_handle(proc_handle)
                _cleanup_handles(handles)
                if outer_job is not None:
                    from app.windows_job import close_handle
                    close_handle(outer_job)

    def _assert_supervise_session(self, *, stdin_open: bool):
        import _winapi

        with tempfile.TemporaryDirectory(prefix=f"umeko-job-session-{int(stdin_open)}-") as temp:
            work = Path(temp)
            env = {
                **os.environ,
                "QT_QPA_PLATFORM": "offscreen",
                "QT_QUICK_BACKEND": "software",
            }
            handles = {}
            proc = subprocess.Popen(
                [sys.executable, "-c", HOST_SUPERVISE_SESSION, str(work), "true" if stdin_open else "false"],
                cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                ready = _wait_json(work / "session-ready.json", timeout=30.0, process=proc)
                if ready is None:
                    err = proc.stderr.read().decode("utf-8", "replace") if proc.poll() is not None else "still running"
                    self.fail(f"supervise_session(stdinOpen={stdin_open}) host failed (rc={proc.poll()}): {err}")
                self.assertTrue(ready["stdin_check_ok"], ready)
                self.assertEqual(ready["first_cleanup"], "done", ready)
                # Confirm the first command and its grandchild exited after single-command stop.
                for stopped_key in ("first_cmd_pid", "first_grandchild_pid"):
                    try:
                        h = _winapi.OpenProcess(SYNCHRONIZE_AND_TERMINATE, False, int(ready[stopped_key]))
                    except OSError:
                        continue
                    try:
                        self.assertEqual(
                            _winapi.WaitForSingleObject(h, 2000), _winapi.WAIT_OBJECT_0,
                            f"{stopped_key} survived single-command stop (stdinOpen={stdin_open})",
                        )
                    finally:
                        _winapi.CloseHandle(h)

                handles.update(_open_handles({
                    "node": ready["node_pid"],
                    "bash_helper": ready["bash_helper_pid"],
                    "cmd": ready["cmd_pid"],
                    "grandchild": ready["grandchild_pid"],
                }))
                for name, handle in handles.items():
                    self.assertEqual(_winapi.WaitForSingleObject(handle, 0), _winapi.WAIT_TIMEOUT, name)
                proc.kill()
                proc.wait(timeout=5)
                for name, handle in handles.items():
                    self.assertEqual(
                        _winapi.WaitForSingleObject(handle, 5000), _winapi.WAIT_OBJECT_0,
                        f"{name} survived desktop TerminateProcess (stdinOpen={stdin_open})",
                    )
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
                proc.stdout.close()
                proc.stderr.close()
                _cleanup_handles(handles)

    def test_supervise_session_stdin_closed_cleanup_and_reap_on_terminate(self):
        self._assert_supervise_session(stdin_open=False)

    def test_supervise_session_stdin_open_cleanup_and_reap_on_terminate(self):
        self._assert_supervise_session(stdin_open=True)

    def test_job_creation_failure_degrades_gracefully_and_main_starts(self):
        from app import windows_job

        prev_job, prev_unavail = windows_job._managed_job, windows_job._managed_job_unavailable
        try:
            windows_job._managed_job = None
            windows_job._managed_job_unavailable = False
            with patch.object(windows_job, "create_kill_on_close_job", side_effect=PermissionError("Access is denied")):
                self.assertFalse(windows_job.ensure_managed_job())
                self.assertFalse(windows_job.assign_process_id(os.getpid()))
        finally:
            windows_job._managed_job = prev_job
            windows_job._managed_job_unavailable = prev_unavail

        # End-to-end main.py --smoke startup when CreateJobObjectW raises PermissionError.
        with tempfile.TemporaryDirectory(prefix="umeko-job-denied-") as temp:
            work = Path(temp)
            profile = work / "profile"
            diag = work / "diagnostics.log"
            hook_dir = work / "hook"
            hook_dir.mkdir()
            (hook_dir / "sitecustomize.py").write_text(
                "import app.windows_job as wj\n"
                "def _deny(*a, **kw):\n"
                "    raise PermissionError('Simulated restricted job environment')\n"
                "wj.create_kill_on_close_job = _deny\n",
                encoding="utf-8",
            )
            env = {
                **os.environ,
                "QT_QPA_PLATFORM": "offscreen",
                "QT_QUICK_BACKEND": "software",
                "UMEKO_DATA_DIR": str(profile),
                "UMEKO_DIAGNOSTICS": str(diag),
                "PYTHONPATH": str(hook_dir) + os.pathsep + str(ROOT) + (
                    os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""
                ),
            }
            result = subprocess.run(
                [sys.executable, str(ROOT / "main.py"), "--smoke"],
                cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=45, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            self.assertEqual(result.returncode, 0, result.stderr + "\n" + result.stdout)
            self.assertTrue(diag.is_file(), "Diagnostics file not written")
            text = diag.read_text(encoding="utf-8", errors="replace")
            self.assertIn("QML_READY", text)
            self.assertIn("EXIT:0", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
