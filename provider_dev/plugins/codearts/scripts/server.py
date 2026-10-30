"""One plugin-owned CodeArts HTTP process and a shared three-request FIFO.

Only this process receives the account's AK/SK. Control responses contain the
local server's random Basic credentials, never upstream credentials or output.
The private application gateway supplies authentication for ``handle``.
"""

from __future__ import annotations

import base64
from collections import deque
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import threading
import time
import urllib.request

try:
    from .account import _SECRET_NAMES
    from .i18n import tr
except ImportError:
    from account import _SECRET_NAMES
    from i18n import tr


_CONFIG = {
    "tools": {"*": False},
    "permission": {"*": "deny"},
    "snapshot": False,
    "agent": {
        f"umeko{slot}": {
            "mode": "primary",
            "description": "Umeko Pi tool bridge",
            "permission": {"*": "deny", f"pi{slot}_*": "allow"},
            "tools": {"*": False, f"pi{slot}_*": True},
        }
        for slot in range(3)
    },
}
_NOT_CONNECTED = "请先导入 CodeArts 凭据并完成连接。"
_START_FAILED = "CodeArts 本地服务启动失败，请检查 CLI 安装后重试。"
_CLOSED = "CodeArts 本地服务已关闭。"
_CANCELLED = "CodeArts 请求已取消。"


class CodeartsServer:
    """Thread-safe control handler, shared by every Pi session and subagent.

    ``launcher`` is Popen-compatible; ``request`` receives a health URL and
    keyword username/password/timeout and returns whether the service is ready.
    Neither hook is needed in normal use. Queued acquire calls block their own
    HTTP worker, so a separate worker can cancel them by caller-supplied ID.
    """

    def __init__(self, account, profile_dir, launcher=None, request=None, progress=None,
                 *, ready_timeout=30.0, queue_timeout=300.0, language="zh"):
        self.account = account
        self.language = language
        self.profile_dir = Path(profile_dir).resolve() / "codearts-server"
        self._launcher = launcher or subprocess.Popen
        self._request = request or self._health_request
        self._progress = progress or (lambda message: None)
        self._ready_timeout = ready_timeout
        self._queue_timeout = queue_timeout
        self._lifecycle = threading.Lock()
        self._condition = threading.Condition()
        self._closed = threading.Event()
        self._process = None
        self._processes = set()
        self._connection = None
        self._queue = deque()
        self._leases = {}
        self._lease_slots = {}
        self._requests = {}
        self._cancelled = set()

    @staticmethod
    def _health_request(url, *, username, password, timeout):
        basic = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        request = urllib.request.Request(url, headers={"Authorization": "Basic " + basic})
        # Do not route loopback health checks through system proxies.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=timeout) as response:
            payload = json.load(response)
        return isinstance(payload, dict) and payload.get("healthy") is True

    def _message(self, message):
        try:
            self._progress(self._text(message))
        except Exception:
            pass

    def _text(self, message):
        keys = {
            _NOT_CONNECTED: "server_not_connected", _START_FAILED: "server_start_failed",
            _CLOSED: "server_closed", _CANCELLED: "server_cancelled",
            "正在启动 CodeArts 本地服务…": "server_starting",
            "CodeArts 本地服务已就绪。": "server_started",
            "CodeArts 请求标识无效。": "server_invalid_id",
            "CodeArts 请求标识已使用。": "server_duplicate_id",
            "等待 CodeArts 并发名额超时，请重试。": "server_queue_timeout",
            "CodeArts 控制请求无效。": "server_invalid_request",
            "请指定要取消的 CodeArts 请求。": "server_cancel_target",
            "不支持的 CodeArts 控制操作。": "server_unsupported",
        }
        return tr(self.language, keys[message])

    @staticmethod
    def _port():
        while True:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            if port != 24894:
                return port

    def _environment(self, credentials, username, password):
        root = self.profile_dir
        env = {key: value for key, value in os.environ.items() if key.upper() not in _SECRET_NAMES}
        # Public settings from the official China codearts.cmd. Launch its EXE
        # directly: that .cmd unconditionally resets KERNEL paths to user-global.
        env.update({
            "package_tag": "undefined",
            "OMO_SEND_ANONYMOUS_TELEMETRY": "0", "SCENARIO": "codeartsdoer",
            "OPENCODE_CHANNEL": "latest", "OPENCODE_MODE": "tui", "PLUGIN_ENV": "hc",
            "NODE_TLS_REJECT_UNAUTHORIZED": "0", "OPENCODE_DISABLE_MODELS_FETCH": "1",
            "OPENCODE_DISABLE_AUTOUPDATE": "true", "OPENCODE_ALWAYS_NOTIFY_UPDATE": "false",
            "CODEARTS_DISABLE_AUTO_UPDATE": "true", "KERNEL_ACP": "",
            # The fork otherwise hides MCP schemas behind its own tool search.
            # Pi owns discovery and already supplies the current tool set.
            "ENABLE_TOOL_LAZY_LOADING": "false",
            "KERNEL_CONFIG_DIR": str(root / "config"), "KERNEL_DATA_DIR": str(root / "data"),
            "KERNEL_STATE_DIR": str(root / "state"),
            "OPENCODE_CONFIG": str(root / "config" / "codearts_cli.json"),
            "OPENCODE_CONFIG_FILE": "codearts_cli.json,codearts_cli.jsonc",
            "OPENCODE_CONFIG_CONTENT": json.dumps(_CONFIG),
            "OPENCODE_SERVER_USERNAME": username, "OPENCODE_SERVER_PASSWORD": password,
            "CODEARTS_SERVER_USERNAME": username, "CODEARTS_SERVER_PASSWORD": password,
            "XDG_CONFIG_HOME": str(root / "config"), "XDG_DATA_HOME": str(root / "data"),
            "XDG_STATE_HOME": str(root / "state"), "XDG_CACHE_HOME": str(root / "cache"),
            "QT_QPA_PLATFORM": "offscreen", "BROWSER": "false",
            "CODEARTS_CLI_AK": credentials[0], "CODEARTS_CLI_SK": credentials[1],
        })
        return env

    def prepare_directory(self):
        """Prepare this owned workspace with folder trust still enabled."""
        for name in ("config", "data", "state", "cache", "work"):
            (self.profile_dir / name).mkdir(parents=True, exist_ok=True)
        (self.profile_dir / "config" / "codearts_cli.json").write_text(
            json.dumps(_CONFIG), encoding="utf-8")
        work = self.profile_dir / "work"
        (self.profile_dir / "data" / "settings.json").write_text(json.dumps({
            "security": {"folderTrust": {"enabled": True},
                         "trustedFolders": [str(work.resolve())]},
        }), encoding="utf-8")
        return work

    def _stop_process(self, process):
        """Kill only a process this manager created, including its children."""
        if process not in self._processes:
            return
        try:
            if process.poll() is None:
                if os.name == "nt" and self._launcher is subprocess.Popen:
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, check=False,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                else:
                    process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        except Exception:
            # A concurrently exiting owned child must not leak an OS exception.
            try:
                process.kill()
            except Exception:
                pass
        finally:
            self._processes.discard(process)

    def connection(self):
        with self._lifecycle:
            if self._closed.is_set():
                raise RuntimeError(self._text(_CLOSED))
            if self._process is not None and self._process.poll() is None:
                return dict(self._connection)
            if self._process is not None:
                self._stop_process(self._process)
                self._process = self._connection = None
            try:
                credentials = self.account._credentials()
            except Exception:
                credentials = None
            if not credentials:
                raise RuntimeError(self._text(_NOT_CONNECTED))
            process = None
            try:
                if not self.account._ensure_cli():
                    raise RuntimeError(self._text(_START_FAILED))
                cli = Path(self.account._cli)
                executable = cli if cli.suffix.lower() == ".exe" or os.name != "nt" else cli.parent / "bin" / "codearts.exe"
                if not executable.is_file():
                    raise RuntimeError(self._text(_START_FAILED))
                # The CodeArts fork checks folder trust before starting serve.
                # Its store lives under KERNEL_DATA_DIR, separate from config.
                # Trust only this owned service workspace; keep the check enabled.
                work = self.prepare_directory()
                port = self._port()
                username, password = "umeko-" + secrets.token_urlsafe(12), secrets.token_urlsafe(32)
                connection = {"url": f"http://127.0.0.1:{port}", "username": username, "password": password,
                              "directory": str(self.profile_dir / "work")}
                self._message("正在启动 CodeArts 本地服务…")
                process = self._launcher(
                    [str(executable), "serve", "--hostname", "127.0.0.1", "--port", str(port)],
                    env=self._environment(credentials, username, password),
                    cwd=str(work), stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self._processes.add(process)
                deadline = time.monotonic() + self._ready_timeout
                while not self._closed.is_set() and process.poll() is None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    try:
                        ready = self._request(connection["url"] + "/global/health", username=username,
                                              password=password, timeout=min(1.0, remaining))
                    except Exception:
                        ready = False
                    if ready and not self._closed.is_set() and process.poll() is None:
                        self._process, self._connection = process, connection
                        self._message("CodeArts 本地服务已就绪。")
                        return dict(connection)
                    self._closed.wait(min(0.1, max(0, deadline - time.monotonic())))
            except Exception:
                pass
            if process is not None:
                self._stop_process(process)
            raise RuntimeError(self._text(_CLOSED if self._closed.is_set() else _START_FAILED))

    def _identifier(self, body, name, required=False):
        value = body.get(name)
        if value is None and not required:
            return None
        if not isinstance(value, str) or not value or len(value) > 200:
            raise ValueError(self._text("CodeArts 请求标识无效。"))
        return value

    def _acquire(self, request_id):
        deadline = time.monotonic() + self._queue_timeout
        with self._condition:
            if self._closed.is_set():
                raise RuntimeError(self._text(_CLOSED))
            if request_id in self._cancelled:
                self._cancelled.discard(request_id)
                raise RuntimeError(self._text(_CANCELLED))
            if request_id in self._requests or request_id in self._queue:
                raise ValueError(self._text("CodeArts 请求标识已使用。"))
            self._queue.append(request_id)
            try:
                while True:
                    if self._closed.is_set():
                        raise RuntimeError(self._text(_CLOSED))
                    if request_id in self._cancelled:
                        self._cancelled.discard(request_id)
                        raise RuntimeError(self._text(_CANCELLED))
                    if self._queue[0] == request_id and len(self._leases) < 3:
                        self._queue.popleft()
                        lease_id = secrets.token_urlsafe(24)
                        slot = next(slot for slot in range(3) if slot not in self._lease_slots.values())
                        self._leases[lease_id] = request_id
                        self._lease_slots[lease_id] = slot
                        self._requests[request_id] = lease_id
                        self._condition.notify_all()
                        return {"leaseId": lease_id, "slot": slot}
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise RuntimeError(self._text("等待 CodeArts 并发名额超时，请重试。"))
                    self._condition.wait(remaining)
            finally:
                if request_id in self._queue:
                    self._queue.remove(request_id)
                    self._condition.notify_all()

    def _release(self, lease_id):
        with self._condition:
            request_id = self._leases.pop(lease_id, None)
            self._lease_slots.pop(lease_id, None)
            if request_id is not None:
                self._requests.pop(request_id, None)
            self._condition.notify_all()
            return {"released": request_id is not None}

    def _cancel(self, request_id, lease_id):
        with self._condition:
            if request_id:
                lease_id = self._requests.get(request_id, lease_id)
                self._cancelled.add(request_id)
            if lease_id:
                active_id = self._leases.pop(lease_id, None)
                self._lease_slots.pop(lease_id, None)
                if active_id:
                    self._requests.pop(active_id, None)
            self._condition.notify_all()
            return {"cancelled": True}

    def handle(self, body):
        """Control protocol; all errors are fixed Chinese text, never CLI output."""
        if not isinstance(body, dict):
            raise ValueError(self._text("CodeArts 控制请求无效。"))
        action = body.get("action")
        if action == "connection":
            return self.connection()
        if action == "acquire":
            return self._acquire(self._identifier(body, "requestId", required=True))
        if action == "release":
            return self._release(self._identifier(body, "leaseId", required=True))
        if action == "cancel":
            request_id = self._identifier(body, "requestId")
            lease_id = self._identifier(body, "leaseId")
            if not request_id and not lease_id:
                raise ValueError(self._text("请指定要取消的 CodeArts 请求。"))
            return self._cancel(request_id, lease_id)
        raise ValueError(self._text("不支持的 CodeArts 控制操作。"))

    def close(self):
        self._closed.set()
        with self._condition:
            self._leases.clear()
            self._lease_slots.clear()
            self._requests.clear()
            self._condition.notify_all()
        with self._lifecycle:
            for process in list(self._processes):
                self._stop_process(process)
            self._process = self._connection = None
