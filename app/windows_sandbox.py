"""Settings and explicit provisioning for the packaged Windows launcher."""
from __future__ import annotations

import logging
import lzma
import os
import tarfile
from threading import Thread
from time import monotonic

from PySide6.QtCore import QObject, Property, QProcess, QTimer, Signal, Slot

from .pi_runtime import RELEASE_NAME
from .sandbox_git_bash import (
    ARCHIVE_NAME, VERSION, clean_git_bash_cache, find_git_bash, git_bash_ready, recover_git_bash,
)


STORAGE_ERROR = "git-bash-storage-unwritable"
ARCHIVE_MISSING = "git-bash-archive-missing"
ARCHIVE_INVALID = "git-bash-archive-invalid"
PREPARATION_ERRORS = (STORAGE_ERROR, ARCHIVE_MISSING, ARCHIVE_INVALID,)
RETRY_INTERVALS_MS = (1000, 3000, 10000, 30000)
MISSING_ERROR = "Windows 沙箱组件缺失。请重新安装完整的 Windows 版本。"
SETUP_ERROR = "未完成管理员级隔离安装。请在 Windows 提示中允许安装，或稍后重试。"
SAVE_ERROR = "无法保存沙箱设置。请检查用户数据目录是否可写，然后重试。"
AGENT_BUSY = "另一个 Agent 正在执行任务。请等任务结束后再开启沙箱。"
ERROR_MESSAGES = {
    ARCHIVE_MISSING: "The Umeko installation is incomplete. Download and install Umeko again to restore Git Bash.",
    ARCHIVE_INVALID: "The Umeko installation has a damaged Git Bash archive. Download and install Umeko again.",
    MISSING_ERROR: "Windows sandbox components are missing. Reinstall the complete Windows package.",
    SETUP_ERROR: "Administrator isolation setup did not finish. Allow installation at the Windows prompt or try again later.",
    SAVE_ERROR: "Could not save the sandbox settings. Check that your user data folder is writable, then try again.",
    AGENT_BUSY: "Another Agent is running a task. Wait for it to finish before turning on the sandbox.",
}
log = logging.getLogger(__name__)


class WindowsSandbox(QObject):
    changed = Signal()
    _progress_changed = Signal(int)
    _prepared = Signal(object, str)

    def __init__(self, backend):
        super().__init__(backend)
        self.backend = backend
        self.launcher = backend.root / f"runtime/releases/{RELEASE_NAME}/bin/windows-sandbox/umeko-sandbox.exe"
        self.home = backend.store.directory / "windows-sandbox"
        self.temp = backend.store.directory / "windows-sandbox-temp"
        self.archive = self.launcher.with_name(ARCHIVE_NAME)
        self.git_version = self.home / "git" / VERSION
        self.git = None
        self._supported = os.name == "nt"
        self._elevated = False
        self._error = ""
        self._process = None
        self._preparing = False
        self._extracting = False
        self._progress = 0
        self._failed_attempts = 0
        self._archive_failed_once = False
        self._preparation_attempt = 0
        self._preparation_started = None
        self._preparation_seconds = None
        self._preparation_first_use = False
        self._prepared_before = False
        self._previous_git = None
        self._cleanup_on_startup = True
        self._setup_pending = False
        self._retry = None
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
                "preparing": self._preparing, "progress": self._progress, "error": self._error,
                "errorPath": str(self.git_version.parent) if self._error == STORAGE_ERROR else "",
                "gitRoot": str(self.git) if self.git else ""}

    def _error_message(self):
        if self._error == STORAGE_ERROR:
            return f"Could not write Git Bash to {self.git_version.parent}. Umeko will continue retrying automatically."
        return ERROR_MESSAGES.get(self._error, "")

    def tool_state(self):
        state = self.state
        state["error"] = self._error_message()
        if state["preparing"]:
            state["message"] = f"Preparing Git Bash for the Windows sandbox ({self._progress}%)."
        return state

    def policy(self):
        state = self.state
        if not state["enabled"]:
            return {"enabled": False}
        return {"enabled": True, "allowNetwork": state["allowNetwork"], "elevated": self._elevated,
                "launcher": str(self.launcher), "home": str(self.home), "temp": str(self.temp),
                "archive": str(self.archive), "gitRoot": state["gitRoot"], "gitReady": bool(self.git),
                "preparing": self._preparing, "progress": self._progress,
                "preparationAttempt": self._preparation_attempt,
                "preparationSeconds": self._preparation_seconds,
                "preparationFirstUse": self._preparation_first_use,
                "preparationError": self._error_message() if self._error in (*PREPARATION_ERRORS, MISSING_ERROR) else ""}

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
            if not self.launcher.is_file():
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
            self.prepare_for_command()
        elif not self._setup_pending:
            if self._retry is not None:
                self._retry.stop()
            self._preparing = self._extracting
        self.publish()
        return self.tool_state()

    def _configuration_error(self, message):
        self._error = message
        self.changed.emit()
        raise ValueError(ERROR_MESSAGES[message])

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
        if not self.launcher.is_file():
            self._error = MISSING_ERROR
            self.changed.emit()
            return
        self._setup_pending = True
        self._prepare()

    def prepare_for_command(self):
        if not self.state["enabled"]:
            return
        if self._retry is not None:
            if self._retry.isActive() and self._preparing:
                return
            self._retry.stop()
        self._prepare()

    def _schedule_retry(self, delay):
        if self._retry is None:
            self._retry = QTimer(self)
            self._retry.setSingleShot(True)
            self._retry.timeout.connect(self._prepare)
        self._retry.start(delay)

    def _prepare(self):
        if self._extracting or not (self.state["enabled"] or self._setup_pending):
            return
        if not self.archive.is_file() or not self.launcher.is_file():
            self._finish_preparation(None, ARCHIVE_MISSING if not self.archive.is_file() else MISSING_ERROR)
            return
        previous = self.git
        if previous is not None and git_bash_ready(previous):
            self._preparing = False
            if self._setup_pending:
                self._setup_pending = False
                self._launch("setup")
            self.publish()
            return
        self._previous_git = previous or self._previous_git
        self.git = None
        cleanup = self._cleanup_on_startup
        self._cleanup_on_startup = False
        self._preparing = True
        self._extracting = True
        self._progress = 0
        self._preparation_seconds = None
        if self._preparation_started is None:
            self._preparation_started = monotonic()
        self.publish()

        def extract():
            try:
                git = find_git_bash(self.git_version)
                reused = git is not None
                if not reused:
                    git = recover_git_bash(self.archive, self.git_version, self._progress_changed.emit, self._previous_git)
                if cleanup:
                    clean_git_bash_cache(self.git_version, keep=git)
            except (ValueError, EOFError, tarfile.TarError, lzma.LZMAError):
                log.exception("The Windows sandbox Git Bash archive is damaged")
                self._prepared.emit(None, ARCHIVE_INVALID)
            except OSError:
                log.exception("Could not prepare the Windows sandbox Git Bash bundle")
                self._prepared.emit(None, STORAGE_ERROR if self.archive.is_file() else ARCHIVE_MISSING)
            else:
                self._prepared.emit((git, reused), "")

        Thread(target=extract, name="Umeko Git Bash preparation", daemon=True).start()

    @Slot(int)
    def _set_progress(self, progress):
        self._progress = progress
        self.changed.emit()

    @Slot(object, str)
    def _finish_preparation(self, result, error):
        self._extracting = False
        self._preparing = False
        self._preparation_attempt += 1
        if result:
            self.git, reused = result
            self._previous_git = None
            self._preparation_first_use = not self._prepared_before
            self._prepared_before = True
            self._progress = 100
            self._preparation_seconds = None if reused else round(monotonic() - self._preparation_started, 1)
            self._preparation_started = None
            self._failed_attempts = 0
            self._archive_failed_once = False
            if self._error in PREPARATION_ERRORS:
                self._error = ""
            if self._setup_pending:
                self._setup_pending = False
                self._launch("setup")
        elif error == STORAGE_ERROR:
            self._failed_attempts += 1
            self._preparing = self._failed_attempts < 3 and (self.state["enabled"] or self._setup_pending)
            if self._failed_attempts >= 3:
                self._error = error
            if self.state["enabled"] or self._setup_pending:
                self._schedule_retry(RETRY_INTERVALS_MS[min(self._failed_attempts - 1, len(RETRY_INTERVALS_MS) - 1)])
        elif error == ARCHIVE_INVALID and not self._archive_failed_once and (self.state["enabled"] or self._setup_pending):
            self._archive_failed_once = True
            self._preparing = True
            self._schedule_retry(RETRY_INTERVALS_MS[0])
        else:
            self.git = None
            self._error = error
            self._setup_pending = False
            self._preparation_started = None
            self._archive_failed_once = False
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
