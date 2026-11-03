"""One shared asynchronous preflight/cache for the settings UI and desktop tool."""
from __future__ import annotations

import copy
import os
import time
import uuid
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot

from .runtime_dependencies import inspect_dependencies


class RuntimeCapabilities(QObject):
    changed = Signal()
    TTL = 120
    LIMIT = 8

    def __init__(self, backend):
        super().__init__(backend)
        self.backend = backend
        self.entries = OrderedDict()
        self.running = {}
        backend.jobDone.connect(self._finished)
        backend.viewChanged.connect(self.changed)

    def _context(self, caller=None):
        record = caller or self.backend._view
        workspace = str(Path(record.workspace or self.backend.store.directory / 'workspace').absolute())
        env = dict(os.environ)
        # Values stay internal. Never include environment variables in results.
        key = (workspace, *(env.get(k, '') for k in ('PATH', 'PATHEXT', 'HOME', 'USERPROFILE', 'LOCALAPPDATA',
            'XDG_CACHE_HOME', 'PLAYWRIGHT_BROWSERS_PATH')))
        return key, workspace, env

    def _snapshot(self, key, workspace):
        entry = self.entries.get(key, {})
        stale = time.monotonic() - entry.get('finished', float('-inf')) >= self.TTL
        return {**copy.deepcopy(entry.get('result', {})), 'workspace': workspace, 'stale': stale,
            'busy': entry.get('pending', False), 'state': 'checking' if entry.get('pending') else entry.get('state', 'unchecked'),
            'error': entry.get('error', ''), 'expiresInSeconds': max(0, self.TTL - (time.monotonic() - entry.get('finished', float('-inf'))))}

    @Property('QVariantMap', notify=changed)
    def snapshot(self):
        key, workspace, _ = self._context()
        return self._snapshot(key, workspace)

    def request(self, caller=None, force=False):
        key, workspace, env = self._context(caller)
        snapshot = self._snapshot(key, workspace)
        if self.backend._closing or snapshot['busy'] or not force and not snapshot['stale']:
            return snapshot
        if key not in self.entries and len(self.entries) >= self.LIMIT:
            victim = next((k for k, e in self.entries.items() if not e.get('pending')), None)
            if victim is None:
                raise ValueError('依赖检测队列已满，请稍后重试')
            del self.entries[victim]
        entry = self.entries.setdefault(key, {})
        self.entries.move_to_end(key)
        entry.update(pending=True, workspace=workspace, env=env)
        self._start_next()
        self.changed.emit()
        return self._snapshot(key, workspace)

    @Slot()
    def check(self):
        self.request()

    @Slot()
    def refresh(self):
        self.request(force=True)

    def _start_next(self):
        if self.backend._closing:
            return
        for key, entry in self.entries.items():
            if len(self.running) >= 2:
                break
            if not entry.get('pending') or key in self.running.values():
                continue
            name = 'runtime-capabilities:' + uuid.uuid4().hex
            self.running[name] = key
            workspace, env = entry['workspace'], entry.pop('env')
            self.backend._job(name, lambda w=workspace, e=env: inspect_dependencies(w, e))

    def _finished(self, name, outcome):
        key = self.running.pop(name, None)
        if key is None or self.backend._closing:
            return
        entry = self.entries[key]
        entry.update(pending=False, finished=time.monotonic())
        if outcome['ok']:
            entry.update(result=outcome['value'], state='ready', error='')
        else:
            # Failure never reuses a formerly successful result as current evidence.
            entry.update(result={}, state='error', error='依赖检测失败，请重新检测')
        self._start_next()
        self.changed.emit()
