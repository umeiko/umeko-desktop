"""Independent native Pi processes, with an LRU of idle instances."""
from __future__ import annotations

import json
import os
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal
from .npm_config import npm_overrides


@dataclass(eq=False)
class SessionState:
    global_agent: str = ""
    key: str = field(default_factory=lambda: uuid.uuid4().hex)
    id: str = ""
    file: str = ""
    workspace: str = ""
    model: str = ""
    provider: str = ""
    title: str = "新会话"
    messages: list = field(default_factory=list)
    history: list = field(default_factory=list)
    tree: list = field(default_factory=list)
    resources: dict = field(default_factory=lambda: {"tools": [], "skills": [], "extensions": [], "diagnostics": []})
    context_usage: dict = field(default_factory=dict)
    network_retry: dict = field(default_factory=dict)
    reasoning_effort: str = "off"
    attachments: list = field(default_factory=list)
    approval: dict = field(default_factory=dict)
    draft: str = ""
    greeting: str = ""
    phase: str = "idle"
    action: str = ""
    prompt_started: float | None = None
    tool_status: str = ""
    pet_activity: str = "thinking"
    process: QProcess | None = None
    buffer: bytes = b""
    ready: bool = False
    failed: bool = False
    cancelled: bool = False
    stale: bool = False
    operation: bool = False
    queue: list = field(default_factory=list)
    portrait: int = 0
    optimistic_user: bool = False
    scroll_y: float = -1
    scroll_index: int = -1
    follow_tail: bool = True
    loaded: bool = True
    transcript: object = None
    index_request: int = 0
    body_bytes: int = 0
    body_dirty: bool = True
    index_running: bool = False
    index_pending: object = None
    tail_characters: int = 0
    projection_dirty_from: int | None = None
    subagents: dict = field(default_factory=dict)
    subagents_active: bool = False

    @property
    def busy(self):
        return self.phase != "idle" or self.operation

    @busy.setter
    def busy(self, value):
        self.phase = (self.phase if self.phase != "idle" else "working") if value else "idle"


class PiSessionPool(QObject):
    event = Signal(object, object)

    def __init__(self, parent=None, limit=8, body_limit=32 * 1024 * 1024):
        super().__init__(parent)
        self.limit = limit
        self.body_limit = body_limit
        self.records = OrderedDict()
        self.current = None
        self.retiring = set()
        self.closing = False

    def touch(self, record, current=False):
        record.body_dirty = True
        self.records[record.key] = record
        self.records.move_to_end(record.key)
        if current:
            self.current = record
        self.trim()

    def find(self, session_id):
        return next((record for record in self.records.values() if record.id == session_id), None) if session_id else None

    def write(self, record, payload):
        if record.process:
            record.process.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())

    def start(self, record, program, bridge, payload):
        process = QProcess(self)
        record.process, record.buffer, record.ready = process, b"", False
        environment = QProcessEnvironment.systemEnvironment()
        for key in environment.keys():
            if key.upper() in ("NODE_OPTIONS", "NODE_PATH") or key.upper().endswith(("API_KEY", "ACCESS_TOKEN", "_AK", "_SK", "_SECRET_KEY", "_SECURITY_TOKEN")):
                environment.remove(key)
        environment.remove("PI_OFFLINE")
        for key, value in npm_overrides(payload.get("agent") or {}).items():
            for existing in environment.keys():
                if existing.lower() == key: environment.remove(existing)
            environment.insert(key, value)
        environment.insert("PATH", os.path.dirname(program) + os.pathsep + environment.value("PATH"))
        process.setProcessEnvironment(environment)
        process.setProgram(program)
        process.setArguments([str(bridge)])
        process.started.connect(lambda: self.write(record, payload) if record.process is process else None)
        process.readyReadStandardOutput.connect(lambda: self._read(record, process))
        process.readyReadStandardError.connect(lambda: process.readAllStandardError())
        process.finished.connect(lambda *_: self._finished(record, process))
        process.errorOccurred.connect(lambda error: self._error(record, process, error))
        process.start()
        self.touch(record)

    def _read(self, record, process):
        if record.process is not process or self.closing:
            return
        record.buffer += bytes(process.readAllStandardOutput())
        while b"\n" in record.buffer:
            line, record.buffer = record.buffer.split(b"\n", 1)
            try:
                event = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            self.event.emit(record, event)

    def _error(self, record, process, error):
        if record.process is process and error == QProcess.FailedToStart:
            record.process = None
            self.event.emit(record, {"type": "exit", "message": "Pi 内核启动失败，请检查 Node.js 和内核设置"})
            process.deleteLater()

    def _finished(self, record, process):
        if record.process is process:
            self._read(record, process)
            record.process = None
            if not self.closing:
                self.event.emit(record, {"type": "exit"})
        self.retiring.discard(process)
        process.deleteLater()

    def retire(self, record):
        """Dispose an idle instance without blocking navigation on process exit."""
        process = record.process
        if not process:
            return
        self.write(record, {"type": "shutdown"})
        record.process, record.ready, record.stale = None, False, False
        self.retiring.add(process)
        timer = QTimer(process)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: process.kill() if process.state() != QProcess.NotRunning else None)
        timer.start(2500)

    def trim(self):
        while sum(record.process is not None for record in self.records.values()) > self.limit:
            oldest = next((record for record in self.records.values() if record.process and not record.busy and not record.subagents_active and record is not self.current), None)
            if not oldest:
                break  # Running/loading instances are never evicted.
            self.retire(oldest)
        self.trim_bodies()

    def trim_bodies(self):
        from .transcript_index import memory_weight
        for record in self.records.values():
            if record.body_dirty:
                record.body_bytes = memory_weight((record.messages, record.history, record.tree, record.resources))
                record.body_dirty = False
        total = sum(record.body_bytes for record in self.records.values())
        for record in self.records.values():
            if total <= self.body_limit:
                break
            if record is self.current or record.busy or record.subagents_active or not record.file or not record.loaded:
                continue
            self.retire(record)
            total -= record.body_bytes
            record.messages, record.history, record.tree = [], [], []
            record.resources = {"tools": [], "skills": [], "extensions": [], "diagnostics": []}
            record.transcript, record.loaded, record.body_bytes = None, False, 0

    def invalidate(self):
        for record in self.records.values():
            if record.busy or record.subagents_active:
                record.stale = True
            else:
                self.retire(record)

    def close(self):
        if self.closing:
            return
        self.closing = True
        processes = set(self.retiring)
        for record in self.records.values():
            if record.process:
                self.write(record, {"type": "shutdown"})
                processes.add(record.process)
        deadline = time.monotonic() + 2.5
        for process in processes:
            if process.state() != QProcess.NotRunning:
                process.waitForFinished(max(1, int((deadline - time.monotonic()) * 1000)))
        for process in processes:
            if process.state() != QProcess.NotRunning:
                process.kill()
                process.waitForFinished(500)
        for record in self.records.values():
            record.process = None
