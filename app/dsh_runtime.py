"""Discover, check and install the official DSH runtime without blocking Qt.

The managed installation is separate from DSH's profile. Health checks use a
temporary home and the official ACP SDK bridge; they never send a model prompt.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot

from .filesystem_paths import filesystem_path, ordinary_path
from .npm_config import npm_environment
from .pi_runtime import CREATE_NO_WINDOW, node_executable, npm_command

PACKAGE = "@deepseek-ai/dsh"
PINNED_VERSION = "0.2.2-rc.1"
OFFICIAL_REGISTRY = "https://registry.npmjs.org/"
RELEASE_NAME = "dsh-" + PINNED_VERSION


class RuntimeFailure(RuntimeError):
    def __init__(self, code, message, hint):
        super().__init__(message)
        self.code, self.hint = code, hint


def _version(value):
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?", value.strip())
    if not match:
        raise ValueError("invalid version")
    core = tuple(map(int, match.group(1, 2, 3)))
    # Release versions sort above prereleases; numeric prerelease identifiers
    # sort below textual identifiers, as required by SemVer.
    prerelease = tuple((0, int(part)) if part.isdigit() else (1, part)
                       for part in (match[4] or "").split("."))
    return core, not bool(match[4]), prerelease


def _candidates(path):
    path = ordinary_path(Path(path).expanduser()).resolve()
    if path.is_dir():
        return [path / "node_modules" / PACKAGE / "lib/bin.js",
                path / PACKAGE / "lib/bin.js", path / "lib/bin.js",
                path / "bin.js", path / "dsh.cmd", path / "dsh"]
    return [path]


def _entry(path):
    """Resolve npm Windows shims to JS rather than executing a shell command."""
    if not path.is_file():
        return None
    path = path.resolve()
    if path.suffix.lower() in (".cmd", ".bat", ".ps1"):
        target = path.parent / "node_modules" / PACKAGE / "lib/bin.js"
        return target.resolve() if target.is_file() else None
    return path


def discover_dsh(configured="", runtime_root=None):
    """Configured path wins, then this application's installation, then PATH.

    An explicit invalid path is reported instead of silently using another DSH.
    This keeps the path shown in Settings consistent with the runtime in use.
    """
    if configured:
        groups = [("configured", _candidates(configured))]
    else:
        managed = Path(runtime_root) / RELEASE_NAME if runtime_root else None
        groups = [("managed", _candidates(managed))] if managed else []
        found = shutil.which("dsh.cmd" if os.name == "nt" else "dsh")
        if found:
            groups.append(("path", _candidates(found)))
    for source, candidates in groups:
        for candidate in candidates:
            entry = _entry(candidate)
            if entry:
                return {"path": str(entry), "source": source}
    raise RuntimeFailure("missing", "未找到 dsh", "选择官方 dsh 的安装目录或 bin.js，也可以点击下载。")


def _terminate(process):
    """Stop only this operation's child process and its descendants."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=CREATE_NO_WINDOW, timeout=10)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def _run(command, *, env, cwd, cancelled=None, timeout=60):
    """Bounded output files avoid pipe deadlocks and keep cancellation responsive."""
    if cancelled and cancelled():
        raise InterruptedError("已取消")
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, cwd=str(ordinary_path(cwd)), env=env,
            stdin=subprocess.DEVNULL, stdout=output, stderr=errors,
            creationflags=CREATE_NO_WINDOW, start_new_session=os.name != "nt")
        started = time.monotonic()
        try:
            while process.poll() is None:
                if cancelled and cancelled():
                    raise InterruptedError("已取消")
                if time.monotonic() - started >= timeout:
                    raise RuntimeFailure("timeout", "dsh 操作超时", "检查网络或 dsh 安装后重试。")
                time.sleep(.1)
            output.seek(0)
            # Only bridge/version output is consumed, never relayed to the UI.
            text = output.read(1024 * 1024).decode("utf-8", errors="replace")
            return process.returncode, text
        finally:
            _terminate(process)


def _command(entry):
    return [node_executable(), str(entry)] if entry.suffix.lower() in (".js", ".mjs", ".cjs") else [str(entry)]


def bridge_path():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return root / "runtime/dsh-acp-bridge.mjs"


def _check_entry(entry, source, *, bridge=None, npm_config=None, cancelled=None):
    entry = ordinary_path(entry)
    environment = npm_environment(npm_config or {})
    environment.update(NO_COLOR="1", DO_NOT_TRACK="1", DSH_TELEMETRY_DISABLED="1")
    with tempfile.TemporaryDirectory(prefix="umeko-dsh-check-") as temporary:
        home = Path(temporary)
        environment.update(DSH_HOME=str(home / "dsh"), DSH_AGENTS_HOME=str(home / "agents"),
                           HOME=str(home), USERPROFILE=str(home),
                           APPDATA=str(home / "appdata"), LOCALAPPDATA=str(home / "localappdata"))
        manifest = filesystem_path(entry).parent.parent / "package.json"
        version = ""
        if manifest.is_file():
            try:
                package = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raise RuntimeFailure("version", "无法读取 dsh 版本", "重新安装官方 @deepseek-ai/dsh。") from None
            if package.get("name") != PACKAGE:
                raise RuntimeFailure("package", "所选程序不是官方 dsh", "请选择 @deepseek-ai/dsh，而非同名的 dsh 包。")
            version = str(package.get("version", ""))
        else:
            code, text = _run([*_command(entry), "--version"], env=environment, cwd=home,
                              cancelled=cancelled, timeout=20)
            match = re.search(r"\b\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", text)
            if not code and match:
                version = match[0]
        try:
            supported = _version(version) >= _version(PINNED_VERSION)
        except ValueError:
            supported = False
        if not supported:
            raise RuntimeFailure("version", "dsh 版本不受支持", "需要官方 dsh " + PINNED_VERSION + " 或更新版本；可点击下载。")
        driver = Path(bridge) if bridge else bridge_path()
        if not driver.is_file():
            raise RuntimeFailure("bridge", "ACP 桥接组件缺失", "重新解压完整的 Umeko 安装包。")
        code, text = _run([node_executable(), str(driver), "--health", "--dsh-bin", str(entry),
                          "--dsh-home", str(home / "dsh")], env=environment, cwd=home,
                         cancelled=cancelled, timeout=60)
        responses = []
        for line in text.splitlines():
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                responses.append(value)
        healthy = next((value for value in responses if value.get("type") == "health" and value.get("ok") is True), None)
        if code or not healthy or not isinstance(healthy.get("result"), dict):
            raise RuntimeFailure("acp", "dsh 未通过 ACP 初始化", "检查安装是否完整；此检查未发送模型请求。")
    return {"ok": True, "code": "ready", "message": "dsh 可用", "hint": "已完成版本检查和 ACP 初始化，未发送模型请求。",
            "path": str(entry), "version": version, "source": source}


def check_dsh(configured="", runtime_root=None, *, bridge=None, npm_config=None, cancelled=None):
    found = discover_dsh(configured, runtime_root)
    return _check_entry(Path(found["path"]), found["source"], bridge=bridge,
                        npm_config=npm_config, cancelled=cancelled)


def _remove_owned(path, root):
    path, root = filesystem_path(path).resolve(), filesystem_path(root).resolve()
    if path.parent != root:
        raise ValueError("dsh cleanup target is outside its runtime directory")
    if path.exists():
        shutil.rmtree(path)


def install_dsh(runtime_root, *, npm_config=None, bridge=None, progress=None, cancelled=None):
    """Stage the pinned official package, probe it, then publish its directory.

    npm retains the application's existing userconfig, CA and proxy settings.
    Only the package registry is fixed to the official npm registry. Progress is
    stage progress, not a fabricated network byte counter.
    """
    root = ordinary_path(runtime_root).resolve()
    filesystem_path(root).mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".dsh-install-", dir=filesystem_path(root)))
    stage = ordinary_path(stage)
    final = root / RELEASE_NAME
    backup = root / (".dsh-previous-" + uuid.uuid4().hex)
    notify = progress or (lambda value: None)
    try:
        if cancelled and cancelled():
            raise InterruptedError("已取消")
        notify({"progress": .05, "message": "正在准备 dsh 下载"})
        environment = npm_environment(npm_config or {})
        for key in list(environment):
            if key.lower() in ("npm_config_registry", "npm_config_audit", "npm_config_fund"):
                del environment[key]
        environment.update(npm_config_registry=OFFICIAL_REGISTRY, npm_config_audit="false",
                           npm_config_fund="false", DO_NOT_TRACK="1", DSH_TELEMETRY_DISABLED="1")
        from .update_proxy import system_proxy
        proxy = system_proxy(OFFICIAL_REGISTRY)
        if proxy:
            environment["npm_config_https_proxy"] = proxy
            environment["npm_config_proxy"] = proxy
        notify({"progress": .15, "message": "正在从官方 npm 下载 dsh " + PINNED_VERSION})
        code, _ = _run([*npm_command(), "install", "--prefix", str(stage), "--registry", OFFICIAL_REGISTRY,
                       "--no-audit", "--no-fund", "--no-update-notifier", "--save-exact", PACKAGE + "@" + PINNED_VERSION],
                      env=environment, cwd=stage, cancelled=cancelled, timeout=600)
        if code:
            raise RuntimeFailure("download", "dsh 下载失败", "检查网络、代理或 npm CA 设置后重试；原有安装已保留。")
        notify({"progress": .8, "message": "正在检查版本和 ACP 初始化"})
        entry = stage / "node_modules" / PACKAGE / "lib/bin.js"
        if not filesystem_path(entry).is_file():
            raise RuntimeFailure("download", "下载内容缺少 dsh", "重试下载；原有安装已保留。")
        result = _check_entry(entry, "managed", bridge=bridge, npm_config=npm_config, cancelled=cancelled)
        if result["version"] != PINNED_VERSION:
            raise RuntimeFailure("version", "下载版本与固定版本不符", "重试下载；原有安装已保留。")
        if cancelled and cancelled():
            raise InterruptedError("已取消")
        notify({"progress": .95, "message": "正在保存 dsh 安装"})
        had_previous = filesystem_path(final).exists()
        if had_previous:
            os.replace(filesystem_path(final), filesystem_path(backup))
        try:
            os.replace(filesystem_path(stage), filesystem_path(final))
        except BaseException:
            if had_previous:
                os.replace(filesystem_path(backup), filesystem_path(final))
            raise
        result.update(path=str(final / "node_modules" / PACKAGE / "lib/bin.js"), message="dsh 下载完成")
        if had_previous:
            try:
                _remove_owned(backup, root)
            except OSError:
                # A Windows scanner can temporarily hold old files. The new
                # working installation should still be returned to the user.
                pass
        notify({"progress": 1., "message": result["message"]})
        return result
    finally:
        _remove_owned(stage, root)


class DshRuntimeService(QObject):
    changed = Signal()
    configChanged = Signal()
    finished = Signal("QVariantMap")
    _event = Signal(object)
    _done = Signal(object)

    def __init__(self, runtime_root, config=None, save_config=None, parent=None, *, bridge=None, npm_config=None):
        super().__init__(parent)
        self.runtime_root = Path(runtime_root)
        self.config = config if config is not None else {}
        self._save_config = save_config
        self._bridge = bridge
        self._npm_config = npm_config if npm_config is not None else {}
        self._busy = self._ready = self._failed = False
        self._status, self._hint = "尚未检查 dsh", "选择安装路径，或下载官方版本。"
        self._version = self._resolved_path = ""
        self._progress = 0.
        self._cancelled = threading.Event()
        self._event.connect(self._apply_progress)
        self._done.connect(self._complete)

    @Property(str, notify=changed)
    def path(self): return str(self.config.get("dshPath", ""))

    @Property(bool, notify=changed)
    def busy(self): return self._busy

    @Property(bool, notify=changed)
    def ready(self): return self._ready

    # Display only: the last check or download ended in an error (not a cancel).
    @Property(bool, notify=changed)
    def failed(self): return self._failed

    @Property(str, notify=changed)
    def status(self): return self._status

    @Property(str, notify=changed)
    def hint(self): return self._hint

    @Property(str, notify=changed)
    def version(self): return self._version

    @Property(str, notify=changed)
    def resolvedPath(self): return self._resolved_path

    @Property(float, notify=changed)
    def progress(self): return self._progress

    @Slot(str)
    def setPath(self, value):
        if self._busy: return
        value = value.strip().strip('"')
        if value == self.path: return
        self.config["dshPath"] = value
        self._ready, self._failed, self._version, self._resolved_path = False, False, "", ""
        self._status, self._hint = "路径已更改，请检查", "检查通过后即可使用。"
        if self._save_config: self._save_config()
        self.configChanged.emit()
        self.changed.emit()

    @Slot()
    def check(self): self._start(False)

    @Slot()
    def download(self): self._start(True)

    @Slot()
    def cancel(self):
        if self._busy:
            self._cancelled.set()
            self._status = "正在取消"
            self.changed.emit()

    def _start(self, download):
        if self._busy: return
        self._cancelled.clear()
        self._busy, self._ready, self._failed, self._progress = True, False, False, 0.
        self._status, self._hint = "正在下载 dsh" if download else "正在检查 dsh", ""
        configured, npm_config = self.path, dict(self._npm_config)
        self.changed.emit()
        def run():
            try:
                options = dict(bridge=self._bridge, npm_config=npm_config, cancelled=self._cancelled.is_set)
                result = (install_dsh(self.runtime_root, progress=self._event.emit, **options) if download
                          else check_dsh(configured, self.runtime_root, **options))
                result["downloaded"] = download
            except InterruptedError:
                result = {"ok": False, "code": "cancelled", "message": "已取消", "hint": "原有安装已保留。"}
            except RuntimeFailure as error:
                result = {"ok": False, "code": error.code, "message": str(error), "hint": error.hint}
            except Exception:
                result = {"ok": False, "code": "failed", "message": "dsh 操作失败", "hint": "检查 Node、安装路径和网络后重试；原有安装已保留。"}
            self._done.emit(result)
        threading.Thread(target=run, name="umeko-dsh-runtime", daemon=True).start()

    @Slot(object)
    def _apply_progress(self, value):
        self._progress = float(value.get("progress", self._progress))
        if not self._cancelled.is_set(): self._status = value.get("message", self._status)
        self.changed.emit()

    @Slot(object)
    def _complete(self, result):
        self._busy, self._ready = False, bool(result.get("ok"))
        self._failed = not self._ready and result.get("code") != "cancelled"
        self._status, self._hint = result["message"], result.get("hint", "")
        if self._ready:
            self._resolved_path, self._version, self._progress = result["path"], result["version"], 1.
            if result.get("downloaded"):
                # Managed installs follow the application's runtime directory;
                # only an explicitly selected external runtime needs a path.
                self.config["dshPath"] = ""
                if self._save_config: self._save_config()
                self.configChanged.emit()
        self.changed.emit()
        self.finished.emit(result)
