"""Settings and explicit provisioning for the packaged Windows launcher."""
from __future__ import annotations

import logging
import lzma
import os
import tarfile
from threading import Thread

from PySide6.QtCore import QObject, Property, QProcess, Signal, Slot

from .pi_runtime import RELEASE_NAME
from .sandbox_git_bash import ARCHIVE_NAME, VERSION, git_bash_ready, prepare_git_bash


PREPARE_ERROR = "无法准备 Git Bash。请检查用户数据目录是否可写，然后关闭并重新开启沙箱。"
MISSING_ERROR = "Windows 沙箱组件缺失。请重新安装完整的 Windows 版本。"
SETUP_ERROR = "未完成管理员级隔离安装。请在 Windows 提示中允许安装，或稍后重试。"
SAVE_ERROR = "无法保存沙箱设置。请检查用户数据目录是否可写，然后重试。"
AGENT_BUSY = "另一个 Agent 正在执行任务。请等任务结束后再开启沙箱。"
ERROR_MESSAGES = {
    PREPARE_ERROR: "Could not prepare Git Bash. Check that your user data folder is writable, then turn the sandbox off and back on.",
    MISSING_ERROR: "Windows sandbox components are missing. Reinstall the complete Windows package.",
    SETUP_ERROR: "Administrator isolation setup did not finish. Allow installation at the Windows prompt or try again later.",
    SAVE_ERROR: "Could not save the sandbox settings. Check that your user data folder is writable, then try again.",
    AGENT_BUSY: "Another Agent is running a task. Wait for it to finish before turning on the sandbox.",
}
log = logging.getLogger(__name__)


class WindowsSandbox(QObject):
    changed = Signal()
    _progress_changed = Signal(int)
    _prepared = Signal(bool)

    def __init__(self, backend):
        super().__init__(backend)
        self.backend = backend
        self.launcher = backend.root / f"runtime/releases/{RELEASE_NAME}/bin/windows-sandbox/umeko-sandbox.exe"
        self.home = backend.store.directory / "windows-sandbox"
        self.temp = backend.store.directory / "windows-sandbox-temp"
        self.archive = self.launcher.with_name(ARCHIVE_NAME)
        self.git = self.home / "git" / VERSION
        self._supported = os.name == "nt"
        self._elevated = False
        self._error = ""
        self._process = None
        self._preparing = False
        self._progress = 0
        self._git_ready = False
        self._setup_pending = False
        self._progress_changed.connect(self._set_progress)
        self._prepared.connect(self._finish_preparation)
        if self._supported and self.home.is_dir() and self.launcher.is_file():
            self._launch("status")
        if self.state["enabled"]:
            self._prepare()

    @Property("QVariantMap", notify=changed)
    def state(self):
        agent = self.backend.store.data["agent"]
        enabled = self._supported and agent.get("windowsSandboxEnabled") is True
        allow_network = agent.get("windowsSandboxAllowNetwork") is True
        return {"supported": self._supported, "enabled": enabled,
                "level": ("elevated" if self._elevated else "non-elevated") if enabled else "off",
                "allowNetwork": allow_network,
                "networkBlocked": enabled and self._elevated and not allow_network,
                "elevatedReady": self._elevated, "busy": self._preparing or self._process is not None,
                "preparing": self._preparing, "progress": self._progress, "error": self._error}

    def tool_state(self):
        state = self.state
        state["error"] = ERROR_MESSAGES.get(self._error, "")
        if state["preparing"]:
            state["message"] = f"Preparing Git Bash for the Windows sandbox ({self._progress}%)."
        return state

    def policy(self):
        state = self.state
        if not state["enabled"]:
            return {"enabled": False}
        return {"enabled": True, "allowNetwork": state["allowNetwork"], "elevated": self._elevated,
                "launcher": str(self.launcher), "home": str(self.home), "temp": str(self.temp),
                "gitRoot": str(self.git), "gitReady": self._git_ready,
                "preparing": self._preparing, "progress": self._progress,
                "preparationError": self._error in (MISSING_ERROR, PREPARE_ERROR)}

    def publish(self):
        payload = {"type": "windows_sandbox", "policy": self.policy()}
        for record in tuple(self.backend._pool.records.values()):
            if record.process is not None:
                if getattr(record, "backend", "pi") == "dsh":
                    if payload["policy"]["enabled"]:
                        self.backend._pool.retire(record)
                    continue
                self.backend._pool.write(record, payload)
        self.changed.emit()

    def configure(self, enabled, allow_network):
        if not self._supported:
            raise ValueError("The Windows command sandbox is only available on Windows")
        if enabled:
            if any(getattr(record, "backend", "pi") == "dsh" and record.busy
                   for record in self.backend._pool.records.values()):
                self._configuration_error(AGENT_BUSY)
            if self._missing_components():
                self._configuration_error(MISSING_ERROR)
            try:
                self.temp.mkdir(exist_ok=True)
            except OSError:
                log.exception("Could not create the Windows sandbox temp directory")
                self._configuration_error(SAVE_ERROR)
        agent = self.backend.store.data["agent"]
        previous = {key: agent.get(key, False) for key in ("windowsSandboxEnabled", "windowsSandboxAllowNetwork")}
        agent.update(windowsSandboxEnabled=enabled, windowsSandboxAllowNetwork=allow_network)
        try:
            self.backend.store.save()
        except (OSError, RuntimeError):
            agent.update(previous)
            log.exception("Could not save the Windows sandbox settings")
            self._configuration_error(SAVE_ERROR)
        self._error = ""
        if enabled:
            self._prepare()
        self.publish()
        return self.tool_state()

    def _configuration_error(self, message):
        self._error = message
        self.changed.emit()
        raise ValueError(ERROR_MESSAGES[message])

    def _missing_components(self):
        return not (self.launcher.is_file() and self.archive.is_file())

    @Slot(bool, bool)
    def setOptions(self, enabled, allow_network):
        try:
            self.configure(enabled, allow_network)
        except ValueError as error:
            if not self._supported:
                self.backend.toast.emit(str(error))

    @Slot(bool)
    def setEnabled(self, enabled):
        self.setOptions(enabled, self.state["allowNetwork"])

    @Slot(bool)
    def setAllowNetwork(self, allow_network):
        self.setOptions(self.state["enabled"], allow_network)

    @Slot()
    def setup(self):
        if not self._supported or self.state["busy"]:
            return
        if self._missing_components():
            self._error = MISSING_ERROR
            self.changed.emit()
            return
        self._setup_pending = True
        self._prepare()
        self.changed.emit()

    def _prepare(self):
        if self._preparing:
            return
        self._git_ready = git_bash_ready(self.git)
        if self._git_ready:
            if self._setup_pending:
                self._setup_pending = False
                self._launch("setup")
            return
        if self._missing_components():
            self._error = MISSING_ERROR
            return

        self._preparing = True
        self._progress = 0

        def extract():
            try:
                prepare_git_bash(self.archive, self.git, self._progress_changed.emit)
            except (OSError, ValueError, EOFError, tarfile.TarError, lzma.LZMAError):
                log.exception("Could not prepare the Windows sandbox Git Bash bundle")
                self._prepared.emit(False)
            else:
                self._prepared.emit(True)

        Thread(target=extract, name="Umeko Git Bash preparation", daemon=True).start()

    @Slot(int)
    def _set_progress(self, progress):
        self._progress = progress
        self.changed.emit()

    @Slot(bool)
    def _finish_preparation(self, ok):
        self._preparing = False
        self._git_ready = ok
        if self._setup_pending and ok:
            self._launch("setup")
        self._setup_pending = False
        if not ok:
            self._error = PREPARE_ERROR
        self.publish()

    def _launch(self, operation):
        process = QProcess(self)
        self._process = process
        if operation == "setup":
            self._error = ""
        process.setProgram(str(self.launcher))
        process.setArguments([operation, str(self.home)])

        def finish(ok):
            if self._process is not process:
                return
            self._process = None
            self._elevated = ok
            if operation == "setup" and not ok:
                detail = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip()
                log.warning("Windows sandbox setup did not finish: %s", detail or process.errorString())
                self._error = SETUP_ERROR
            process.deleteLater()
            self.publish()

        process.finished.connect(lambda code, status: finish(code == 0 and status == QProcess.NormalExit))
        process.errorOccurred.connect(lambda error: finish(False) if error == QProcess.FailedToStart else None)
        process.start()
