"""Cowork OCR controller: a separate local job, never a chat turn."""
from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import QObject, Property, QProcess, QProcessEnvironment, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}

class QuickOcr(QObject):
    changed = Signal()

    def __init__(self, backend):
        super().__init__(backend)
        self.b = backend
        self.component = backend.store.directory.resolve() / "quick-ocr"
        self.worker = backend.root / "app/quick_ocr_worker.py"
        self.process = None
        self.timer = QTimer(self, singleShot=True, interval=45_000)
        self.timer.timeout.connect(self._timeout)
        self._ready = False
        self._error = ""
        self._state = "idle"
        self._source = None
        self._result = ""
        self._truncated = False
        self._rotation = 0
        self._owner = None
        backend.viewChanged.connect(self._view_changed)

    @property
    def _python(self):
        relative = "Scripts/python.exe" if os.name == "nt" else "bin/python"
        return self.component / "venv" / relative

    @Property(bool, notify=changed)
    def ready(self): return self._ready

    @Property(str, notify=changed)
    def state(self): return self._state

    @Property(str, notify=changed)
    def error(self): return self._error

    @Property(str, notify=changed)
    def sourceName(self): return self._source.name if self._source else ""

    @Property(str, notify=changed)
    def result(self): return self._result

    @Property(bool, notify=changed)
    def truncated(self): return self._truncated

    @Property(int, notify=changed)
    def rotation(self): return self._rotation

    @Property(str, constant=True)
    def profilePath(self): return str(self.component.parent)

    def _view_changed(self):
        if self._owner is not None and self._owner is not self.b._view:
            self.end()

    def _in_role(self):
        return self.b.cowork.active and self.b.cowork.role.get("typeId") == "ocr"

    @Slot(result=bool)
    def begin(self):
        if not self._in_role() or self.process is not None:
            return False
        self._owner = self.b._view
        self.refresh()
        return True

    @Slot()
    def refresh(self):
        if not self._owner or self.process is not None:
            return
        self._ready = False
        self._error = ""
        if not self._python.is_file() or not self.worker.is_file():
            self._state = "missing"
            self.changed.emit()
            return
        self._start("checking", ["--check"])

    @Slot(QUrl, result=bool)
    def selectImage(self, url):
        if not self._owner or self.process is not None:
            return False
        self._source, self._result, self._truncated, self._rotation = None, "", False, 0
        if not url.isLocalFile() or url.host() not in ("", "localhost"):
            self._error, self._state = "format", "error"
            self.changed.emit()
            return False
        raw = Path(url.toLocalFile())
        try:
            source = raw.resolve(strict=True)
            if os.name == "nt" and str(source).startswith("\\\\"):
                raise ValueError("remote path")
            if not source.is_file() or source.suffix.lower() not in IMAGE_SUFFIXES:
                raise ValueError("not a supported image")
            if source.stat().st_size > 40 * 1024 * 1024:
                self._error, self._state = "image_size", "error"
                self.changed.emit()
                return False
        except (ValueError, OSError, RuntimeError):
            self._error, self._state = "format", "error"
            self.changed.emit()
            return False
        self._source = source
        self._state, self._error = "idle", ""
        self.changed.emit()
        return True

    @Slot()
    def rotate(self):
        if self._source and self.process is None:
            self._rotation = (self._rotation + 90) % 360
            self._result, self._error, self._state = "", "", "idle"
            self._truncated = False
            self.changed.emit()

    @Slot()
    def recognize(self):
        if not self._owner or not self._in_role() or not self._source or not self._ready or self.process is not None:
            return
        self._result, self._error, self._truncated = "", "", False
        self._start("running", [str(self._source), str(self._rotation)])

    def _start(self, phase, args):
        process = QProcess(self)
        self.process, self._state = process, phase
        env = QProcessEnvironment.systemEnvironment()
        for key in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "PYTHONPATH", "PYTHONHOME"):
            env.remove(key)
        process.setProcessEnvironment(env)
        process.setWorkingDirectory(str(self.component))
        process.setStandardErrorFile(QProcess.nullDevice())
        process.finished.connect(lambda code, status: self._completed(process, phase, code, status))
        process.errorOccurred.connect(lambda error: self._failed_to_start(process) if error == QProcess.FailedToStart else None)
        self.timer.start()
        process.start(str(self._python), ["-I", str(self.worker), *args])
        self.changed.emit()

    def _detach(self, process, kill=False):
        if self.process is not process:
            return False
        self.process = None
        self.timer.stop()
        if kill and process.state() != QProcess.NotRunning:
            process.kill()
            process.finished.connect(lambda *_: process.deleteLater())
        else:
            process.deleteLater()
        return True

    def _failed_to_start(self, process):
        if self._detach(process):
            self._ready, self._state, self._error = False, "error", "engine"
            self.changed.emit()

    def _completed(self, process, phase, code, status):
        if self.process is not process:
            return
        data = bytes(process.readAllStandardOutput())
        if not self._detach(process):
            return
        try:
            if code or status != QProcess.NormalExit or len(data) > 1_000_000:
                raise ValueError()
            payload = json.loads(data)
            if not isinstance(payload, dict):
                raise ValueError()
        except (UnicodeError, ValueError):
            payload = {"ok": False, "error": "recognition" if phase == "running" else "engine"}
        if payload.get("ok") is not True:
            self._error = str(payload.get("error", "recognition"))
            self._state = "error"
            if phase == "checking" or self._error in ("engine", "weights", "offline"):
                self._ready = False
        elif phase == "checking":
            self._ready, self._state = True, "idle"
        else:
            value = payload.get("text")
            if not isinstance(value, str) or len(value) > 60_000:
                self._state, self._error = "error", "recognition"
            else:
                self._result, self._state = value, "done"
                self._truncated = payload.get("truncated") is True
        self.changed.emit()

    def _timeout(self):
        if self.process and self._detach(self.process, kill=True):
            self._state, self._error = "error", "timeout"
            self.changed.emit()

    @Slot()
    def cancel(self):
        if self.process and self._detach(self.process, kill=True):
            self._state, self._error = "idle", ""
            self.changed.emit()

    @Slot()
    def end(self):
        self._owner = None
        if self.process:
            self._detach(self.process, kill=True)
        self._ready, self._state, self._error = False, "idle", ""
        self._source, self._result, self._rotation, self._truncated = None, "", 0, False
        self.changed.emit()

    def close(self):
        if self.process:
            process = self.process
            self._detach(process, kill=True)
            if process.state() != QProcess.NotRunning:
                process.waitForFinished(750)

    @Slot()
    def copyResult(self):
        if self._result:
            QGuiApplication.clipboard().setText(self._result)

    @Slot()
    def copyProfilePath(self):
        QGuiApplication.clipboard().setText(self.profilePath)
