"""Virtualized results from the shared, cancellable ripgrep worker."""
import json
import os
import uuid
import time
from pathlib import Path
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Property, Signal, Slot, QProcess, QProcessEnvironment, QTimer
from .pi_runtime import node_executable


class ConversationSearch(QAbstractListModel):
    changed = Signal()
    jumpReady = Signal(int, str)

    def __init__(self, controller):
        super().__init__(controller)
        self.controller = controller
        self._query = self._phase = self._error = ''
        self._busy = self._limit = False
        self._count = self._skipped = self._generation = 0
        self._groups, self._flat = [], []
        self._worker, self._buffer = None, b''
        self._pump = QTimer(self)
        self._pump.setSingleShot(True)
        self._pump.timeout.connect(self._drain)
        self._jump_token = -1000000
        self._jump = None
        controller.sessionPreview.ready.connect(self._prepared)

    query = Property(str, lambda self: self._query, notify=changed)
    phase = Property(str, lambda self: self._phase, notify=changed)
    error = Property(str, lambda self: self._error, notify=changed)
    busy = Property(bool, lambda self: self._busy, notify=changed)
    limitHit = Property(bool, lambda self: self._limit, notify=changed)
    count = Property(int, lambda self: self._count, notify=changed)
    skipped = Property(int, lambda self: self._skipped, notify=changed)
    conversationCount = Property(int, lambda self: len(self._groups), notify=changed)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._flat)

    def roleNames(self):
        return {Qt.UserRole + 1: b'modelData'}

    def data(self, index, role=Qt.DisplayRole):
        return self.item(index.row()) if index.isValid() and role == Qt.UserRole + 1 else None

    @Slot(int, result='QVariantMap')
    def item(self, row):
        if not 0 <= row < len(self._flat):
            return {}
        group, hit = self._flat[row]
        value = self._groups[group]
        return ({'kind': 'session', 'sessionId': value['id'], 'title': value['title'], 'count': len(value['hits']), 'collapsed': value['collapsed']}
                if hit < 0 else {**value['hits'][hit], 'kind': 'match'})

    def _rebuild(self):
        self.beginResetModel()
        self._flat = [(group, hit) for group, value in enumerate(self._groups)
                      for hit in [-1, *(range(len(value['hits'])) if not value['collapsed'] else ())]]
        self.endResetModel()

    @Slot(str)
    def toggle(self, session_id):
        for group in self._groups:
            if group['id'] == session_id:
                group['collapsed'] = not group['collapsed']
                self._rebuild()
                return

    @Slot()
    def collapseAll(self):
        expand = bool(self._groups) and all(group['collapsed'] for group in self._groups)
        for group in self._groups:
            group['collapsed'] = not expand
        self._rebuild()

    def _add(self, items):
        batches = {}
        for item in items:
            batches.setdefault(item['sessionId'], []).append(item)
        for session_id, hits in batches.items():
            group = next((i for i, value in enumerate(self._groups) if value['id'] == session_id), len(self._groups))
            if group == len(self._groups):
                title = hits[0]['title']
                group = next((i for i, value in enumerate(self._groups) if value['title'].casefold() > title.casefold()), len(self._groups))
                at = len(self._flat) if group == len(self._groups) else self._flat.index((group, -1))
                self.beginInsertRows(QModelIndex(), at, at)
                self._flat = [(g + (g >= group), h) for g, h in self._flat]
                self._groups.insert(group, {'id': session_id, 'title': title, 'hits': [], 'collapsed': False})
                self._flat.insert(at, (group, -1))
                self.endInsertRows()
            value = self._groups[group]
            header = self._flat.index((group, -1))
            start = len(value['hits'])
            if value['collapsed']:
                value['hits'].extend(hits)
            else:
                at = header + 1 + start
                self.beginInsertRows(QModelIndex(), at, at + len(hits) - 1)
                value['hits'].extend(hits)
                self._flat[at:at] = [(group, start + i) for i in range(len(hits))]
                self.endInsertRows()
            self.dataChanged.emit(self.index(header), self.index(header), [Qt.UserRole + 1])
            self._count += len(hits)

    def _write(self, job):
        if self._worker:
            self._worker.write((json.dumps(job, ensure_ascii=False) + '\n').encode())

    def _start(self):
        if self._worker and self._worker.state() != QProcess.NotRunning:
            return True
        if self._worker:
            self._worker.deleteLater()
        try:
            program = node_executable()
        except RuntimeError as error:
            self._error, self._busy = str(error), False
            self.changed.emit()
            return False
        process = self._worker = QProcess(self)
        self._buffer = b''
        env = QProcessEnvironment.systemEnvironment()
        env.remove('NODE_OPTIONS'); env.remove('NODE_PATH')
        process.setProcessEnvironment(env)
        process.setProgram(program)
        process.setArguments([str(self.controller.root / 'runtime/conversation-search.mjs')])
        process.readyReadStandardOutput.connect(self._read)
        process.readyReadStandardError.connect(lambda: process.readAllStandardError())
        process.errorOccurred.connect(lambda _: self._failed(process))
        process.finished.connect(lambda *_: self._failed(process))
        process.start()
        return True

    def _failed(self, process):
        if self._worker is process and self._busy:
            self._busy, self._error = False, '本地搜索进程已退出，请重试'
            self.changed.emit()

    def _read(self):
        self._buffer += bytes(self._worker.readAllStandardOutput())
        if not self._pump.isActive(): self._pump.start(0)

    def _drain(self):
        until, batches = time.monotonic() + 0.006, 0
        while b'\n' in self._buffer and batches < 4 and time.monotonic() < until:
            batches += 1
            line, self._buffer = self._buffer.split(b'\n', 1)
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get('id') != self._generation:
                continue
            kind = event.get('type')
            if kind == 'matches': self._add(event['items'])
            elif kind in ('preparing', 'searching'): self._phase = kind
            elif kind == 'source_error': self._skipped += 1
            elif kind == 'done':
                self._busy, self._phase = False, 'done'
                self._limit, self._skipped = bool(event.get('limitHit')), event.get('skipped', 0)
            elif kind == 'error': self._busy, self._phase, self._error = False, 'error', event.get('message', '')
            self.changed.emit()
        if b'\n' in self._buffer: self._pump.start(8)

    @Slot()
    def cancel(self):
        self._generation += 1
        self._write({'type': 'cancel', 'id': self._generation})
        self._busy, self._phase = False, 'stopped'
        self.changed.emit()

    @Slot()
    def clear(self):
        self.cancel()
        self._query = self._error = self._phase = ''
        self._count = self._skipped = 0
        self._limit = False
        self.beginResetModel(); self._groups.clear(); self._flat.clear(); self.endResetModel()
        self.changed.emit()

    @Slot(str, 'QVariantMap')
    def search(self, text, options):
        self.clear()
        self._query = text
        if not text.strip(): self.changed.emit(); return
        self._busy, self._phase = True, 'preparing'
        self.changed.emit()
        if not self._start(): return
        controller = self.controller
        workspace = str(Path(controller._view.workspace).resolve()) if controller._view.workspace else ''
        sources = []
        for saved in controller._sessions:
            saved_workspace = saved.get('workspace', '')
            if (str(Path(saved_workspace).resolve()) if saved_workspace else '') != workspace: continue
            if options.get('scope') == 'session' and saved['id'] != controller._view.id: continue
            title = saved['title'].casefold()
            include = [term.strip().casefold() for term in options.get('include', '').split(',') if term.strip()]
            exclude = [term.strip().casefold() for term in options.get('exclude', '').split(',') if term.strip()]
            if include and not any(term in title for term in include) or any(term in title for term in exclude): continue
            session = {key: saved.get(key, '') for key in ('id', 'title', 'file')}
            record = controller._pool.find(saved['id'])
            if record:
                session['leaf'] = record.search_leaf
                live = []
                for i, row in enumerate(record.messages):
                    if row.get('entryId') or not row.get('text'): continue
                    row.setdefault('_searchId', 'live:' + record.key + ':' + uuid.uuid4().hex)
                    live.append({'entryId': row['_searchId'], 'text': row['text'], 'role': row['role'], 'timestamp': row.get('timestamp'), 'sourceIndex': i})
                session['live'] = live
            sources.append(session)
        rg = controller.root / 'runtime/releases/coding-1.3.0/bin' / ('rg.exe' if os.name == 'nt' else 'rg')
        if not rg.is_file():
            self._busy, self._error = False, '未找到内置 ripgrep，请修复客户端安装'
            self.changed.emit(); return
        self._write({'type': 'search', 'id': self._generation, 'query': text, 'options': options,
                     'workspace': workspace, 'cache': str(controller.store.directory / 'cache/conversation-search-v1'),
                     'rg': str(rg), 'sessions': sources, 'maxResults': 20000})

    @Slot(int)
    def open(self, row):
        hit = self.item(row)
        if hit.get('kind') != 'match': return
        if hit.get('file') and not Path(hit['file']).is_file():
            self.controller.toast.emit('原消息已不可用，请刷新搜索'); self.jumpReady.emit(-1, ''); return
        self._jump = hit
        record = self.controller._pool.find(hit['sessionId'])
        if record and record.loaded:
            self._finish_jump()
        else:
            self._jump_token -= 1
            self.controller.sessionPreview.prepare(hit['sessionId'], self._jump_token)

    def _prepared(self, token, ok):
        if token != self._jump_token or not self._jump: return
        if ok and self.controller.sessionPreview.activate_read_only(token): self._finish_jump()
        else: self._jump = None; self.jumpReady.emit(-1, '')

    def _finish_jump(self):
        hit, self._jump = self._jump, None
        record = self.controller._pool.find(hit['sessionId'])
        if record is None:
            self.controller.toast.emit('原消息已不可用，请刷新搜索'); self.jumpReady.emit(-1, ''); return
        self.controller._activate(record)
        target = self.controller._chat_model.row_for_entry(hit['entryId'])
        if target < 0: self.controller.toast.emit('原消息已不可用，请刷新搜索')
        self.jumpReady.emit(target, hit['entryId'])

    def close(self):
        self._pump.stop()
        if self._worker:
            worker, self._worker = self._worker, None
            worker.blockSignals(True)
            worker.write(b'{"type":"cancel"}\n'); worker.closeWriteChannel()
            if not worker.waitForFinished(1000): worker.kill(); worker.waitForFinished(1000)
            worker.deleteLater()
