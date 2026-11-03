"""Stable message rows: streaming updates never reset the conversation list."""
import copy
import re
from bisect import bisect_left, bisect_right
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Property, Signal, Slot
from .message_attachments import split_attachments
from .chatbox import media_view

RENDER_ROWS = 4


class ChatModel(QAbstractListModel):
    MessageRole = Qt.UserRole + 1
    questionsChanged = Signal()
    sourceChanged = Signal()
    pageReady = Signal(object)
    viewportAboutToChange = Signal()
    viewportChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self._questions = []
        self._source_starts = []
        self._source_count = 0
        self._source = None
        self.snapshot = None
        self._generation = 0
        self._pending, self._failed = set(), set()
        self._wanted, self._prepared, self._job = [], {}, None
        from .chat_presentation import HistoryPresentation
        self._presentation = HistoryPresentation()
        self._session_key, self._render_context = None, None
        self._render_cache, self._live_prepared = None, {}
        self._cache_enabled, self._streaming = False, False
        self._binding_changed = False
        self._snapshot_sources = {}
        self._metadata, self._heights = OrderedDict(), OrderedDict()
        self._layout = ''
        self._closed = False
        self._reader = ThreadPoolExecutor(max_workers=1, thread_name_prefix='chat-pages')
        self.pageReady.connect(self._page_ready)

    def set_session(self, key, context, streaming=False, enabled=True):
        """Bind render retention to the controller's existing session pool."""
        changed = (key != self._session_key or context != self._render_context
                   or enabled != self._cache_enabled or streaming != self._streaming)
        binding_changed = key != self._session_key
        self._binding_changed |= binding_changed
        if binding_changed:
            self._wanted = []
            self._source = None
        if not enabled:
            self._presentation.discard_session(key)
            self._snapshot_sources.pop(key, None)
        self._session_key = key
        self._render_context = copy.deepcopy(context)
        self._cache_enabled, self._streaming = bool(enabled), bool(streaming)
        self._render_cache = self._presentation.session_cache(key, context) if enabled else None
        if streaming and not binding_changed and self._source_starts:
            for offset, start in enumerate(self._source_starts):
                if start == self._source_starts[-1]:
                    self._presentation.invalidate(self._render_cache, self.base_count + offset, self.base_count + offset)
        if changed:
            self._generation += 1
            self._pending.clear()
            self._failed.clear()
            self._prepared.clear()
            self._live_prepared.clear()
            self._heights.clear()
            if self.rowCount():
                self.dataChanged.emit(self.index(0), self.index(self.rowCount() - 1), [self.MessageRole])
            if not binding_changed and enabled:
                self._pump()

    def discard_session(self, key):
        self._presentation.discard_session(key)
        self._snapshot_sources.pop(key, None)
        if key == self._session_key:
            self._wanted = []
            self.set_session(key, self._render_context, self._streaming, False)

    def clear(self):
        self._generation += 1
        self._presentation.clear()
        self._snapshot_sources.clear()
        self._render_cache = None
        self._cache_enabled = False
        self._prepared.clear()
        self._live_prepared.clear()

    def _live_renderable(self, row):
        offset = row - self.base_count
        if not self._cache_enabled or not 0 <= offset < len(self.rows):
            return False
        # A native assistant may project into many fragments or a grouped tool
        # chain. Every fragment of that final source group remains live.
        if (self._streaming and self._source_starts
                and (offset >= len(self._source_starts) or self._source_starts[offset] == self._source_starts[-1])):
            return False
        return bool(self._presentation.signature(self.rows[offset]))

    def _loading(self, row, meta):
        return {'role': meta.get('role', 'assistant'), 'text': '', 'error': False, '_loading': True,
                '_loadError': row // RENDER_ROWS in self._failed,
                '_estimatedHeight': self._heights.get(row, meta.get('hint', 100))}

    @Property(bool, notify=sourceChanged)
    def paged(self):
        return self.snapshot is not None

    @property
    def base_count(self):
        return self.snapshot.count if self.snapshot else 0

    @Property(int, notify=questionsChanged)
    def questionCount(self):
        return (self.snapshot.question_count if self.snapshot else 0) + len(self._questions)

    @Slot(int, result='QVariantMap')
    def question(self, index):
        base = self.snapshot.question_count if self.snapshot else 0
        if index < base:
            return self.snapshot.question(index)
        return self._questions[index - base] if 0 <= index - base < len(self._questions) else {}

    @Slot(int, result=int)
    def questionIndexForRow(self, row):
        base = self.snapshot.question_count if self.snapshot else 0
        if row < self.base_count:
            return self.snapshot.question_index(row)
        selected = bisect_right([value['row'] for value in self._questions], row) - 1
        return base + selected if selected >= 0 else max(0, base - 1)

    def set_snapshot(self, snapshot):
        revised = False
        if snapshot is not None and self._cache_enabled:
            identity = (getattr(snapshot, 'database', None) or getattr(snapshot, 'file', None)
                        or getattr(snapshot, 'path', None) or id(snapshot))
            source = str(identity), getattr(snapshot, 'revision', None), snapshot.count
            previous = self._snapshot_sources.get(self._session_key)
            revised = previous is not None and previous != source
            if revised:
                self._generation += 1
                self._presentation.invalidate(self._render_cache, 0)
            self._snapshot_sources[self._session_key] = source
        if self.snapshot is snapshot and not revised:
            return
        self.beginResetModel()
        if self.snapshot:
            self.snapshot.repository.cache.pin(())
        if not revised:
            self._generation += 1
        self._pending.clear()
        self._failed.clear()
        self._prepared.clear()
        self._live_prepared.clear()
        self._wanted = []
        self._metadata.clear()
        self._heights.clear()
        self.snapshot = snapshot
        self.rows, self._questions, self._source_starts = [], [], []
        self._source, self._source_count = None, 0
        if snapshot and snapshot.count:
            focus = snapshot.focus_row if snapshot.focus_row >= 0 else snapshot.count - 1
            self.requestRange(focus, focus)
        self.endResetModel()
        self.sourceChanged.emit()
        self.questionsChanged.emit()

    @Slot(int, int)
    def requestRange(self, first, last):
        if self._closed or (not self.snapshot and not self._cache_enabled):
            return
        first, last = max(0, first), min(self.rowCount() - 1, max(first, last))
        if first > last:
            return
        last = min(last, first + 32)
        visible = list(range(first // RENDER_ROWS, last // RENDER_ROWS + 1))
        neighbors = [visible[-1] + 1, visible[0] - 1]
        pages = visible + [p for p in neighbors if 0 <= p <= (self.rowCount() - 1) // RENDER_ROWS]
        self._wanted = pages
        self._prepared = {row:value for row,value in self._prepared.items() if row // RENDER_ROWS in pages}
        self._live_prepared = {row:value for row,value in self._live_prepared.items() if row // RENDER_ROWS in pages}
        if self.snapshot:
            self.snapshot.repository.cache.pin(self.snapshot.key(row) for row in range(max(0, first - 8), min(self.base_count, last + 9)))
        self._pump()

    def _request(self, page):
        if page not in self._wanted:
            return
        self._pump()

    def _pump(self):
        if self._closed or self._job is not None or (not self.snapshot and not self._cache_enabled):
            return
        def ready(row):
            return row in self._prepared if row < self.base_count else (not self._live_renderable(row) or row in self._live_prepared)
        page = next((p for p in self._wanted if p not in self._failed and not all(
            ready(row) for row in range(p * RENDER_ROWS, min(self.rowCount(), (p + 1) * RENDER_ROWS)))), None)
        if page is None:
            return
        snapshot, generation = self.snapshot, self._generation
        first, last, base_count = page * RENDER_ROWS, min(self.rowCount(), (page + 1) * RENDER_ROWS), self.base_count
        live = {row: copy.deepcopy(self.rows[row - base_count]) for row in range(max(base_count, first), last)
                if self._live_renderable(row)}
        cache = self._render_cache
        use_default = self._session_key is None
        self._job = generation, page
        self._pending.add(page)
        def read():
            from .transcript_index import PAGE_ROWS
            cancelled = lambda: self._closed or generation != self._generation or page not in self._wanted
            if cancelled(): return {}
            rows = {}
            if snapshot and first < base_count:
                rows = snapshot.page(first // PAGE_ROWS)
                rows = {row:value for row,value in rows.items() if first <= row < min(last, base_count)}
            rows.update(live)
            return self._presentation.prepare(rows, cancelled, cache=cache, use_default=use_default)
        future = self._reader.submit(read)
        def complete(job):
            try:
                prepared = job.result()
                error = False
            except Exception:
                prepared = {}
                error = True
            try:
                if not self._closed:
                    self.pageReady.emit((generation, page, error, prepared))
            except RuntimeError:
                pass
        future.add_done_callback(complete)

    @Slot(object)
    def _page_ready(self, value):
        generation, page, error, prepared = value
        self._job = None
        self._pending.discard(page)
        if self._closed or generation != self._generation:
            self._pump()
            return
        if page not in self._wanted:
            self._pump()
            return
        if error:
            self._failed.add(page)
        self._prepared.update((row, value) for row, value in prepared.items() if row < self.base_count)
        self._live_prepared.update((row, value) for row, value in prepared.items() if row >= self.base_count)
        first, last = page * RENDER_ROWS, min(self.rowCount() - 1, (page + 1) * RENDER_ROWS - 1)
        self.viewportAboutToChange.emit()
        self.dataChanged.emit(self.index(first), self.index(last), [self.MessageRole])
        self.viewportChanged.emit()
        self._pump()

    @Slot(int)
    def retryPage(self, row):
        page = row // RENDER_ROWS
        self._failed.discard(page)
        self.requestRange(row, row)

    @Slot(int, result=bool)
    def isReady(self, row):
        if row >= self.base_count:
            return (not self._live_renderable(row) or row in self._live_prepared
                    or row // RENDER_ROWS in self._failed)
        if not self.snapshot or row < 0:
            return True
        return row in self._prepared or row // RENDER_ROWS in self._failed

    @Slot(int, float)
    def recordHeight(self, row, height):
        if not self.snapshot or not 0 <= row < self.base_count or not 0 < height < 10000000:
            return
        self._heights[row] = height
        self._heights.move_to_end(row)
        while len(self._heights) > 2048:
            self._heights.popitem(last=False)

    @Slot(str)
    def setLayout(self, key):
        if key != self._layout:
            self._layout = key
            self._heights.clear()

    def message(self, row, synchronous=False):
        if row >= self.base_count:
            if not 0 <= row - self.base_count < len(self.rows):
                return {}
            value = self.rows[row - self.base_count]
            if synchronous or not self._live_renderable(row):
                return value
            prepared = self._live_prepared.get(row)
            if prepared is None:
                prepared = self._presentation.cached(row, value, self._render_cache)
                if prepared is not None and row // RENDER_ROWS in self._wanted:
                    self._live_prepared[row] = prepared
            if prepared is not None:
                return prepared
            self._request(row // RENDER_ROWS)
            # Preserve raw fallback if worker preparation failed.
            return value if row // RENDER_ROWS in self._failed else self._loading(row, value)
        if not self.snapshot or row < 0:
            return {}
        value = self._prepared.get(row)
        if value is not None:
            return value
        if synchronous:
            return self.snapshot.row(row)
        self._request(row // RENDER_ROWS)
        meta = self._metadata.get(row)
        if meta is None:
            meta = self.snapshot.metadata(row)
            self._metadata[row] = meta
            while len(self._metadata) > 192:
                self._metadata.popitem(last=False)
        return self._loading(row, meta)

    def close(self):
        self._closed = True
        self.clear()
        self._reader.shutdown(wait=False, cancel_futures=True)

    @Property('QVariantList', notify=questionsChanged)
    def questions(self):
        return self._questions

    def roleNames(self):
        return {self.MessageRole: b"modelData"}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self.base_count + len(self.rows)

    def data(self, index, role=Qt.DisplayRole):
        if index.isValid() and role == self.MessageRole and index.row() < self.rowCount():
            return self.message(index.row())

    def update(self, messages, dirty_from=None):
        source = messages
        first = start = 0
        if dirty_from is not None and self._source is source and self._source_starts and len(source) >= self._source_count:
            # An appended terminal transition belongs to the event's first row,
            # even if ordinary conversation now separates those transitions.
            events = {value.get('compaction', {}).get('eventId') for value in source[dirty_from:]
                      if value.get('customType') == 'umeko-compaction' and value.get('compaction', {}).get('version') == 2}
            if events:
                dirty_from = min(dirty_from, next((index for index, value in enumerate(source[:dirty_from])
                    if value.get('customType') == 'umeko-compaction' and value.get('compaction', {}).get('eventId') in events), dirty_from))
            first = max(0, bisect_right(self._source_starts, min(dirty_from, self._source_count - 1)) - 1)
            start = self._source_starts[first]
            first = bisect_left(self._source_starts, start)
        projected, native_starts = self.project(source[start:], with_starts=True, max_group=16)
        from .transcript_index import display_fragments
        messages, starts = [], []
        for row, native in zip(projected, native_starts):
            pieces = list(display_fragments(row))
            for part, piece in enumerate(pieces):
                if len(pieces) > 1:
                    piece = {**piece, '_chunked':True, 'continuation':bool(row.get('continuation')) or part > 0, 'segmentLast':part == len(pieces) - 1}
                messages.append(piece)
                starts.append(native)
        del self._source_starts[first:]
        self._source_starts.extend(start + value for value in starts)
        self._source, self._source_count = source, len(source)
        total = first + len(messages)
        changed_rows = {row for row in range(first, min(total, len(self.rows))) if self.rows[row] != messages[row - first]}
        if changed_rows or total != len(self.rows):
            self._generation += 1
            self._failed.clear()
            for row in changed_rows:
                absolute = self.base_count + row
                self._live_prepared.pop(absolute, None)
                if not self._binding_changed:
                    self._presentation.invalidate(self._render_cache, absolute, absolute)
            self._presentation.invalidate(self._render_cache, self.base_count + total)
            self._live_prepared = {row:value for row,value in self._live_prepared.items() if row < self.base_count + total}
        questions_dirty = total != len(self.rows)
        for row in range(first, min(total, len(self.rows))):
            value = messages[row - first]
            if row in changed_rows:
                questions_dirty |= self.rows[row].get('role') == 'user' or value.get('role') == 'user'
                self.rows[row] = copy.deepcopy(value)
                self.dataChanged.emit(self.index(self.base_count + row), self.index(self.base_count + row), [self.MessageRole])
        if total > len(self.rows):
            self.beginInsertRows(QModelIndex(), self.base_count + len(self.rows), self.base_count + total - 1)
            self.rows.extend(copy.deepcopy(messages[len(self.rows) - first:]))
            self.endInsertRows()
        elif total < len(self.rows):
            self.beginRemoveRows(QModelIndex(), self.base_count + total, self.base_count + len(self.rows) - 1)
            del self.rows[total:]
            self.endRemoveRows()
        if questions_dirty:
            questions = []
            for row, message in enumerate(self.rows):
                if message.get('role') != 'user' or message.get('continuation'):
                    continue
                title = message.get('text', '').strip() or '、'.join(a.get('name', '') for a in message.get('attachments', [])) or '…'
                questions.append({'row': self.base_count + row, 'title': re.sub(r'\s+', ' ', title[:500])})
            if questions != self._questions:
                self._questions = questions
                self.questionsChanged.emit()
        if self._cache_enabled and self.rowCount():
            if not self._wanted:
                self.requestRange(max(0, self.rowCount() - RENDER_ROWS), self.rowCount() - 1)
            else:
                self._pump()
        self._binding_changed = False

    def row_for_entry(self, entry_id):
        if self.snapshot:
            from .transcript_index import connect
            with connect(self.snapshot.database) as db:
                revision = db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()
                if revision is None or int(revision[0]) != self.snapshot.revision:
                    return -1
                row = db.execute('''SELECT d.seq FROM native n JOIN display d
                    ON n.pos BETWEEN d.first_native AND d.last_native WHERE n.id=? ORDER BY d.seq LIMIT 1''', (entry_id,)).fetchone()
                if row is not None:
                    return row[0]
        for row, message in enumerate(self.rows):
            if entry_id in message.get('_entries', []) or entry_id == message.get('entryId'):
                return self.base_count + row
        return -1

    @staticmethod
    def project(messages, with_starts=False, max_group=None):
        """Keep ordered process steps under one assistant, leaving Pi's log intact."""
        rows, starts, compactions = [], [], {}
        for source_index, message in enumerate(messages):
            current = dict(message)
            current['_entries'] = [value for value in (message.get('entryId'), message.get('_searchId')) if value]
            if current.get('customType') == 'umeko-compaction':
                current.pop('activity', None)
                details = current.get('compaction', {})
                if details.get('version') == 2:
                    current['text'] = ''
                    previous = compactions.get(details.get('eventId'))
                    if previous is not None:
                        previous['compaction'] = dict(details)
                        continue
                    compactions[details.get('eventId')] = current
            if current.get("role") == "user":
                current["text"], attachments = split_attachments(current.get("text", ""))
                if attachments:
                    current["attachments"] = attachments
            if current.get("role") == "assistant" and current.get("customType") != "umeko-compaction":
                # Native failures can contain both partial output and a separate
                # errorMessage. Keep both; the report ID belongs to the failure.
                failure = current.get('errorMessage', '') if current.get('stopReason') != 'aborted' else ''
                if not failure and current.get('error'):
                    failure = current['error'] if isinstance(current['error'], str) else current.get('text', '')
                marker = re.search(r'\[Umeko:([a-f0-9-]{36})\]', failure)
                if marker:
                    current['diagnosticId'] = marker[1]
                if marker:
                    from .provider_errors import diagnostic_notice
                    notice = diagnostic_notice(failure)
                else:
                    notice = failure
                body = current.get('text', '')
                if body == failure:
                    body = ''
                if notice:
                    current['text'] = body or notice
                    current['error'] = True
                steps = []
                if current.get("thinking"):
                    steps.append({"kind": "thinking", "text": current["thinking"]})
                if body:
                    steps.append({"kind": "text", "text": body, "error": False})
                if current.get("tools"):
                    current["tools"] = [dict(tool) for tool in current["tools"]]
                    batch = []
                    for tool in current["tools"]:
                        if tool.get("subagent"):
                            if batch:
                                steps.append({"kind": "tools", "tools": batch})
                                batch = []
                            if steps and steps[-1]["kind"] == "subagents":
                                steps[-1]["agents"].append(dict(tool["subagent"]))
                            else:
                                steps.append({"kind": "subagents", "agents": [dict(tool["subagent"])]})
                            continue
                        batch.append(tool)
                        if tool.get("name") in ("submit_to_chatbox", "image_gen", "voice_gen", "video_gen") and tool.get("media"):
                            steps.append({"kind": "tools", "tools": batch})
                            steps.append({"kind": "media", "items": media_view(tool["media"]), "toolId": tool["id"]})
                            batch = []
                    if batch: steps.append({"kind": "tools", "tools": batch})
                if notice:
                    steps.append({"kind": "text", "text": notice, "error": True})
                current["activity"] = steps
            continuing = bool(rows and rows[-1].get('stopReason') == 'length' and not current.get('error'))
            merging = bool(rows and current.get("role") == rows[-1].get("role") == "assistant"
                    and current.get("customType") != "umeko-compaction" and rows[-1].get("customType") != "umeko-compaction"
                    and (continuing or rows[-1].get("tools") or rows[-1].get('_chain_tools') or current.get("tools")))
            if merging and (max_group is None or source_index - starts[-1] < max_group):
                group = rows[-1]
                group['_entries'] = group.get('_entries', []) + current['_entries']
                if current.get('diagnosticId'): group['diagnosticId'] = current['diagnosticId']
                steps = current["activity"]
                if continuing:
                    # Keep a code fence/table/word continuous across output limits.
                    # Only join prose after the last completed tool/media step.
                    tail, head = [], []
                    while group['activity'] and group['activity'][-1]['kind'] in ('thinking', 'text'):
                        tail.insert(0, group['activity'].pop())
                    while steps and steps[0]['kind'] in ('thinking', 'text'):
                        head.append(steps.pop(0))
                    for kind in ('thinking', 'text'):
                        text = ''.join(step['text'] for step in tail + head if step['kind'] == kind)
                        if text:
                            group['activity'].append({'kind':kind, 'text':text, **({'error':False} if kind == 'text' else {})})
                # Adjacent operations with no intervening prose share a batch.
                if group["activity"] and steps and group["activity"][-1]["kind"] == steps[0]["kind"] and steps[0]["kind"] in ("tools", "subagents"):
                    field = "tools" if steps[0]["kind"] == "tools" else "agents"
                    group["activity"][-1][field] = group["activity"][-1][field] + steps[0][field]
                    steps = steps[1:]
                group["activity"].extend(steps)
                group["tools"] = group.get("tools", []) + current.get("tools", [])
                group["text"] = (group.get('text', '') if continuing else '') + current.get("text", "")
                group["error"] = group.get("error", False) or current.get("error", False)
                group["stopReason"] = current.get("stopReason", "")
                if current.get("timestamp"): group["timestamp"] = current["timestamp"]
            else:
                if merging:
                    current['continuation'] = True
                    current['_chain_tools'] = bool(rows[-1].get('tools') or rows[-1].get('_chain_tools') or current.get('tools'))
                    rows[-1]['segmentLast'] = False
                rows.append(current)
                starts.append(source_index)
        for row in rows:
            for index, step in enumerate(row.get("activity", [])):
                step["blockOffset"] = index * 10000
        return (rows, starts) if with_starts else rows
