"""Stable message rows: streaming updates never reset the conversation list."""
import copy
import re
from bisect import bisect_left, bisect_right
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Property, Signal, Slot
from .message_attachments import split_attachments
from .chatbox import media_view


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
        self._metadata, self._heights = OrderedDict(), OrderedDict()
        self._layout = ''
        self._closed = False
        self._reader = ThreadPoolExecutor(max_workers=1, thread_name_prefix='chat-pages')
        self.pageReady.connect(self._page_ready)

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
        if self.snapshot is snapshot:
            return
        self.beginResetModel()
        if self.snapshot:
            self.snapshot.repository.cache.pin(())
        self._generation += 1
        self._pending.clear()
        self._failed.clear()
        self._metadata.clear()
        self._heights.clear()
        self.snapshot = snapshot
        self.rows, self._questions, self._source_starts = [], [], []
        self._source, self._source_count = None, 0
        self.endResetModel()
        self.sourceChanged.emit()
        self.questionsChanged.emit()

    @Slot(int, int)
    def requestRange(self, first, last):
        if not self.snapshot or self._closed:
            return
        from .transcript_index import PAGE_ROWS
        first, last = max(0, first), min(self.base_count - 1, max(first, last))
        if first > last:
            return
        pages = range(max(0, first // PAGE_ROWS - 1), min((self.base_count - 1) // PAGE_ROWS, last // PAGE_ROWS + 1) + 1)
        self.snapshot.repository.cache.pin(self.snapshot.key(row) for row in range(max(0, first - 8), min(self.base_count, last + 9)))
        for page in pages:
            self._request(page)

    def _request(self, page):
        from .transcript_index import PAGE_ROWS
        if self._closed or page in self._pending or page in self._failed or not self.snapshot:
            return
        snapshot, generation = self.snapshot, self._generation
        if all(snapshot.cached(row) is not None for row in range(page * PAGE_ROWS, min(self.base_count, (page + 1) * PAGE_ROWS))):
            return
        self._pending.add(page)
        future = self._reader.submit(snapshot.page, page)
        def complete(job):
            try:
                job.result()
                error = False
            except Exception:
                error = True
            try:
                if not self._closed:
                    self.pageReady.emit((generation, page, error))
            except RuntimeError:
                pass
        future.add_done_callback(complete)

    @Slot(object)
    def _page_ready(self, value):
        generation, page, error = value
        if self._closed or generation != self._generation or not self.snapshot:
            return
        from .transcript_index import PAGE_ROWS
        self._pending.discard(page)
        if error:
            self._failed.add(page)
        first, last = page * PAGE_ROWS, min(self.base_count - 1, (page + 1) * PAGE_ROWS - 1)
        self.viewportAboutToChange.emit()
        self.dataChanged.emit(self.index(first), self.index(last), [self.MessageRole])
        self.viewportChanged.emit()

    @Slot(int)
    def retryPage(self, row):
        from .transcript_index import PAGE_ROWS
        page = row // PAGE_ROWS
        self._failed.discard(page)
        self._request(page)

    @Slot(int, result=bool)
    def isReady(self, row):
        if not self.snapshot or row >= self.base_count or row < 0:
            return True
        from .transcript_index import PAGE_ROWS
        return self.snapshot.cached(row) is not None or row // PAGE_ROWS in self._failed

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
            return self.rows[row - self.base_count] if 0 <= row - self.base_count < len(self.rows) else {}
        if not self.snapshot or row < 0:
            return {}
        value = self.snapshot.cached(row)
        if value is not None:
            return value
        if synchronous:
            return self.snapshot.row(row)
        from .transcript_index import PAGE_ROWS
        self._request(row // PAGE_ROWS)
        meta = self._metadata.get(row)
        if meta is None:
            meta = self.snapshot.metadata(row)
            self._metadata[row] = meta
            while len(self._metadata) > PAGE_ROWS * 8:
                self._metadata.popitem(last=False)
        return {'role': meta.get('role', 'assistant'), 'text': '', 'error': False, '_loading': True,
                '_loadError': row // PAGE_ROWS in self._failed, '_estimatedHeight': self._heights.get(row, meta.get('hint', 100))}

    def close(self):
        self._closed = True
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
        questions_dirty = total != len(self.rows)
        for row in range(first, min(total, len(self.rows))):
            value = messages[row - first]
            if self.rows[row] != value:
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

    @staticmethod
    def project(messages, with_starts=False, max_group=None):
        """Keep ordered process steps under one assistant, leaving Pi's log intact."""
        rows, starts = [], []
        for source_index, message in enumerate(messages):
            current = dict(message)
            if current.get("role") == "user":
                current["text"], attachments = split_attachments(current.get("text", ""))
                if attachments:
                    current["attachments"] = attachments
            if current.get("role") == "assistant":
                marker = re.search(r'\[Umeko:([a-f0-9-]{36})\]', current.get('text', ''))
                if marker:
                    current['diagnosticId'] = marker[1]
                    current['text'] = '供应商请求失败，请查看请求详情'
                steps = []
                if current.get("thinking"):
                    steps.append({"kind": "thinking", "text": current["thinking"]})
                if current.get("text"):
                    steps.append({"kind": "text", "text": current["text"], "error": current.get("error", False)})
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
                        if tool.get("name") == "submit_to_chatbox" and tool.get("media"):
                            steps.append({"kind": "tools", "tools": batch})
                            steps.append({"kind": "media", "items": media_view(tool["media"]), "toolId": tool["id"]})
                            batch = []
                    if batch: steps.append({"kind": "tools", "tools": batch})
                current["activity"] = steps
            continuing = bool(rows and rows[-1].get('stopReason') == 'length' and not current.get('error'))
            merging = bool(rows and current.get("role") == rows[-1].get("role") == "assistant"
                    and (continuing or rows[-1].get("tools") or rows[-1].get('_chain_tools') or current.get("tools")))
            if merging and (max_group is None or source_index - starts[-1] < max_group):
                group = rows[-1]
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
