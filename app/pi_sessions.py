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


def clean_blocked_tools(value):
    if not isinstance(value, list): return []
    return list(dict.fromkeys(name for name in value if isinstance(name,str) and 0 < len(name) <= 256 and not any(ch.isspace() or ch in "*?\x00" for ch in name)))[:4096]


def clean_extension_modes(value):
    if not isinstance(value, dict): return {}
    return {path:mode for path,mode in value.items() if isinstance(path,str) and 0 < len(path) <= 4096 and mode in ("session","disabled")}


def clean_skill_modes(value):
    if not isinstance(value, dict): return {}
    return {path: enabled for path, enabled in value.items()
            if isinstance(path, str) and 0 < len(path) <= 4096 and type(enabled) is bool}


def saved_viewport(meta):
    value = meta.get('viewport', {})
    if not isinstance(value, dict): return -1, -1, True
    index, offset, follow = value.get('row', -1), value.get('offset', 0), value.get('follow', True)
    if type(index) is not int or not -1 <= index <= 2147483647 or type(offset) not in (int, float) or not 0 <= offset < 10000000 or type(follow) is not bool:
        return -1, -1, True
    if index == -1: return -1, -1, True
    return index, float(offset), follow


@dataclass(eq=False)
class SessionState:
    search_leaf: str = ""
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
    extension_modes: dict = field(default_factory=dict)
    skill_modes: dict = field(default_factory=dict)
    known_skills: dict = field(default_factory=dict)
    blocked_tools: list = field(default_factory=list)
    pi_capabilities: dict = field(default_factory=dict)
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
    crashed: bool = False
    operation: bool = False
    queue: list = field(default_factory=list)
    compaction_running: bool = False
    compaction_event_id: str = ""
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

    def __init__(self, parent=None, limit=3, body_limit=32 * 1024 * 1024):
        super().__init__(parent)
        self.limit = limit
        self.body_limit = body_limit
        self.records = OrderedDict()
        self.current = None
        self.retiring = set()
        self.closing = False
        self.catalog_requests = {}

    def query_catalog(self, record, kind, callback, **arguments):
        """Read the owning live Pi without changing its turn, model or busy state."""
        if self.closing or not record.process or not record.ready or record.stale or record.global_agent:
            return False
        if len(self.catalog_requests) >= 16:
            return False
        identifier = uuid.uuid4().hex
        timer = QTimer(self)
        timer.setSingleShot(True)
        self.catalog_requests[identifier] = (record, record.process, callback, timer)
        timer.timeout.connect(lambda: self._catalog_reply(record, {'id': identifier, 'ok': False, 'error': 'Pi directory read timed out'}))
        timer.start(10000)
        self.write(record, {'type': 'widget_catalog', 'id': identifier, 'kind': kind, **arguments})
        return True

    def _catalog_reply(self, record, event):
        request = self.catalog_requests.get(event.get('id'))
        if not request or request[0] is not record:
            return
        self.catalog_requests.pop(event['id'])
        _, _, callback, timer = request
        timer.stop()
        timer.deleteLater()
        if not self.closing:
            callback({'ok': bool(event.get('ok')), 'value': event.get('value') if event.get('ok') else event.get('error', 'Pi directory read failed')})

    def _cancel_catalogs(self, record):
        for identifier, request in list(self.catalog_requests.items()):
            if request[0] is record:
                self._catalog_reply(record, {'id': identifier, 'ok': False, 'error': 'Pi instance changed; refresh the directory'})

    def touch(self, record, current=False, dirty=True):
        if dirty:
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
        record.crashed = False
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
            if event.get('type') == 'widget_catalog':
                self._catalog_reply(record, event)
            else:
                self.event.emit(record, event)

    def _error(self, record, process, error):
        if record.process is process and error == QProcess.FailedToStart:
            record.process = None
            record.crashed = True
            self.event.emit(record, {"type": "exit", "message": "Pi 内核启动失败，请检查 Node.js 和内核设置"})
            process.deleteLater()

    def _finished(self, record, process):
        if record.process is process:
            self._read(record, process)
            self._cancel_catalogs(record)
            record.process = None
            if not self.closing:
                record.crashed = True
                self.event.emit(record, {"type": "exit"})
        self.retiring.discard(process)
        process.deleteLater()

    def retire(self, record):
        """Dispose an idle instance without blocking navigation on process exit."""
        process = record.process
        record.crashed = False
        record.ready, record.stale = False, False
        if not process:
            return
        self._cancel_catalogs(record)
        self.write(record, {"type": "shutdown"})
        record.process, record.ready, record.stale = None, False, False
        self.retiring.add(process)
        timer = QTimer(process)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: process.kill() if process.state() != QProcess.NotRunning else None)
        timer.start(2500)

    @staticmethod
    def protected(record):
        return record.busy or record.subagents_active or bool(record.approval)

    @staticmethod
    def _has_resources(record):
        return record.process is not None

    def _evict(self, record):
        """Release the kernel; loaded history has its own byte budget."""
        self.retire(record)

    def _clear_body(self, record):
        """Release a replayable body for its byte budget or explicit removal."""
        self._evict(record)
        if not record.file:
            return  # Unsaved messages are authoritative, not a replayable cache.
        record.messages, record.history, record.tree = [], [], []
        record.resources = {"tools": [], "skills": [], "extensions": [], "diagnostics": [], "toolCatalog":record.resources.get("toolCatalog",[])}
        record.transcript, record.loaded, record.body_bytes = None, False, 0
        record.body_dirty = False
        record.tail_characters = 0
        record.projection_dirty_from = None

    def trim(self):
        def idle():
            return [record for record in self.records.values()
                    if self._has_resources(record) and not self.protected(record)]
        while len(idle()) > max(0, self.limit):
            oldest = next((record for record in idle() if record is not self.current), None)
            if not oldest:
                break  # The current session is retained even when capacity is zero.
            self._evict(oldest)
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
            if record is self.current or self.protected(record) or not record.file or not record.loaded:
                continue
            released = record.body_bytes
            self._clear_body(record)
            total -= released

    def invalidate(self):
        for record in self.records.values():
            if self.protected(record):
                record.stale = True
            else:
                self.retire(record)

    def close(self):
        if self.closing:
            return
        self.closing = True
        for record in self.records.values():
            self._cancel_catalogs(record)
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
                process.waitForFinished(5000)
        for record in self.records.values():
            record.process = None
