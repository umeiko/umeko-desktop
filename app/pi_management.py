"""Native extension administration and recoverable factory restoration."""
import copy
import json
import os
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl, QTimer
from PySide6.QtGui import QDesktopServices
from .pi_runtime import CREATE_NO_WINDOW, RELEASE_NAME, installed_version, node_executable, verify_runtime
from .pi_terminal import console_runtime, prepare_terminal, launch_terminal
from .pi_install import parse_install_command, install_package, remove_package
from .package_records import PackageRecords, timestamp
from .package_presentation import audit_presentation
from .npm_config import validate_npm_config, probe_npm, npm_environment
from .storage import DEFAULTS


def resource_command(release, cwd, agent_dir, agent, **action):
    environment = npm_environment(agent)
    environment["PI_OFFLINE"] = "1"
    environment.pop("NODE_OPTIONS", None)
    environment.pop("NODE_PATH", None)
    result = subprocess.run([node_executable(), str(release / "resources.mjs")],
        input=json.dumps({"cwd": str(cwd), "agentDir": str(agent_dir), "agent": agent, **action}),
        capture_output=True, text=True, encoding="utf-8", timeout=45, env=environment, creationflags=CREATE_NO_WINDOW)
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        raise RuntimeError("Pi 配置管理暂不可用，可尝试恢复出厂内核") from None
    if result.returncode or not payload.get("ok"):
        raise RuntimeError(payload.get("error", "Pi 配置读取失败"))
    return payload["update"] if action.get("action") == "check-update" else payload["extensions"]


def prepare_factory(root, directory, agent, workspace):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    backup = directory / "pi-backups" / stamp
    backup.mkdir(parents=True)
    old_dir = Path(agent.get("agentDir") or Path.home() / ".pi/agent")
    (backup / "restore.json").write_text(json.dumps({"agent": agent, "workspace": str(workspace)}, ensure_ascii=False, indent=2), encoding="utf-8")
    for source, name in ((old_dir / "settings.json", "personal-settings.json"),
                         (Path(workspace) / ".pi/settings.json", "project-settings.json"),
                         (directory / "kernels/active.json", "active.json")):
        if source.is_file(): shutil.copy2(source, backup / name)
    release = directory / "kernels" / ("factory-" + stamp)
    shutil.copytree(root / "runtime/releases" / RELEASE_NAME, release)
    verify_runtime(release, root / "runtime/bridge.mjs")
    fresh = directory / "pi-profiles" / stamp
    fresh.mkdir(parents=True)
    # Keep all original Pi directories, extension files and native sessions intact.
    return {"backup": str(backup), "release": str(release), "agentDir": str(fresh)}


class PiManagement(QObject):
    changed = Signal()
    operationFinished = Signal(str, object)

    def __init__(self, controller):
        super().__init__(controller)
        self.controller = controller
        self._busy, self._extensions, self._status, self._backup = False, [], "", ""
        self._install_state, self._install_message = "idle", ""
        self._npm_status = ""
        self._package_records = PackageRecords(controller.store.directory)
        self._marketplace_progress = {}
        self._extension_update = {}
        backups = controller.store.directory / "pi-backups"
        if backups.is_dir():
            saved = sorted(p for p in backups.iterdir() if p.is_dir() and (p / "restore.json").is_file())
            if saved: self._backup = str(saved[-1])
        controller.jobDone.connect(self._finished)
        self._visible_context = None
        self._scan_pending = False
        if hasattr(controller, "viewChanged"):
            self._visible_context = self._resource_key()
            controller.viewChanged.connect(self._sync_context)
            controller.changed.connect(self._sync_context)

    @Property(bool, notify=changed)
    def busy(self): return self._busy

    @Property("QVariantList", notify=changed)
    def extensions(self): return self._extensions

    @Property("QVariantList", notify=changed)
    def packages(self):
        # Adapted grouping/action model: pi-extmgr 0.4.2 InstalledPackage and
        # UnifiedItem in src/types/index.ts, src/ui/installed/items.ts, and
        # src/ui/installed/item-actions.ts. Desktop actions reuse Pi's native
        # enable/remove paths rather than copying its TUI implementation.
        groups = {}
        workspace = str(self.controller._view.workspace or self.controller.store.data.get("workspace", ""))
        for extension in self._extensions:
            source = extension.get("source", "")
            native_package = extension.get("origin") == "package" or source not in ("builtin", "local", "")
            key = (source, extension.get("scope")) if native_package else (extension["id"],)
            if key not in groups:
                details = self._package_records.metadata(source, extension["name"], extension.get("scope", ""), workspace)
                groups[key] = {**details, **extension, "extensions": [], "removable": native_package}
                if not groups[key].get("version"):
                    groups[key]["version"] = details["version"]
            if extension.get("resourceKind") != "package":
                groups[key]["extensions"].append(extension)
        return sorted(groups.values(), key=lambda row: (not bool(row["useCount"]), row["name"].casefold()))

    @Property("QVariantList", notify=changed)
    def manageablePackages(self):
        # Native discovery is scoped to the current workspace. Disabled local
        # extensions remain manageable (the user can enable them); built-ins
        # and group placeholders do not create a composer action.
        return [row for row in self.packages if row.get("source") != "builtin"
                and not row.get("path", "").startswith("builtin:")
                and (row.get("resourceKind") == "package" and row.get("packageRoot")
                     or any(extension.get("path") for extension in row["extensions"]))]

    @Property(bool, notify=changed)
    def hasManageableExtensions(self):
        return bool(self.manageablePackages)

    def _sync_context(self):
        if getattr(self.controller, "_closing", False): return
        key = self._resource_key()
        if key != self._visible_context:
            self._visible_context = key
            self._extensions = []
            self._marketplace_progress = {}
            self._scan_pending = True
            self.changed.emit()
        if self._scan_pending and not self._busy and not self.controller.kernelBusy:
            self.scan()

    @Property(str, notify=changed)
    def installPermission(self):
        value = self.controller.store.data["agent"].get("installPermission", "ask")
        return value if value in ("ask", "automatic") else "ask"

    @Property("QVariantMap", notify=changed)
    def marketplaceProgress(self): return self._marketplace_progress

    @Slot("QVariant", result="QVariantMap")
    def auditPresentation(self, value):
        return audit_presentation(value.toVariant() if hasattr(value, "toVariant") else value)

    @Slot(str, result=bool)
    def setInstallPermission(self, value):
        if value not in ("ask", "automatic"):
            return False
        c = self.controller
        previous = c.store.data["agent"].get("installPermission", "ask")
        c.store.data["agent"]["installPermission"] = value
        try:
            c.store.save()
        except OSError as exc:
            c.store.data["agent"]["installPermission"] = previous
            c.toast.emit(str(exc)); return False
        for record in c._pool.records.values():
            c._pool.write(record, {"type": "install_permission", "value": value})
        c.changed.emit(); self.changed.emit()
        return True

    def handleRuntimeEvent(self, event, record):
        kind = event.get("type")
        if kind not in ("package_install", "package_usage", "marketplace_progress"):
            return False
        try:
            if kind == "package_install":
                self._package_records.installed({**event, "session": event.get("session") or record.id,
                    "workspace": record.workspace, "scope": event.get("scope", "global")})
                self.scan()
            elif kind == "package_usage":
                self._package_records.used(event)
            else:
                self._marketplace_progress = {key: str(event.get(key, ""))[:2000]
                    for key in ("operation", "package", "state", "message")}
        except (OSError, ValueError) as exc:
            self.controller.toast.emit("扩展记录保存失败：" + str(exc))
        self.changed.emit()
        return True

    @Property(str, notify=changed)
    def status(self): return self._status

    @Property(str, notify=changed)
    def backupPath(self): return self._backup

    @Property(str, notify=changed)
    def installState(self): return self._install_state

    @Property(str, notify=changed)
    def installMessage(self): return self._install_message

    @Property("QVariantMap", notify=changed)
    def npmConfig(self):
        agent = self.controller.store.data["agent"]
        return {key: agent.get(key, "") for key in ("npmRegistry", "npmUserconfig", "npmCafile")}

    @Property(str, notify=changed)
    def npmStatus(self): return self._npm_status

    @Property("QVariantMap", notify=changed)
    def extensionUpdate(self): return self._extension_update

    @Slot(str)
    def checkExtensionUpdate(self, extension_id):
        if self._busy or self.controller.kernelBusy: return
        context = self._context()
        self._extension_update = {"id": extension_id, "status": "checking", "message": "正在检查扩展更新…"}
        self._start("extension-check", "正在检查扩展更新…", lambda: resource_command(*context, action="check-update", id=extension_id))

    @Slot(str, result=bool)
    def saveNpmConfig(self, raw):
        if self._busy or self.controller.kernelBusy: return False
        previous = copy.deepcopy(self.controller.store.data["agent"])
        try:
            values = validate_npm_config(json.loads(raw))
            self.controller.store.data["agent"].update(values)
            self.controller.store.save()
        except (ValueError, OSError, TypeError) as exc:
            self.controller.store.data["agent"] = previous
            self.controller.toast.emit(str(exc)); return False
        self._npm_status = "npm 配置已保存；新启动的 Pi、扩展安装和内核更新将使用此配置"
        self.controller._restart_pi()
        self.controller.changed.emit(); self.changed.emit()
        return True

    @Slot()
    def testNpmConfig(self):
        if self._busy or self.controller.kernelBusy: return
        _, cwd, _, agent = self._context()
        self._npm_status = "正在检测 npm 源…"
        self._start("npm", self._npm_status, lambda: probe_npm(agent, cwd))

    def _context(self):
        c = self.controller
        agent = copy.deepcopy(c.store.data["agent"])
        cwd = Path(c._view.workspace or c.store.data["workspace"] or c.store.directory / "workspace")
        if not cwd.is_dir():
            cwd = c.store.directory / "workspace"
            cwd.mkdir(parents=True, exist_ok=True)
        agent_dir = Path(agent.get("agentDir") or Path.home() / ".pi/agent")
        return c._release, cwd, agent_dir, agent

    def _start(self, name, status, work):
        if self._busy or self.controller.kernelBusy: return
        self._job_context = self._resource_key()
        self._busy, self._status = True, status
        self.changed.emit()
        self.controller._job("pi-admin:" + name, work)

    def _resource_key(self):
        c = self.controller
        agent = {key: value for key, value in c.store.data["agent"].items() if key != "installPermission"}
        return (c._view.workspace or c.store.data["workspace"], str(c._release), json.dumps(agent, sort_keys=True))

    def _scan(self, apply=False):
        if self._busy or self.controller.kernelBusy:
            self._scan_pending = True
            return
        self._scan_pending = False
        context = self._context()
        self._start("reload" if apply else "scan", "正在读取 Pi 扩展…", lambda: resource_command(*context, action="scan"))

    @Slot()
    def scan(self):
        self._scan()

    @Slot()
    def refresh(self):
        self._scan(apply=True)

    @Slot(str, bool)
    def setExtensionEnabled(self, extension_id, enabled):
        if self._busy or self.controller.kernelBusy: return
        context = self._context()
        self._start("toggle", "正在保存扩展配置…", lambda: resource_command(*context, action="toggle", id=extension_id, enabled=enabled))

    @Slot()
    def openCatalog(self):
        QDesktopServices.openUrl(QUrl("https://pi.dev/packages"))

    @Slot()
    def resetInstall(self):
        if self._install_state == "installing": return
        self._install_state, self._install_message = "idle", ""
        self.changed.emit()

    @Slot(str, bool)
    def installExtension(self, command, local):
        if self._busy or self.controller.kernelBusy: return
        try:
            source, local = parse_install_command(command, local)
            context = self._context()
        except (ValueError, OSError) as exc:
            self._install_state, self._install_message = "failed", str(exc)
            self.changed.emit()
            return
        release, cwd, agent_dir, agent = context
        target = "项目 " + str(cwd) if local else "全局 " + str(agent_dir)
        def install():
            install_package(release, cwd, agent_dir, source, local, npm_config=agent)
            # Installation has succeeded even if a separate damaged config prevents scanning.
            try:
                rows = resource_command(*context, action="scan")
                warning = ""
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                rows, warning = [], "\n列表读取失败：" + str(exc)[:250]
            recovery = "\n恢复模式已开启，关闭后可加载新扩展。" if agent.get("safeMode") else ""
            installed = next((row for row in rows if row.get("source") == source), {})
            if not installed and not source.startswith(("npm:", "git:", "https://", "http://", "ssh://", "git@")):
                installed = next((row for row in rows if row.get("packageRoot") and
                    Path(row["packageRoot"]).resolve() == (cwd / source).resolve()), {})
            return {"extensions": rows, "message": "安装成功 · " + target + recovery + warning,
                    "installation": {"package": installed.get("name", source), "version": installed.get("version", ""),
                        "source": installed.get("source", source), "scope": "project" if local else "global", "workspace": str(cwd),
                        "installedBy": "user", "reason": "用户从设置手动安装", "time": timestamp()}}
        self._install_state, self._install_message = "installing", "正在安装到" + target + "…"
        self._start("install", self._install_message, install)

    @Slot(str)
    def uninstallPackage(self, extension_id):
        if self._busy or self.controller.kernelBusy: return
        row = next((row for row in self.packages if row["id"] == extension_id), None)
        if not row or not row["removable"]:
            self.controller.toast.emit("仅已注册的第三方扩展包可以卸载")
            return
        context = self._context()
        release, cwd, agent_dir, agent = context
        def uninstall():
            remove_package(release, cwd, agent_dir, row["source"], row["scope"] == "project", npm_config=agent, package_root=row.get("packageRoot"))
            return resource_command(*context, action="scan")
        self._start("remove", "正在卸载 " + row["name"] + "…", uninstall)

    @Slot(str, bool)
    def addMcp(self, text, local):
        if self._busy or self.controller.kernelBusy: return
        context = self._context()
        if not text.strip() or len(text) > 1_000_000 or context[3].get('safeMode') or local and not self.controller._view.workspace:
            self._install_state, self._install_message = 'failed', '请填写 MCP 命令或 JSON；项目范围需先打开项目，并关闭恢复模式'
            self.changed.emit(); return
        release, cwd, agent_dir, agent = context
        extensions = copy.deepcopy(self._extensions)
        def add():
            result = subprocess.run([node_executable(), str(release/'pi-commands.mjs'), '--add-mcp'],
                input=json.dumps({'text':text, 'local':local, 'cwd':str(cwd), 'agentDir':str(agent_dir)}),
                capture_output=True, text=True, encoding='utf-8', timeout=25,
                env=npm_environment(agent), creationflags=CREATE_NO_WINDOW)
            payload = json.loads(result.stdout)
            if result.returncode or not payload.get('ok'): raise ValueError(payload.get('error', 'MCP 添加失败'))
            return {'extensions':extensions, 'message':payload['message']}
        self._install_state, self._install_message = 'installing', '正在添加 MCP 服务器…'
        self._start('mcp-add', self._install_message, add)

    @Slot()
    def openTerminal(self):
        if self._busy or self.controller.kernelBusy: return
        release, cwd, agent_dir, agent = self._context()
        directory, root = self.controller.store.directory, self.controller.root
        def prepare():
            try:
                resource_command(release, cwd, agent_dir, agent, action="scan")
            except RuntimeError:
                pass  # A damaged settings file must not block its repair terminal.
            runtime = console_runtime(release, directory, agent_dir, root / "runtime/bridge.mjs")
            if agent.get("safeMode"):
                cwd_safe = directory / "pi-console/safe-workspace"
                cwd_safe.mkdir(parents=True, exist_ok=True)
            else:
                cwd_safe = cwd
            return prepare_terminal(runtime, directory, agent_dir, cwd_safe, directory / "pi/sessions", npm_config=agent)
        self._start("terminal", "正在准备内嵌 Pi 终端…", prepare)

    @Slot(bool)
    def setRecoveryMode(self, enabled):
        c = self.controller
        if self._busy or c.kernelBusy: return
        old = c.store.data["agent"].get("safeMode", False)
        try:
            c.store.data["agent"]["safeMode"] = enabled
            c.store.save()
        except (OSError, RuntimeError):
            c.store.data["agent"]["safeMode"] = old
            return c.toast.emit("恢复模式设置保存失败")
        c._restart_pi(); c.changed.emit()
        self.scan()

    @Slot()
    def restoreFactory(self):
        c = self.controller
        if self._busy or c.kernelBusy: return
        if any(record.busy for record in c._pool.records.values()):
            return c.toast.emit("请等待所有任务结束后恢复 Pi 内核")
        _, cwd, _, agent = self._context()
        self._start("factory", "正在备份配置并恢复出厂内核…", lambda: prepare_factory(c.root, c.store.directory, agent, cwd))
        c._kernel_busy = True; c.changed.emit()

    @Slot()
    def openBackup(self):
        if self._backup: QDesktopServices.openUrl(QUrl.fromLocalFile(self._backup))

    def _apply_factory(self, value):
        c = self.controller
        pointer = c.store.directory / "kernels/active.json"
        old_pointer = pointer.read_bytes() if pointer.exists() else None
        old_agent = c.store.data["agent"]
        new_agent = {**copy.deepcopy(DEFAULTS["agent"]), "agentDir": value["agentDir"], "safeMode": True}
        try:
            c.store.data["agent"] = new_agent
            c.store.save()
            temp = pointer.with_suffix(".tmp")
            release = Path(value["release"])
            temp.write_text(json.dumps({"version": installed_version(release), "directory": release.name}), encoding="utf-8")
            temp.replace(pointer)
        except (OSError, RuntimeError):
            c.store.data["agent"] = old_agent
            c.store.save()
            if old_pointer is not None: pointer.write_bytes(old_pointer)
            raise
        c._release = Path(value["release"])
        c._restart_pi()
        self._backup = value["backup"]
        self._extensions = []
        c._view.resources = {"tools": [], "skills": [], "extensions": [], "diagnostics": []}
        c._kernel_status = "已恢复出厂内核（恢复模式）"

    def _finished(self, name, result):
        if not name.startswith("pi-admin:") or self.controller._closing: return
        outcome = dict(result)
        self._apply_finished(name, outcome)
        self.operationFinished.emit(name, outcome)
        if self._scan_pending:
            QTimer.singleShot(0, self._sync_context)

    def _apply_finished(self, name, result):
        action, c = name.split(":", 1)[1], self.controller
        self._busy = False
        if action == "extension-check":
            if self._job_context != self._resource_key():
                self._extension_update = {}
            elif result["ok"]:
                self._extension_update = result["value"]
            else:
                self._extension_update = {**self._extension_update, "status": "error", "message": str(result["value"])}
            self._status = self._extension_update.get("message", "")
            self.changed.emit()
            return
        if action == "factory": c._kernel_busy = False
        if not result["ok"]:
            self._status = str(result["value"])
            if action == "npm": self._npm_status = self._status
            if action in ("install", "mcp-add"):
                self._install_state, self._install_message = "failed", self._status
            c.toast.emit(self._status); self.changed.emit()
            if action == "factory": c.changed.emit()
            return
        try:
            value = result["value"]
            if action == "npm":
                self._npm_status = str(value); self.changed.emit(); return
            if action in ("install", "mcp-add"):
                if value.get("installation"):
                    self._package_records.installed(value["installation"])
                self._install_state, self._install_message = "succeeded", value["message"]
                c._restart_pi()
                self._status = value["message"]
                c.toast.emit("MCP 已添加；运行中的任务完成后应用" if action == "mcp-add" else "扩展安装成功；运行中的任务完成后应用")
                self._extensions = value["extensions"] if self._job_context == self._resource_key() else []
                self.changed.emit()
                if self._job_context != self._resource_key(): self.scan()
                return
            if action in ("scan", "toggle", "reload", "remove"):
                if action in ("toggle", "reload", "remove"):
                    c._restart_pi()
                if self._job_context != self._resource_key():
                    self._extensions = []
                    self.changed.emit()
                    self.scan()
                    return
                self._extensions = value
                self._status = "已启用 " + str(sum(row["enabled"] for row in value)) + " / " + str(len(value)) + " 个扩展"
                if action in ("toggle", "reload", "remove"):
                    c.toast.emit("扩展包已卸载；运行中的任务完成后应用" if action == "remove" else "已保存；运行中的任务完成后应用扩展设置")
            elif action == "terminal":
                launch_terminal(value)
                self._status = "Pi 管理终端已打开，返回后可刷新扩展列表"
            elif action == "factory":
                self._apply_factory(value)
                self._status = "已恢复出厂内核；原配置已备份，项目和聊天记录已保留"
                c.toast.emit(self._status)
            self.changed.emit()
            if action == "factory":
                c.changed.emit()
                self.scan()
        except (OSError, RuntimeError, ValueError) as exc:
            result.update(ok=False, value=str(exc))
            self._status = str(exc); self.changed.emit(); c.toast.emit(self._status)
            if action == "factory": c.changed.emit()
