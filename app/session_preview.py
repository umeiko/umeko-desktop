"""Read cold transcripts off the UI thread; keep one reader and the latest request."""
from collections import OrderedDict
import copy
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from .transcripts import preview
from .pi_sessions import clean_extension_modes, clean_skill_modes, clean_blocked_tools


# About how long a click takes to show its conversation.
OPENING_SECONDS = 0.8
RECENT_MESSAGES = 120
PREFETCH_SECONDS = 15
PREFETCH_SESSIONS = 10


class SessionPreview(QObject):
    ready = Signal(int, bool)
    completed = Signal(object)

    def __init__(self, controller):
        super().__init__(controller)
        self.controller = controller
        self.request = 0
        self.pending = None
        self.prepared = None
        self.reading = False
        # Background indexing yields to the conversation being opened.
        self.busy_until = 0.0
        self.direct_token = 0
        self.epoch = 0
        self.warm = OrderedDict()
        self.speculative = OrderedDict()
        self.last_prefetch = OrderedDict()
        self.wheel_scrolling = False
        self.speculation_epoch = 0
        self.prefetch_timer = QTimer(self)
        self.prefetch_timer.setSingleShot(True)
        self.prefetch_timer.timeout.connect(self._start)
        self.completed.connect(self._completed)

    @Slot()
    def cancel(self):
        self.controller._cancel_pi_warmup()
        self.epoch += 1
        self.request = 0
        self.pending = self.prepared = None

    @Slot(str)
    def prefetch(self, session_id):
        now = time.monotonic()
        if now - self.last_prefetch.get(session_id, -PREFETCH_SECONDS) < PREFETCH_SECONDS:
            return
        saved = next((row for row in self.controller._sessions if row['id'] == session_id), None)
        if not saved or not saved.get('file') or saved.get('backend') == 'dsh':
            return
        record = self.controller._pool.find(session_id)
        if record and record.loaded and (record.busy or not record.transcript or record.transcript.matches_source()):
            return
        self.last_prefetch[session_id] = now
        self.last_prefetch.move_to_end(session_id)
        if len(self.last_prefetch) > 4 * PREFETCH_SESSIONS:
            self.last_prefetch.popitem(last=False)
        self.speculative[session_id] = dict(saved)
        self.speculative.move_to_end(session_id)
        if len(self.speculative) > PREFETCH_SESSIONS:
            self.speculative.popitem(last=False)
        self._start()

    @Slot()
    def prefetchRecent(self):
        for row in self.controller._sessions[:PREFETCH_SESSIONS]:
            self.prefetch(row['id'])

    @Slot(bool)
    def setWheelScrolling(self, active):
        if self.wheel_scrolling == active:
            return
        self.wheel_scrolling = active
        if active:
            # Let the viewport's history reader and layout finish during
            # the gesture before reading unrelated transcripts.
            self.speculation_epoch += 1
        else:
            self.prefetch_timer.start(0)

    @Slot(str, int)
    def prepare(self, session_id, token, recent=True):
        """Read a session for display. recent allows a long unindexed
        transcript to appear from its latest messages first."""
        self.cancel()
        self.request = token
        self.busy_until = time.monotonic() + OPENING_SECONDS
        saved = next((row for row in self.controller._sessions if row['id'] == session_id), None)
        if not saved:
            self.ready.emit(token, False)
            return
        saved = dict(saved)
        cached = self.controller._pool.find(session_id)
        partial = bool(cached and cached.transcript and cached.transcript.partial and not recent)
        if cached and cached.loaded and not partial and (cached.busy or not cached.transcript or cached.transcript.matches_source()):
            self.prepared = {'token': token, 'saved': saved}
            self.ready.emit(token, True)
            return
        snapshot = self.warm.pop(session_id, None)
        if snapshot is not None and snapshot.matches_source() and (recent or not snapshot.partial):
            self.prepared = {'token': token, 'saved': saved, 'snapshot': snapshot}
            self.ready.emit(token, True)
            return
        self.speculative.pop(session_id, None)
        view = self.controller._conversation_views.models.get(cached.key) if cached else None
        indexed = bool(view and view.snapshot and not view.snapshot.partial)
        self.pending = {'token': token, 'saved': saved, 'recent': recent and not indexed, 'epoch': self.epoch}
        self._start()

    def _start(self):
        if self.reading or self.controller._closing:
            return
        if self.pending:
            job, self.pending = self.pending, None
        elif self.speculative and not self.wheel_scrolling:
            remaining = self.busy_until - time.monotonic()
            if remaining > 0:
                self.prefetch_timer.start(max(1, int(remaining * 1000)))
                return
            _, saved = self.speculative.popitem(last=False)
            job = {'token': None, 'saved': saved, 'recent': True, 'epoch': self.epoch,
                   'speculation_epoch': self.speculation_epoch}
        else:
            return
        self.reading = True
        def read():
            result = dict(job)
            try:
                saved = job['saved']
                file = saved.get('file')
                if file:
                    repository = self.controller.transcripts
                    def cancelled():
                        return (self.epoch != job['epoch'] or self.controller._closing
                                or (job['token'] is None and job['speculation_epoch'] != self.speculation_epoch))
                    snapshot = None
                    if job['recent'] and repository.large(file) and not repository.current(file):
                        snapshot = repository.open_recent(file, cancelled=cancelled, messages=RECENT_MESSAGES)
                    result['snapshot'] = snapshot or repository.open(file, cancelled=cancelled)
                else:
                    result['messages'], result['tree'] = preview(file) if file else (copy.deepcopy(saved.get('messages', [])), [])
            except Exception:
                result['error'] = True
            try:
                self.completed.emit(result)
            except RuntimeError:
                pass  # A closing window can release the QObject before disk I/O ends.
        threading.Thread(target=read, daemon=True).start()

    @Slot(object)
    def _completed(self, result):
        self.reading = False
        if self.controller._closing:
            return
        if result['epoch'] == self.epoch and result['token'] is None:
            snapshot = result.get('snapshot')
            if snapshot is not None and snapshot.matches_source():
                key = result['saved']['id']
                self.warm[key] = snapshot
                self.warm.move_to_end(key)
                if len(self.warm) > PREFETCH_SESSIONS:
                    self.warm.popitem(last=False)
            elif result['speculation_epoch'] != self.speculation_epoch and len(self.speculative) < PREFETCH_SESSIONS:
                saved = result['saved']
                self.speculative.setdefault(saved['id'], saved)
        elif result['epoch'] == self.epoch and result['token'] == self.request:
            # A slow foreground read can outlast the quiet period established
            # at the click. Give its newly attached view the same idle window
            # before speculative transcript reads resume.
            self.busy_until = time.monotonic() + OPENING_SECONDS
            if result.get('error'):
                self.controller.toast.emit('聊天记录暂时无法读取，请稍后重试')
            else:
                self.prepared = result
            self.ready.emit(result['token'], not result.get('error', False))
            if result['token'] == self.direct_token and not result.get('error', False):
                self.activate(result['token'])
        self._start()

    @Slot(int, result=bool)
    def activate(self, token, read_only=False):
        result = self.prepared
        if not result or token != self.request or result['token'] != token:
            return False
        saved = next((row for row in self.controller._sessions if row['id'] == result['saved']['id']), None)
        if not saved:
            return False
        self.busy_until = time.monotonic() + OPENING_SECONDS
        record = self.controller._pool.find(saved['id'])
        if not record or not record.loaded or 'snapshot' in result or 'messages' in result:
            fresh = record is None
            record = record or self.controller._new_view(saved.get('workspace', ''))
            record.id, record.file, record.title = saved['id'], saved.get('file', ''), saved['title']
            record.extension_modes = clean_extension_modes(self.controller.store.data['sessionMeta'].get(saved['id'],{}).get('extensionModes'))
            record.skill_modes = clean_skill_modes(self.controller.store.data['sessionMeta'].get(saved['id'],{}).get('skillModes'))
            record.blocked_tools = clean_blocked_tools(self.controller.store.data['sessionMeta'].get(saved['id'],{}).get('blockedTools'))
            record.pi_capabilities = self.controller.store.data['sessionMeta'].get(saved['id'],{}).get('piCapabilities') or {}
            record.history = copy.deepcopy(saved.get('history', []))
            record.messages, record.tree = result.get('messages', []), result.get('tree', [])
            record.transcript, record.loaded = result.get('snapshot'), True
            record.body_dirty = True
            record.model = saved.get('model') or record.model
            record.provider = saved.get('provider') or record.provider
            if fresh:
                record.reasoning_effort = self.controller.store.data['sessionMeta'].get(saved['id'], {}).get('reasoningEffort', record.reasoning_effort)
            # Register before activation; trimming it while the old view is
            # still pinned could immediately evict this prepared selection.
            self.controller._pool.records[record.key] = record
            record.history_pending, record.history_wanted = None, False
        self.cancel()
        if read_only:
            self.controller._activate(record)
        else:
            self.controller.openSession(saved['id'])
        return True

    def activate_read_only(self, token):
        return self.activate(token, read_only=True)

    def open_direct(self, session_id):
        self.direct_token -= 1
        self.prepare(session_id, self.direct_token)
        # A warm result is ready synchronously and never visits _completed.
        if self.prepared is not None:
            self.activate(self.direct_token)
