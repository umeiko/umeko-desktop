"""Native extension administration and recoverable factory restoration."""
import copy
import json
import os
import re
import shutil
import subprocess
import uuid
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl
from PySide6.QtGui import QDesktopServices
from .pi_runtime import CREATE_NO_WINDOW, RELEASE_NAME, installed_version, node_executable, verify_runtime
from .pi_terminal import console_runtime, prepare_terminal, launch_terminal
from .pi_install import parse_install_command, install_package, remove_package
from .npm_config import validate_npm_config, probe_npm, npm_environment
from .storage import DEFAULTS
from .filesystem_paths import filesystem_path, ordinary_path


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
    return payload["details"] if action.get("action") == "details" else payload["update"] if action.get("action") == "check-update" else payload["extensions"]


def prepare_factory(root, directory, agent, workspace):
    root, directory = filesystem_path(root), filesystem_path(directory)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    backup = directory / "pi-backups" / stamp
    backup.mkdir(parents=True)
    old_dir = filesystem_path(agent.get("agentDir") or Path.home() / ".pi/agent")
    (backup / "restore.json").write_text(json.dumps({"agent": agent, "workspace": str(workspace)}, ensure_ascii=False, indent=2), encoding="utf-8")
    for source, name in ((old_dir / "settings.json", "personal-settings.json"),
                         (filesystem_path(workspace) / ".pi/settings.json", "project-settings.json"),
                         (directory / "kernels/active.json", "active.json")):
        if source.is_file(): shutil.copy2(source, backup / name)
    release = directory / "kernels" / ("factory-" + stamp)
    shutil.copytree(root / "runtime/releases" / RELEASE_NAME, release)
    verify_runtime(release, root / "runtime/bridge.mjs")
    fresh = directory / "pi-profiles" / stamp
    fresh.mkdir(parents=True)
    # Keep all original Pi directories, extension files and native sessions intact.
    return {"backup": str(ordinary_path(backup)), "release": str(ordinary_path(release)), "agentDir": str(ordinary_path(fresh))}


class PiManagement(QObject):
    changed = Signal()
    operationFinished = Signal(str, object)
    installProgress = Signal(str)

    def __init__(self, controller):
        super().__init__(controller)
        self.controller = controller
        self._busy, self._extensions, self._status, self._backup = False, [], "", ""
        self._install_state, self._install_message = "idle", ""
        self._npm_status = ""
        self._extension_update = {}
        self._install_cancel = None
        self.installProgress.connect(self._progress_install)
        self._extension_details = {}
        self._global_target = None
        self._extensions_context = None
        backups = controller.store.directory / "pi-backups"
        if backups.is_dir():
            saved = sorted(p for p in backups.iterdir() if p.is_dir() and (p / "restore.json").is_file())
            if saved: self._backup = str(saved[-1])
        controller.jobDone.connect(self._finished)
        controller.viewChanged.connect(self.changed)

    @Property(bool, notify=changed)
    def busy(self): return self._busy

    @Property("QVariantList", notify=changed)
    def extensions(self): return self._extensions

    @Property("QVariantMap", notify=changed)
    def extensionDetails(self): return self._extension_details

    @Property("QVariantMap", notify=changed)
    def extensionModes(self): return self.controller._view.extension_modes

    @Slot(str)
    def loadExtensionDetails(self, extension_id):
        if self._busy: return
        context = self._context()
        self._extension_details = {"id":extension_id, "busy":True}
        self._start("details", "正在读取扩展说明…", lambda: resource_command(*context,action="details",id=extension_id))

    @Slot(str, str)
    def setExtensionMode(self, extension_id, mode):
        if self._busy or self.controller.kernelBusy or mode not in ("global", "session", "disabled"): return
        row = next((row for row in self._extensions if row.get("id") == extension_id), None)
        if not row or not self.extensionsCurrent:
            self.controller.toast.emit("请刷新当前对话的插件列表"); return
        if row.get("info",{}).get("required"):
            self.controller.toast.emit("Umeko 基础能力固定启用，不能修改启用范围"); return
        if self.controller.store.data["agent"].get("safeMode"): return
        record = self.controller._view
        if mode == "global":
            self._global_target = (record, row["path"])
            context = self._context()
            self._start("enable-global", "正在保存扩展配置…", lambda: resource_command(*context,action="enable-global",id=extension_id))
            return
        record.extension_modes[row["path"]] = mode
        self._save_modes(record)

    def _save_modes(self, record):
        c=self.controller
        if record.id:
            c.store.data["sessionMeta"].setdefault(record.id,{})["extensionModes"] = dict(record.extension_modes)
            c.store.save()
        record.stale = True
        if not record.busy and not record.subagents_active: c._pool.retire(record)
        self.changed.emit(); c.chatChanged.emit()
    def set_tool_visible(self, name, visible):
        c, record = self.controller, self.controller._view
        if record.busy or record.subagents_active or self._busy or c.kernelBusy:
            raise ValueError("请等待当前任务和子代理结束后修改工具可见性")
        tools = record.resources.get('allTools', [])
        if not any(tool.get('name') == name and tool.get('exposure') != 'hidden' for tool in tools):
            raise ValueError("工具列表已变更，请刷新后重试")
        if not visible and name not in record.blocked_tools and len(record.blocked_tools) >= 4096:
            raise ValueError("本会话工具可见性设置已达上限")
        previous = list(record.blocked_tools)
        record.blocked_tools = [tool for tool in previous if tool != name]
        if not visible: record.blocked_tools.append(name)
        try:
            if record.id:
                c.store.data['sessionMeta'].setdefault(record.id,{})['blockedTools'] = list(record.blocked_tools)
                c.store.save()
        except (OSError, RuntimeError):
            record.blocked_tools = previous
            if record.id: c.store.data['sessionMeta'][record.id]['blockedTools'] = previous
            raise ValueError("工具可见性保存失败")
        for tool in tools:
            if tool.get('name') == name:
                tool['visible'] = visible
                if not visible: tool['active'] = False
        if not visible: record.resources['tools'] = [tool for tool in record.resources.get('tools',[]) if tool != name]
        record.stale = True
        c._pool.retire(record)
        self.changed.emit()
        c.chatChanged.emit()

    @Property(bool, notify=changed)
    def extensionsCurrent(self):
        return self._extensions_context == self._resource_key()

    @Property(str, notify=changed)
    def status(self): return self._status

    @Property(str, notify=changed)
    def backupPath(self): return self._backup

    @Property(str, notify=changed)
    def installState(self): return self._install_state

    @Property(str, notify=changed)
    def installMessage(self): return self._install_message

    @Property(bool, notify=changed)
    def installCancellable(self): return self._install_state=='installing' and self._install_cancel is not None and not self._install_cancel.is_set()

    @Slot()
    def cancelInstall(self):
        if self.installCancellable:
            self._install_cancel.set(); self._install_message='正在取消安装…'; self.changed.emit()

    @Slot(str)
    def _progress_install(self, message):
        if self._install_state=='installing' and self._install_cancel is not None and not self._install_cancel.is_set():
            self._install_message=message;self.changed.emit()

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
        return (c._view.workspace or c.store.data["workspace"], str(c._release), json.dumps(c.store.data["agent"], sort_keys=True))

    def _scan(self, apply=False):
        if self._busy or self.controller.kernelBusy: return
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

    @Slot(str)
    def uninstallPackage(self, extension_id):
        if self._busy or self.controller.kernelBusy: return
        if not self.extensionsCurrent:
            raise ValueError('Refresh the current workspace before removing a package')
        row = next((item for item in self._extensions if item.get('id') == extension_id), None)
        if not row or row.get('source') in ('', 'builtin', 'local', None):
            raise ValueError('Only a registered third-party package can be removed')
        context = self._context()
        release, cwd, agent_dir, agent = context
        if agent.get('safeMode'): raise ValueError('Leave recovery mode before removing a package')
        source, local = row['source'], row.get('scope') == 'project'
        if not Path(source).is_absolute() and not re.match(r'^(npm:|git:|https?:|ssh:|git@)', source):
            source = os.path.abspath((cwd / '.pi' if local else agent_dir) / source)
        def uninstall():
            remove_package(release, cwd, agent_dir, source, local, npm_config=agent)
            return resource_command(*context, action='scan')
        self._start('remove', '正在卸载 Pi 扩展包…', uninstall)

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
        except (ValueError, OSError) as exc:
            self._install_state, self._install_message = "failed", str(exc)
            self.changed.emit()
            return
        self.installPackage(source, local)

    @Slot(str, bool)
    def installPackage(self, source, local):
        """Structured host/Agent operations pass one literal source, not a command."""
        if self._busy or self.controller.kernelBusy: return
        try:
            if not source.strip() or len(source) > 4096 or source.startswith('-') or any(c in source for c in '\r\n\x00'):
                raise ValueError('请提供一个有效的扩展来源')
            context = self._context()
        except (ValueError, OSError) as exc:
            self._install_state, self._install_message = "failed", str(exc)
            self.changed.emit()
            return
        release, cwd, agent_dir, agent = context
        target = "项目 " + str(cwd) if local else "全局 " + str(agent_dir)
        self._install_cancel=threading.Event()
        cancel=self._install_cancel
        def install():
            install_package(release, cwd, agent_dir, source, local, npm_config=agent,
                progress=self.installProgress.emit,cancelled=cancel.is_set)
            # Installation has succeeded even if a separate damaged config prevents scanning.
            try:
                rows = resource_command(*context, action="scan")
                warning = ""
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                rows, warning = [], "\n列表读取失败：" + str(exc)[:250]
            recovery = "\n恢复模式已开启，关闭后可加载新扩展。" if agent.get("safeMode") else ""
            return {"extensions": rows, "message": "安装成功 · " + target + recovery + warning}
        self._install_state, self._install_message = "installing", "正在安装到" + target + "…"
        self._start("install", self._install_message, install)

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
        new_agent = {**copy.deepcopy(DEFAULTS["agent"]), "agentDir": value["agentDir"], "safeMode": True,
                     "toolPermissionMode": old_agent.get("toolPermissionMode", "auto")}
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

    def _apply_finished(self, name, result):
        action, c = name.split(":", 1)[1], self.controller
        self._busy = False
        if action == "details":
            self._extension_details = ({**result["value"], "busy":False} if result["ok"] else {**self._extension_details,"busy":False,"error":str(result["value"])}) if self._job_context == self._resource_key() else {}
            self._status = self._extension_details.get("error", "")
            self.changed.emit(); return
        if action == "enable-global":
            target,self._global_target = self._global_target,None
            if result["ok"] and target:
                record,path=target
                record.extension_modes.pop(path,None)
                self._save_modes(record)
                c._restart_pi()
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
                self._install_state, self._install_message = "cancelled" if action=="install" and self._install_cancel and self._install_cancel.is_set() else "failed", self._status
                if action=="install":self._install_cancel=None
            c.toast.emit(self._status); self.changed.emit()
            if action == "factory": c.changed.emit()
            return
        try:
            value = result["value"]
            if action == "npm":
                self._npm_status = str(value); self.changed.emit(); return
            if action in ("install", "mcp-add"):
                self._install_state, self._install_message = "succeeded", value["message"]
                if action=="install":self._install_cancel=None
                c._restart_pi()
                self._status = value["message"]
                c.toast.emit("MCP 已添加；运行中的任务完成后应用" if action == "mcp-add" else "扩展安装成功；运行中的任务完成后应用")
                self._extensions = value["extensions"] if self._job_context == self._resource_key() else []
                self._extensions_context = self._job_context if self._job_context == self._resource_key() else None
                self.changed.emit()
                if self._job_context != self._resource_key(): self.scan()
                return
            if action in ("scan", "toggle", "reload", "enable-global", "remove"):
                if action in ("toggle", "reload", "remove"):
                    c._restart_pi()
                if self._job_context != self._resource_key():
                    self._extensions = []
                    self._extensions_context = None
                    self.changed.emit()
                    self.scan()
                    return
                self._extensions = value
                self._extensions_context = self._job_context
                self._status = "已启用 " + str(sum(row["enabled"] for row in value)) + " / " + str(len(value)) + " 个扩展"
                if action in ("toggle", "reload", "remove"):
                    c.toast.emit("已保存；运行中的任务完成后应用扩展设置")
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
