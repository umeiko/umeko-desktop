"""Settings and explicit provisioning for the packaged Windows launcher."""
from __future__ import annotations

import os

from PySide6.QtCore import QObject, Property, QProcess, Signal, Slot

from .pi_runtime import RELEASE_NAME


class WindowsSandbox(QObject):
    changed = Signal()

    def __init__(self, backend):
        super().__init__(backend)
        self.backend = backend
        self.launcher = backend.root / f"runtime/releases/{RELEASE_NAME}/bin/windows-sandbox/umeko-sandbox.exe"
        self.home = backend.store.directory / "windows-sandbox"
        self.temp = backend.store.directory / "windows-sandbox-temp"
        self._supported = os.name == "nt"
        self._elevated = False
        self._error = ""
        self._process = None
        if self._supported and self.home.is_dir() and self.launcher.is_file():
            self._launch("status")

    @Property("QVariantMap", notify=changed)
    def state(self):
        agent = self.backend.store.data["agent"]
        enabled = self._supported and agent.get("windowsSandboxEnabled") is True
        allow_network = agent.get("windowsSandboxAllowNetwork") is True
        return {"supported": self._supported, "enabled": enabled,
                "level": ("elevated" if self._elevated else "non-elevated") if enabled else "off",
                "allowNetwork": allow_network,
                "networkBlocked": enabled and self._elevated and not allow_network,
                "elevatedReady": self._elevated, "busy": self._process is not None, "error": self._error}

    def policy(self):
        state = self.state
        if not state["enabled"]:
            return {"enabled": False}
        return {"enabled": True, "allowNetwork": state["allowNetwork"], "elevated": self._elevated,
                "launcher": str(self.launcher), "home": str(self.home), "temp": str(self.temp)}

    def publish(self):
        payload = {"type": "windows_sandbox", "policy": self.policy()}
        for record in self.backend._pool.records.values():
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
                raise ValueError("Finish the other Agent backend's running task before enabling the Windows sandbox")
            if not self.launcher.is_file():
                raise ValueError("The Windows sandbox launcher is missing. Use a complete Windows package.")
            self.temp.mkdir(exist_ok=True)
        agent = self.backend.store.data["agent"]
        previous = {key: agent.get(key, False) for key in ("windowsSandboxEnabled", "windowsSandboxAllowNetwork")}
        agent.update(windowsSandboxEnabled=enabled, windowsSandboxAllowNetwork=allow_network)
        try:
            self.backend.store.save()
        except (OSError, RuntimeError):
            agent.update(previous)
            raise
        self.publish()
        return self.state

    @Slot(bool, bool)
    def setOptions(self, enabled, allow_network):
        try:
            self.configure(enabled, allow_network)
        except (OSError, ValueError, RuntimeError) as error:
            self.backend.toast.emit(str(error))

    @Slot()
    def setup(self):
        if not self._supported or self._process is not None:
            return
        if not self.launcher.is_file():
            self.backend.toast.emit("Windows 沙箱启动程序缺失，请使用完整的 Windows 安装包。")
            return
        self._launch("setup")
        self.changed.emit()

    def _launch(self, operation):
        process = QProcess(self)
        self._process = process
        self._error = ""
        process.setProgram(str(self.launcher))
        process.setArguments([operation, str(self.home)])

        def finish(ok):
            if self._process is not process:
                return
            self._process = None
            self._elevated = ok
            if operation == "setup" and not ok:
                self._error = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip() or process.errorString()
            process.deleteLater()
            self.publish()

        process.finished.connect(lambda code, status: finish(code == 0 and status == QProcess.NormalExit))
        process.errorOccurred.connect(lambda error: finish(False) if error == QProcess.FailedToStart else None)
        process.start()
