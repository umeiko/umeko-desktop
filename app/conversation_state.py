"""Session-bound presentation state for non-main native conversations."""
import copy
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from .conversation_views import ConversationViews
from pathlib import Path
from PySide6.QtCore import QObject, Property, Signal, Slot
from .chat_model import ChatModel
from .transcripts import preview


class ConversationState(QObject):
    chatChanged = Signal()
    transcriptChanged = Signal()
    viewChanged = Signal()
    loaded = Signal(object)

    def __init__(self, backend, parent=None, model=None):
        super().__init__(parent or backend)
        self.b = backend
        self.views = ConversationViews(self, capacity=3) if model is None else None
        self.model = model if model is not None else self.views.select("")
        self.file_cache = OrderedDict()
        self._file_reader = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-history")
        self._file_job = None
        self.token = ''
        self.anchor, self.offset, self.follow = -1, 0.0, True
        self.viewports = {}
        self.busy_value, self.status, self.usage = False, '', {}
        self.bounded_history = False
        self.available, self.loading_value, self.error_value = False, False, ''
        self.compact = lambda: None
        self.submit = lambda text: False
        self._covered_ids = frozenset()
        self._live_messages = []
        self._generation = 0
        self._closed = False
        self.loaded.connect(self._loaded)
        self.model.rowsInserted.connect(self.chatChanged)
        self.model.modelReset.connect(self.chatChanged)

    messageModel = Property(QObject, lambda self: self.model, notify=viewChanged)
    messageCount = Property(int, lambda self: self.model.rowCount(), notify=chatChanged)
    viewKey = Property(str, lambda self: self.token, notify=viewChanged)
    scrollAnchor = Property(int, lambda self: self.anchor, notify=viewChanged)
    scrollPosition = Property(float, lambda self: self.offset, notify=viewChanged)
    followTail = Property(bool, lambda self: self.follow, notify=viewChanged)
    busy = Property(bool, lambda self: self.busy_value, notify=chatChanged)
    running = Property(bool, lambda self: self.busy_value, notify=chatChanged)
    toolStatus = Property(str, lambda self: self.status, notify=chatChanged)
    turnStatus = Property('QVariantMap', lambda self: {'state': 'running' if self.busy_value else 'finished'}, notify=chatChanged)
    contextUsage = Property('QVariantMap', lambda self: self.usage, notify=chatChanged)
    compactionAvailable = Property(bool, lambda self: self.available, notify=chatChanged)
    activeSession = Property(bool, lambda self: bool(self.token), notify=chatChanged)
    sessionBackend = Property(str, lambda self: 'pi', constant=True)
    loading = Property(bool, lambda self: self.loading_value, notify=chatChanged)
    error = Property(str, lambda self: self.error_value, notify=chatChanged)

    def switch_to(self, key):
        if self.token == key:
            return
        if self.token:
            self.viewports[self.token] = (self.anchor, self.offset, self.follow)
        if len(self.viewports) > 64:
            self.viewports.pop(next(iter(self.viewports)))
        self._generation += 1
        self.token = key
        self.anchor, self.offset, self.follow = self.viewports.get(key, (-1, 0.0, True))
        self.usage, self.available = {}, False
        self.busy_value, self.status, self.loading_value, self.error_value = False, "", False, ""
        self._covered_ids = frozenset()
        self._live_messages = []
        if self.views:
            self.model = self.views.select(key)
        else:
            self.model.set_snapshot(None)
            self.model.update([])
        self.chatChanged.emit()
        self.viewChanged.emit()

    @Slot(int, float, bool)
    def saveViewport(self, index, offset, follow):
        if index >= 0:
            self.anchor, self.offset, self.follow = index, max(0.0, offset), follow

    @Slot(int, result='QVariantMap')
    def displayMessage(self, row):
        return self.model.message(row, synchronous=True)

    @Slot(str)
    def copy(self, text):
        self.b.copy(text)

    @Slot(int)
    def copyDisplayMessage(self, row):
        message = self.displayMessage(row)
        prose = '\n\n'.join(item['text'] for item in message.get('activity', []) if item.get('kind') == 'text')
        self.b.copy(prose or message.get('text', ''))

    @Slot(str)
    def copyChatSelection(self, raw):
        import json
        from .chat_copy import selected_text
        selection = json.loads(raw)
        snapshot, overlay = self.model.snapshot, copy.deepcopy(self.model.rows)
        script = (self.b.root / 'app/qml/markdown.js').read_text(encoding='utf-8')
        self.b._copy_chat(lambda: selected_text(script, snapshot, overlay, selection['anchor'], selection['cursor'], selection.get('expanded', {})))

    @Slot()
    def compactSession(self):
        if self.available and not self.busy_value:
            self.compact()

    @Slot(str, result=bool)
    def send(self, text):
        return bool(self.submit(text))

    def update(self, messages):
        self._live_messages = messages
        if self.bounded_history:
            messages = ChatModel.recent_compaction_interval(messages)
        if self._covered_ids:
            messages = [row for row in messages if row.get("entryId") not in self._covered_ids]
        self.model.update(messages)
        self.chatChanged.emit()

    def load(self, path):
        self._generation += 1
        generation = self._generation
        self.loading_value, self.error_value = True, ''
        self.chatChanged.emit()
        def read():
            result = {'generation': generation}
            try:
                if not Path(path).is_file():
                    raise OSError('会话文件已不存在')
                stat = Path(path).stat()
                signature = (str(path), stat.st_size, stat.st_mtime_ns)
                cached = self.file_cache.get(signature)
                if cached is not None:
                    result.update(cached)
                elif self.b.transcripts.large(path):
                    result['snapshot'] = self.b.transcripts.open(path, cancelled=lambda: self._closed or generation != self._generation)
                    if self.bounded_history:
                        result['snapshot'] = result['snapshot'].recent_compaction_interval()
                    from .transcript_index import connect
                    with connect(result['snapshot'].database) as db:
                        result['covered_ids'] = frozenset(row[0] for row in db.execute('SELECT id FROM native'))
                else:
                    result['messages'], _ = preview(path)
                    if self.bounded_history:
                        result['messages'] = ChatModel.recent_compaction_interval(result['messages'])
                result['signature'] = signature
            except Exception as error:
                result['error'] = str(error)
            if not self._closed:
                self.loaded.emit(result)
        if self._file_job is not None: self._file_job.cancel()
        self._file_job = self._file_reader.submit(read)

    @Slot(object)
    def _loaded(self, result):
        if self._closed or result['generation'] != self._generation:
            return
        self.loading_value, self.error_value = False, result.get('error', '')
        if 'signature' in result:
            self.file_cache[result['signature']] = {k:result[k] for k in ('snapshot','messages','covered_ids') if k in result}
            while len(self.file_cache) > 3:
                self.file_cache.popitem(last=False)
        snapshot = result.get('snapshot')
        if snapshot and self.model.snapshot and snapshot.row_offset > self.model.snapshot.row_offset:
            self.file_cache.clear()
            cache = self.views.presentation.cache
            with cache.lock:
                cache.items.clear(); cache.pinned.clear(); cache.weight = 0
            self.anchor, self.offset, self.follow = -1, 0.0, True
        self._covered_ids = result.get('covered_ids', frozenset())
        self.model.set_snapshot(snapshot)
        if snapshot:
            self.update(self._live_messages)
        else:
            self.update(result.get('messages', []))
        self.viewChanged.emit()

    def close(self):
        self._closed = True
        self._file_reader.shutdown(wait=False, cancel_futures=True)
        self._generation += 1
        if self.views:
            self.views.close()
        else:
            self.model.close()
