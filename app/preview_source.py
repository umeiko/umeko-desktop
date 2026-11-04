"""Opt-in source preview checkout; independent from application settings/data."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from typing import Callable

from .preview_network import PreviewNetwork, network_failure

OFFICIAL_REPOSITORY = "https://github.com/umeiko/umeko-desktop.git"
MINIMUM_FREE_BYTES = 2 * 1024 ** 3


class PreviewError(RuntimeError):
    def __init__(self, message: str, detail: str = "", category: str = "", limitation: str = ""):
        self.message = message
        self.detail = _redact(detail)[-16000:]
        self.category = category
        self.limitation = limitation
        super().__init__(message + ("\n" + self.detail if self.detail else ""))


def _redact(value: str) -> str:
    return re.sub(r"(https?://)[^\s/@]+(?::[^\s/@]*)?@", r"\1[redacted]@", value)


class PreviewSource:
    def __init__(self, profile: Path, release_executable: Path | None,
                 environment: dict | None = None, progress: Callable | None = None,
                 cancelled: Callable | None = None, upstream: str = OFFICIAL_REPOSITORY):
        # The alternate upstream is a test seam, never an arbitrary network URL.
        if upstream != OFFICIAL_REPOSITORY and not Path(upstream).is_dir():
            raise ValueError("Only a local repository may replace the official test upstream")
        self.profile = Path(profile).resolve()
        self.checkout = self.profile / "preview" / "source"
        self.state_file = self.profile / "preview-channel.json"
        self.release_executable = Path(release_executable).resolve() if release_executable else None
        self.environment = dict(os.environ if environment is None else environment)
        self.progress = progress or (lambda event: None)
        self.cancelled = cancelled or (lambda: False)
        self.upstream = upstream
        self.system_python: str | None = None
        self._network = None

    def read_state(self) -> dict:
        state = {"channel": "release", "releaseExecutable": "", "dependencyPending": False}
        if self.state_file.exists():
            try:
                value = json.loads(self.state_file.read_text(encoding="utf-8"))
                if not isinstance(value, dict):
                    raise ValueError("Expected an object")
                state.update(value)
            except (OSError, ValueError) as exc:
                raise PreviewError("预览状态文件无法读取", str(exc)) from exc
        if state["channel"] not in ("release", "preview"):
            raise PreviewError("预览状态文件无效")
        return state

    def _save(self, **values) -> dict:
        state = self.read_state()
        state.update(values)
        if self.release_executable:
            state["releaseExecutable"] = str(self.release_executable)
        self.profile.mkdir(parents=True, exist_ok=True)
        temporary = self.state_file.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.state_file)
        return state

    def _emit(self, state: str, message: str, detail: str = ""):
        self.progress({"state": state, "message": message, "detail": _redact(detail)})

    def _run(self, args: list[str], cwd: Path | None = None, timeout: int = 120,
             complete: bool = False, network: bool = False, environment: dict | None = None) -> str:
        if self.cancelled():
            raise PreviewError("操作已取消")
        env = dict(self.environment if environment is None else environment)
        if environment is None and self._network is not None:
            env = self._network.apply(env)
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GCM_INTERACTIVE"] = "Never"
        # Disk-backed output avoids accumulating unbounded installation logs in RAM.
        with tempfile.TemporaryFile() as output:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            try:
                process = subprocess.Popen(args, cwd=cwd, env=env, stdout=output,
                                           stderr=subprocess.STDOUT, creationflags=flags,
                                           start_new_session=os.name != "nt")
            except OSError as exc:
                if network:
                    raise self._network_error(str(exc)) from exc
                raise PreviewError("命令无法启动", str(exc)) from exc
            started = time.monotonic()
            failure = ""
            while process.poll() is None:
                if self.cancelled():
                    failure = "操作已取消"
                elif time.monotonic() - started > timeout:
                    failure = "命令执行超时"
                if failure:
                    self._terminate(process)
                    break
                time.sleep(0.1)
            process.wait()
            size = output.seek(0, 2)
            if complete and size > 65536:
                raise PreviewError("命令输出过多，无法安全继续", "Git output exceeds 64 KiB; no partial data was used")
            output.seek(max(0, size - 65536))
            detail = output.read().decode("utf-8", errors="replace")
            if failure:
                if network and failure != "操作已取消":
                    raise self._network_error("ETIMEDOUT" if failure == "命令执行超时" else detail)
                raise PreviewError(failure, detail)
            if process.returncode:
                if network:
                    raise self._network_error(detail)
                raise PreviewError("命令执行失败", detail)
            return detail.strip()

    def _network_error(self, detail):
        try:
            category = self._network.classify(detail) if self._network else "other"
        except (OSError, ValueError, PreviewError, RuntimeError):
            category = "other"
        failure = network_failure(category)
        return PreviewError("预览版网络步骤失败。", failure["detail"], category)

    def _prepare_network(self):
        if self._network is not None:
            self._network.close()
        self._network = PreviewNetwork(self.environment, lambda command: self._run(
            command, timeout=120, environment=self.environment))
        try:
            return self._network.probe()
        except (OSError, ValueError, PreviewError, RuntimeError):
            return {"ok": False, "category": "other"}

    def _ensure_network(self):
        if self.upstream != OFFICIAL_REPOSITORY:
            return
        result = self._network.result if self._network else self._prepare_network()
        if not result or not result["ok"]:
            failure = network_failure((result or {}).get("category", "other"), (result or {}).get("attempts", []))
            raise PreviewError("预览版网络步骤失败。", failure["detail"], failure["category"], failure.get("limitation", ""))

    @staticmethod
    def _terminate(process):
        if os.name == "nt":
            # Exact PID tree only; never terminate applications by executable name.
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
        else:
            import signal
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def _which(self, name: str) -> str | None:
        return shutil.which(name, path=self.environment.get("PATH", ""))

    def _select_python(self) -> str:
        failures = []
        seen = set()
        stored = self.read_state().get("systemPython")
        candidates = [stored] + [self._which(name) for name in ("python3", "python", "py")]
        for candidate in candidates:
            if not candidate or candidate in seen or "WindowsApps" in candidate:
                continue
            seen.add(candidate)
            try:
                actual = self._run([candidate, "-c", "import sys,venv,ensurepip; assert sys.version_info >= (3,10); print(sys.executable)"])
                if actual:
                    self.system_python = actual.splitlines()[-1]
                    return self.system_python
            except PreviewError as exc:
                failures.append(str(exc))
        raise PreviewError("未找到系统 Python 3.10+", "\n".join(failures))

    def preflight(self) -> dict:
        """Probe tools/disk and updater routes using a temporary CA bundle."""
        details = []
        release = self.release_executable or Path(self.read_state().get('releaseExecutable') or '')
        release_available = release.is_file()
        details.append({'name': '保留的正式版', 'ready': release_available, 'command': [],
                        'detail': '正式版启动程序可用' if release_available else '找不到正式版程序，无法切回'})
        details.append({'name': '网络与代理', 'ready': True, 'command': [],
                        'detail': '按更新器策略尝试系统代理和直连，后续下载沿用成功路径及系统信任证书；供应商代理不适用于此操作。'})

        def probe(label, command, validate=lambda value: True):
            try:
                value = self._run(command)
                if not validate(value):
                    raise PreviewError("版本不符合要求", value)
                details.append({"name": label, "ready": True, "command": command, "detail": value})
                return value
            except (PreviewError, ValueError, AttributeError) as exc:
                details.append({"name": label, "ready": False, "command": command, "detail": str(exc)})
                return None

        git = self._which("git")
        probe("Git", [git or "git", "--version"])
        try:
            actual = self._select_python()
            details.append({"name": "Python 3.10+ / venv", "ready": True,
                            "command": [actual, "-c", "import sys,venv,ensurepip; assert sys.version_info >= (3,10); print(sys.executable)"], "detail": actual})
        except PreviewError as exc:
            details.append({"name": "Python 3.10+ / venv", "ready": False,
                            "command": ["python", "-c", "import venv,ensurepip"], "detail": str(exc)})
        probe("Node.js 22.19+", [self._which("node") or "node", "--version"],
              lambda value: tuple(map(int, re.match(r"v?(\d+)\.(\d+)\.(\d+)", value).groups())) >= (22, 19, 0))
        npm = self._which("npm.cmd" if os.name == "nt" else "npm")
        # npm.cmd is invoked through the same platform setup shell on Windows.
        shell = self._setup_shell()
        npm_command = [shell, "-NoProfile", "-NonInteractive", "-Command", "npm.cmd --version"] if os.name == "nt" else [npm or "npm", "--version"]
        probe("npm", npm_command)
        probe("安装脚本 Shell", [shell, "-NoProfile", "-NonInteractive", "-Command", "$PSVersionTable.PSVersion.ToString()"] if os.name == "nt" else [shell, "--version"])
        ancestor = self.profile
        while not ancestor.exists():
            ancestor = ancestor.parent
        free = shutil.disk_usage(ancestor).free
        details.append({"name": "磁盘空间 (至少 2 GiB)", "ready": free >= MINIMUM_FREE_BYTES,
                        "command": [], "detail": str(free) + " bytes free"})
        if self.upstream == OFFICIAL_REPOSITORY:
            result = self._prepare_network()
            check = {"name": "官方 main 分支连接", "ready": result["ok"], "command": []}
            if result["ok"]:
                check.update(detail="网络连接成功：" + result["route"], route=result["route"])
            else:
                check.update(network_failure(result.get("category", "other"), result.get("attempts", [])))
            check["attempts"] = result.get("attempts", [])
            details.append(check)
        else:
            probe("官方 main 分支连接", [git or "git", "ls-remote", "--exit-code", self.upstream, "refs/heads/main"], bool)
        return {"ready": all(item["ready"] for item in details), "details": details,
                "detail": "\n".join(item["name"] + ": " + item["detail"] for item in details)}

    def _setup_shell(self) -> str:
        if os.name == "nt":
            return self._which("powershell.exe") or self._which("pwsh.exe") or "powershell.exe"
        return self._which("bash") or "bash"

    @property
    def python(self) -> Path:
        return self.checkout / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")

    def _setup(self):
        self._ensure_network()
        self._emit("setup", "正在安装预览版依赖")
        if not self.system_python:
            self._select_python()
        # setup.ps1 calls `python`; provide an actual Python, ahead of aliases.
        self.environment["PATH"] = str(Path(self.system_python).parent) + os.pathsep + self.environment.get("PATH", "")
        self._save(systemPython=self.system_python)
        if os.name == "nt":
            command = [self._setup_shell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(self.checkout / "setup.ps1")]
        else:
            command = [self._setup_shell(), str(self.checkout / "setup.sh")]
        self._run(command, self.checkout, timeout=1800, network=self.upstream == OFFICIAL_REPOSITORY)
        self._verify()

    def _verify(self):
        if not self.python.is_file():
            raise PreviewError("预览版 Python 环境未创建")
        self._run([str(self.python), "-c", "import PySide6.QtCore, PySide6.QtGui, PySide6.QtWidgets"], self.checkout)

    def _git(self, *args: str) -> str:
        network = args[0] in ("fetch", "pull") and self.upstream == OFFICIAL_REPOSITORY
        if network:
            self._ensure_network()
        return self._run(["git", "-C", str(self.checkout), *args], complete=True, network=network)

    def _origin(self):
        effective = self._git("remote", "get-url", "--all", "origin").splitlines()
        urls = self._git("config", "--get-all", "remote.origin.url").splitlines()
        # Push URLs are not used here, but reject alternate origins rather than hiding them.
        configuration = self._git("config", "--get-regexp", r"^remote\.origin\.")
        push_urls = [line.split(" ", 1)[1] for line in configuration.splitlines() if line.startswith("remote.origin.pushurl ")]
        if effective != [self.upstream] or urls != [self.upstream] or (push_urls and push_urls != [self.upstream]):
            raise PreviewError("预览仓库来源不是官方地址", "\n".join(effective + urls + push_urls))

    def _managed(self):
        if not self.read_state().get("previewManaged") or not (self.checkout / ".git").is_dir():
            raise PreviewError("该目录不是应用管理的预览仓库", str(self.checkout))
        self._origin()

    def _clean_tracked(self):
        dirty = self._git("status", "--porcelain", "--untracked-files=no")
        if dirty:
            raise PreviewError("预览仓库有本地修改，请先保存或处理", dirty)

    def _branch(self):
        branch = self._git("rev-parse", "--abbrev-ref", "HEAD")
        if branch != "main":
            raise PreviewError("预览仓库必须位于 main 分支", branch)

    def switch_to_preview(self) -> dict:
        preflight = self.preflight()
        if not preflight["ready"]:
            failed = [item for item in preflight["details"] if not item["ready"]]
            category = next((item["category"] for item in failed if item.get("category")), "")
            limitation = next((item["limitation"] for item in failed if item.get("limitation")), "")
            raise PreviewError("预览版运行条件不满足", "\n".join(item["name"] + ": " + item["detail"] for item in failed), category, limitation)
        if self.checkout.exists():
            self._managed()
            self._branch()
            self._clean_tracked()
        else:
            self.checkout.parent.mkdir(parents=True, exist_ok=True)
            self._emit("clone", "正在下载官方 main 分支")
            staging = Path(tempfile.mkdtemp(prefix="source-install-", dir=self.checkout.parent))
            try:
                self._run(["git", "clone", "--branch", "main", "--single-branch", self.upstream, str(staging)], timeout=600,
                          network=self.upstream == OFFICIAL_REPOSITORY)
                staging.rename(self.checkout)
            finally:
                if staging.exists():
                    self._remove_tree(staging)
            self._save(previewManaged=True, channel="release")
        self._save(channel="release", dependencyPending=True)
        self._setup()
        if self.cancelled():
            raise PreviewError("操作已取消")
        self._save(channel="preview", dependencyPending=False)
        return {"state": "restart-required", "message": "已切换到预览版，重启后生效", "channel": "preview", "checkout": str(self.checkout), "python": str(self.python)}

    @staticmethod
    def _dependency(path: str) -> bool:
        name = Path(path).name
        return (name.startswith("requirements") and name.endswith(".txt") or
                path in {"pyproject.toml", "runtime/package.json", "runtime/package-lock.json", "setup.ps1", "setup.sh", "prepare_runtime.py", "app/pi_runtime.py", "scripts/search-tools.json"} or
                path.startswith("runtime/") and ("compat" in path or name.startswith("package")) or
                path.startswith("scripts/") and (name.startswith("build-") or name.startswith("fetch-")))

    def _overwrites(self, base: str, target: str):
        incoming = self._git("diff", "--name-only", "--diff-filter=ACRT", "-z", base, target).split("\0")
        # Query only incoming files' top-level ancestors. Wholly untracked
        # installation trees collapse to one directory, including ignored paths.
        untracked = set()
        for ancestor in sorted({p.split("/", 1)[0] for p in incoming if p}):
            untracked.update(p.rstrip("/") for p in self._git(
                "ls-files", "--others", "--directory", "-z", "--", ":(literal)" + ancestor).split("\0") if p)
        conflicts = sorted(p for p in untracked if p and any(q and (p == q or p.startswith(q + "/") or q.startswith(p + "/")) for q in incoming))
        if conflicts:
            raise PreviewError("更新会覆盖未跟踪文件，请先保存或移动", "\n".join(conflicts))

    def _relation(self, base: str, target: str):
        counts = self._git("rev-list", "--left-right", "--count", base + "..." + target).split()
        if int(counts[0]):
            raise PreviewError("本地 main 已领先或分叉，无法安全更新", "ahead=" + counts[0] + " behind=" + counts[1])

    def check_update(self) -> dict:
        self._managed()
        self._branch()
        self._clean_tracked()
        base = self._git("rev-parse", "HEAD")
        self._emit("fetch", "正在检查官方 main 分支更新")
        self._git("fetch", "--no-tags", "origin", "main")
        target = self._git("rev-parse", "FETCH_HEAD")
        self._relation(base, target)
        self._overwrites(base, target)
        changed = [p for p in self._git("diff", "--name-only", "-z", base, target).split("\0") if p]
        dependencies = [p for p in changed if self._dependency(p)]
        pending = bool(self.read_state()["dependencyPending"])
        message = "依赖安装尚未完成，请重试" if pending else ("发现预览版更新" if base != target else "预览版已是最新版本")
        return {"state": "available" if base != target or pending else "current", "message": message, "base": base,
                "target": target, "summary": self._git("log", "--oneline", base + ".." + target),
                "changed": changed, "dependencies": dependencies, "dependencyPending": pending}

    def apply_update(self, plan: dict) -> dict:
        self._managed()
        self._branch()
        self._clean_tracked()
        base, target = plan["base"], plan["target"]
        if self._git("rev-parse", "HEAD") != base:
            raise PreviewError("预览仓库已变化，请重新检查更新")
        if not re.fullmatch(r"[0-9a-f]{40,64}", target):
            raise PreviewError("更新目标无效")
        self._relation(base, target)
        self._overwrites(base, target)
        changed = [p for p in self._git("diff", "--name-only", "-z", base, target).split("\0") if p]
        needs_setup = bool(self.read_state()["dependencyPending"]) or any(self._dependency(p) for p in changed)
        self._emit("update", "正在应用已确认的更新", base + ".." + target)
        if base != target:
            self._git("pull", "--ff-only", "--no-rebase", "origin", target)
        if needs_setup:
            self._save(dependencyPending=True)
            self._setup()
        else:
            self._verify()
        if self.cancelled():
            raise PreviewError("操作已取消")
        self._save(channel="preview", dependencyPending=False)
        return {"state": "restart-required", "message": "预览版更新完成，重启后生效", "channel": "preview", "checkout": str(self.checkout), "python": str(self.python)}

    def switch_to_release(self, remove_checkout: bool = False) -> dict:
        executable = self.release_executable or Path(self.read_state()["releaseExecutable"] or "")
        if not executable.is_file():
            raise PreviewError("找不到正式版程序，无法切回", str(executable))
        self.release_executable = executable.resolve()
        # Select the working release first, including when cleanup is refused.
        self._save(channel="release")
        if remove_checkout and self.checkout.exists():
            self._check_removal()
            if Path(sys.executable).resolve().is_relative_to(self.checkout.resolve()):
                self._save(removeCheckoutPending=True, cleanupParentPid=os.getpid())
            else:
                self._remove_tree(self.checkout)
                self._save(previewManaged=False, dependencyPending=False,
                           removeCheckoutPending=False, cleanupParentPid=None)
        return {"state": "restart-required", "message": "已切换到正式版，重启后生效", "channel": "release", "executable": str(executable)}

    def _check_removal(self):
        if self.checkout.is_symlink() or self.checkout.resolve() != self.profile / "preview" / "source":
            raise PreviewError("预览目录位置无效")
        self._managed()
        self._clean_tracked()
        untracked = self._git("ls-files", "--others", "--exclude-standard")
        # Ignored setup outputs belong to the installation; personal ignored files do not.
        owned = (".venv/", "runtime/node_modules/", "runtime/releases/", "runtime/downloads/",
                 "build/provider-resources/", "build/desktop-plugin-resources/",
                 "build/qt-sdk/", "build/input-method/", "__pycache__/", ".pytest_cache/")
        # Exclude install output in Git itself, so a large venv cannot crowd a
        # personal ignored path out of the bounded subprocess output buffer.
        exclusions = [":(exclude)" + path + "**" for path in owned]
        personal = [p for p in self._git("ls-files", "--others", "--ignored", "--exclude-standard", "-z", "--", ".",
                                       *exclusions, ":(exclude)**/__pycache__/**").split("\0") if p]
        if untracked or personal:
            raise PreviewError("预览仓库有未跟踪文件，已切回正式版但保留源码", untracked + "\n" + "\n".join(personal))

    def remove_retained_checkout(self) -> dict:
        """Called by the retained release after the source Python has exited."""
        if self.read_state()["channel"] != "release":
            raise PreviewError("请先切回正式版再删除预览源码")
        if self.checkout.exists():
            self._check_removal()
            if Path(sys.executable).resolve().is_relative_to(self.checkout.resolve()):
                raise PreviewError("预览版仍在运行，请从正式版删除源码")
            self._remove_tree(self.checkout)
        self._save(previewManaged=False, dependencyPending=False,
                   removeCheckoutPending=False, cleanupParentPid=None)
        return {"state": "removed", "message": "预览源码已删除", "channel": "release"}

    @staticmethod
    def _remove_tree(path: Path):
        # Git object files are read-only on Windows; only this owned tree is removed.
        def retry(function, filename, error):
            if not isinstance(error[1], PermissionError):
                raise error[1]
            os.chmod(filename, stat.S_IWRITE | stat.S_IREAD)
            function(filename)
        shutil.rmtree(path, onerror=retry)
