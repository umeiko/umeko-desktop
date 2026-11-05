"""Stable message rows: streaming updates never reset the conversation list."""
import copy
import re
from bisect import bisect_left, bisect_right
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Property, Signal, Slot
from .message_attachments import split_attachments
from .chatbox import media_view

RENDER_ROWS = 1
MAX_PREPARED_ROWS = 8
MAX_CACHED_ROWS = 16
# ListView spacing between rows; the content hints exclude it.
ROW_SPACING = 27
# Upper bound on the rows one viewport request may keep prepared.
MAX_GROUP_ROWS = 512


class ChatModel(QAbstractListModel):
    MessageRole = Qt.UserRole + 1
    questionsChanged = Signal()
    sourceChanged = Signal()
    pageReady = Signal(object)
    viewportAboutToChange = Signal()
    viewportChanged = Signal()

    def __init__(self, parent=None, *, reader=None, presentation=None):
        super().__init__(parent)
        self.rows = []
        self._questions = []
        self._source_starts = []
        self._source_count = 0
        self._source = None
        self.snapshot = None
        self._generation = 0
        self._pending, self._failed = set(), set()
        self._wanted, self._prepared, self._job = [], OrderedDict(), None
        from .chat_presentation import HistoryPresentation
        self._presentation = presentation or HistoryPresentation()
        self._metadata, self._heights = OrderedDict(), OrderedDict()
        self._layout = ''
        self._closed = False
        self._owns_reader = reader is None
        self._reader = reader or ThreadPoolExecutor(max_workers=1, thread_name_prefix='chat-pages')
        self._suspended = False
        # Display groups: runs of consecutive rows whose content hints add up
        # to about groupHeight pixels. The view loads, shows and recycles whole
        # groups. Hints do not change when a row is measured, so groups stay
        # put while the user scrolls; only edited live rows are regrouped.
        self._group_height = 0.0
        self._group_starts, self._group_next, self._group_open = [], 0, None
        self._live_hints = []
        self.pageReady.connect(self._page_ready)

    def suspend(self, value):
        self._suspended = value
        if not value:
            self._pump()

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
        self._prepared.clear()
        self._wanted = []
        self._metadata.clear()
        self._heights.clear()
        self.snapshot = snapshot
        self.rows, self._questions, self._source_starts = [], [], []
        self._live_hints = []
        self._reset_groups()
        self._source, self._source_count = None, 0
        if snapshot and snapshot.count:
            focus = snapshot.focus_row if snapshot.focus_row >= 0 else snapshot.count - 1
            self.requestRange(focus, focus)
        self.endResetModel()
        self.sourceChanged.emit()
        self.questionsChanged.emit()

    @Slot(int, int)
    def requestRange(self, first, last):
        if not self.snapshot or self._closed:
            return
        first, last = max(0, first), min(self.base_count - 1, max(first, last))
        if first > last:
            return
        if self._group_height > 0:
            rows = list(range(first, last + 1))
            rows += [row for row in range(self.groupFirst(self.groupOf(first)), self.groupLast(self.groupOf(last)) + 1)
                     if not first <= row <= last and row < self.base_count]
            self._set_wanted(rows[:MAX_GROUP_ROWS])
            return
        last = min(last, first + MAX_PREPARED_ROWS - 1)
        self._set_wanted(list(range(first // RENDER_ROWS, last // RENDER_ROWS + 1)))

    @Slot(int, int, int)
    def requestGroups(self, first, last, keep):
        """Prepare the groups of the on-screen rows first, then keep groups on each side."""
        if not self.snapshot or self._closed:
            return
        if self._group_height <= 0:
            self.requestViewport(list(range(first, last + 1)), [])
            return
        first, last = max(0, first), min(self.base_count - 1, max(first, last))
        if first > last:
            return
        g0, g1 = self.groupOf(first), self.groupOf(last)
        rows = list(range(first, last + 1))
        rows += [row for row in range(self.groupFirst(g0), self.groupLast(g1) + 1) if not first <= row <= last]
        count = len(self._partition())
        for step in range(1, max(0, keep) + 1):
            for group in (g1 + step, g0 - step):
                if 0 <= group < count:
                    rows += range(self.groupFirst(group), self.groupLast(group) + 1)
        rows = [row for row in dict.fromkeys(rows) if row < self.base_count]
        self._set_wanted(rows[:MAX_GROUP_ROWS])

    @Slot('QVariantList', 'QVariantList')
    def requestViewport(self, visible, nearby):
        if not self.snapshot or self._closed:
            return
        def valid(values):
            return list(dict.fromkeys(int(row) for row in values if isinstance(row, (int, float)) and 0 <= row < self.base_count))
        # Every on-screen row must load, including dense views with more than
        # eight short messages. Only speculative rows share the usual budget.
        rows = valid(visible)
        limit = max(MAX_PREPARED_ROWS, len(rows))
        rows += [row for row in valid(nearby) if row not in rows][:max(0, limit - len(rows))]
        self._set_wanted(rows)

    def _set_wanted(self, pages):
        self._wanted = pages
        for row in pages:
            if row in self._prepared:
                self._prepared.move_to_end(row)
        self._trim_prepared()
        self.snapshot.repository.cache.pin(self.snapshot.key(row) for row in pages)
        self._pump()

    def _trim_prepared(self):
        # Keep a small LRU across viewport-boundary changes. Immediately
        # discarding the previous range made edge rows oscillate into placeholders.
        limit = max(MAX_CACHED_ROWS, len(self._wanted))
        for row in list(self._prepared):
            if len(self._prepared) <= limit:
                break
            if row not in self._wanted:
                self._prepared.pop(row)

    def _request(self, page):
        if page not in self._wanted:
            return
        self._pump()

    def _pump(self):
        if self._closed or self._suspended or self._job is not None or not self.snapshot:
            return
        page = next((p for p in self._wanted if p not in self._failed and not all(
            row in self._prepared for row in range(p * RENDER_ROWS, min(self.base_count, (p + 1) * RENDER_ROWS)))), None)
        if page is None:
            return
        # One job prepares every wanted row of a display group, so the group's
        # rows change from placeholders to content in a single dataChanged.
        pages = [page]
        if self._group_height > 0:
            group = self.groupOf(page)
            members = range(self.groupFirst(group), self.groupLast(group) + 1)
            pages = [p for p in self._wanted if p in members and p not in self._failed and p not in self._prepared]
        snapshot, generation = self.snapshot, self._generation
        self._job = generation, page
        self._pending.update(pages)
        def read():
            from .transcript_index import PAGE_ROWS
            cancelled = lambda: (self._closed or self._suspended or generation != self._generation
                                 or not any(p in self._wanted for p in pages))
            if cancelled(): return {}
            rows = {}
            for number in sorted({p * RENDER_ROWS // PAGE_ROWS for p in pages}):
                rows.update(snapshot.page(number))
            wanted = {row for p in pages for row in range(p * RENDER_ROWS, (p + 1) * RENDER_ROWS)}
            rows = {row:value for row,value in rows.items() if row in wanted}
            return self._presentation.prepare(rows, cancelled)
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
                    self.pageReady.emit((generation, pages, error, prepared))
            except RuntimeError:
                pass
        future.add_done_callback(complete)

    @Slot(object)
    def _page_ready(self, value):
        generation, pages, error, prepared = value
        self._job = None
        self._pending.difference_update(pages)
        if self._closed or generation != self._generation or not self.snapshot:
            self._pump()
            return
        if not any(page in self._wanted for page in pages):
            self._pump()
            return
        if not error and not prepared:
            self._pump()
            return
        if error:
            self._failed.update(pages)
        self._prepared.update(prepared)
        self._trim_prepared()
        first = min(pages) * RENDER_ROWS
        last = min(self.base_count - 1, (max(pages) + 1) * RENDER_ROWS - 1)
        self.viewportAboutToChange.emit()
        self.dataChanged.emit(self.index(first), self.index(last), [self.MessageRole])
        self.viewportChanged.emit()
        self._pump()

    @Slot(int)
    def retryPage(self, row):
        if self._group_height > 0:
            group = self.groupOf(row)
            self._failed.difference_update(range(self.groupFirst(group), self.groupLast(group) + 1))
        self._failed.discard(row // RENDER_ROWS)
        self.requestRange(row, row)

    @Slot(int, result=bool)
    def isReady(self, row):
        if not self.snapshot or row >= self.base_count or row < 0:
            return True
        return row in self._prepared or row // RENDER_ROWS in self._failed

    @Slot(int, float)
    def recordHeight(self, row, height):
        # ListView destroys delegates outside its cache and recreates them from
        # this estimate. Live rows (unindexed sessions and the streaming tail)
        # need the same memory as indexed pages: a forgotten tall row comes back
        # as a short guess, its real height then pushes the tail out of view,
        # and following the tail recreates the same rows again (issue #95).
        if not 0 <= row < self.rowCount() or not 0 < height < 10000000:
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

    def _reset_groups(self):
        self._group_starts, self._group_next, self._group_open = [], 0, None

    def _invalidate_groups(self, row):
        """Regroup from the group containing row; earlier groups stay as they are."""
        if row >= self._group_next:
            return
        group = bisect_right(self._group_starts, row) - 1
        if group < 0:
            self._reset_groups()
            return
        self._group_next = self._group_starts[group]
        del self._group_starts[group:]
        self._group_open = None

    def _row_hint(self, row):
        if row < self.base_count:
            return float(self.snapshot.metadata(row).get('hint', 100))
        index = row - self.base_count
        hint = self._live_hints[index] if index < len(self._live_hints) else None
        if hint is None:
            from .transcript_index import estimated_height
            hint = float(estimated_height(self.rows[index]))
            if index < len(self._live_hints):
                self._live_hints[index] = hint
        return hint

    def _partition(self):
        """Greedy groups over the content hints, continued as rows are appended."""
        total = self.rowCount()
        if self._group_next < total:
            starts, limit, used = self._group_starts, self._group_height, self._group_open
            for row in range(self._group_next, total):
                # Indexed and live rows never share a group: Pi re-sends the
                # live part, the indexed part does not change.
                if used is None or used >= limit or row == self.base_count:
                    starts.append(row)
                    used = 0.0
                used += self._row_hint(row) + ROW_SPACING
            self._group_next, self._group_open = total, used
        return self._group_starts

    @Slot(float)
    def setGroupHeight(self, height):
        height = max(0.0, float(height))
        if abs(height - self._group_height) >= 1:
            self._group_height = height
            self._reset_groups()

    @Slot(int, result=int)
    def groupOf(self, row):
        starts = self._partition()
        if not starts or row < 0:
            return 0
        return max(0, bisect_right(starts, min(row, self.rowCount() - 1)) - 1)

    @Slot(int, result=int)
    def groupFirst(self, group):
        starts = self._partition()
        return starts[max(0, min(group, len(starts) - 1))] if starts else 0

    @Slot(int, result=int)
    def groupLast(self, group):
        starts = self._partition()
        if not starts:
            return -1
        group = max(0, min(group, len(starts) - 1))
        return starts[group + 1] - 1 if group + 1 < len(starts) else self.rowCount() - 1

    @Slot(result=int)
    def groupCount(self):
        return len(self._partition())

    @Slot(int, int, result=float)
    def spanHeight(self, first, last):
        """Estimated pixels of rows first..last, measured heights preferred."""
        first, last = max(0, first), min(self.rowCount() - 1, last)
        return sum(self.estimatedHeight(row) + ROW_SPACING for row in range(first, last + 1))

    @Slot(int, result=float)
    def estimatedHeight(self, row):
        if row in self._heights:
            return self._heights[row]
        if self.snapshot and 0 <= row < self.base_count:
            return float(self.snapshot.metadata(row).get('hint', 100))
        if 0 <= row - self.base_count < len(self.rows):
            # The same visible-content hint the index stores for paged rows.
            from .transcript_index import estimated_height
            return float(estimated_height(self.rows[row - self.base_count]))
        return 100.0

    def message(self, row, synchronous=False):
        if row >= self.base_count:
            return self.rows[row - self.base_count] if 0 <= row - self.base_count < len(self.rows) else {}
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
        return {'role': meta.get('role', 'assistant'), 'text': '', 'error': False, '_loading': True,
                '_loadError': row // RENDER_ROWS in self._failed, '_estimatedHeight': self._heights.get(row, meta.get('hint', 100))}

    def close(self):
        self._closed = True
        self._generation += 1
        if self._owns_reader:
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
        from .transcript_index import display_fragments, estimated_height
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
        self._live_hints.extend([None] * (len(self.rows) - len(self._live_hints)))
        for row in range(first, min(total, len(self.rows))):
            value = messages[row - first]
            if self.rows[row] != value:
                questions_dirty |= self.rows[row].get('role') == 'user' or value.get('role') == 'user'
                self.rows[row] = copy.deepcopy(value)
                # Only an edited row's own group and later groups regroup.
                hint = float(estimated_height(self.rows[row]))
                if hint != self._live_hints[row]:
                    self._live_hints[row] = hint
                    self._invalidate_groups(self.base_count + row)
                self.dataChanged.emit(self.index(self.base_count + row), self.index(self.base_count + row), [self.MessageRole])
        if total > len(self.rows):
            self.beginInsertRows(QModelIndex(), self.base_count + len(self.rows), self.base_count + total - 1)
            self.rows.extend(copy.deepcopy(messages[len(self.rows) - first:]))
            self._live_hints.extend([None] * (len(self.rows) - len(self._live_hints)))
            self.endInsertRows()
        elif total < len(self.rows):
            self.beginRemoveRows(QModelIndex(), self.base_count + total, self.base_count + len(self.rows) - 1)
            for row in range(self.base_count + total, self.base_count + len(self.rows)):
                self._heights.pop(row, None)
            del self.rows[total:]
            del self._live_hints[total:]
            self._invalidate_groups(self.base_count + total)
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
