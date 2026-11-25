"""Complete the history of a conversation first shown from its latest messages.

A first visit to a long unindexed transcript shows a partial snapshot read
from the end of the file. This builds the complete index in the background.
When the complete index ends with the same rows, its earlier rows are inserted
above the ones on screen as soon as the reader is at the latest message or
reaches the top of the partial history. A complete index whose last rows
differ (a compaction that started before the partial history) replaces the
view when the reader reaches the top or leaves the conversation.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import time

from PySide6.QtCore import QObject, QTimer, Signal, Slot

# The first screen of the latest messages is drawn before the complete index
# starts competing with it for the interpreter.
BUILD_DELAY_MS = 600


class RecentHistory(QObject):
    finished = Signal(object)

    def __init__(self, controller):
        super().__init__(controller)
        self.controller = controller
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='transcript-history')
        self.building = {}
        self.finished.connect(self._finished)

    def complete(self, record):
        """Build the complete index for record's partial snapshot."""
        recent = record.transcript
        if recent is None or not recent.partial or self.controller._closing or record is not self.controller._view:
            return
        generation = self.controller._view_open_generation
        if recent.origin in self.building:
            return
        self.building[recent.origin] = generation
        session_id, repository = record.id, self.controller.transcripts
        preview = self.controller._session_preview

        def cancelled():
            # Another conversation being opened goes first.
            while time.monotonic() < preview.busy_until and not self.controller._closing:
                time.sleep(0.02)
            return self.controller._closing

        def build():
            result = {'id': session_id, 'recent': recent, 'generation': generation}
            try:
                snapshot = repository.open(recent.origin, cancelled=cancelled)
                result['snapshot'] = snapshot
                result['same'] = repository.same_tail(recent, snapshot)
            except Exception:
                result['error'] = True
            try:
                self.finished.emit(result)
            except RuntimeError:
                pass  # The application closed while the index was being built.
        def start():
            if generation == self.controller._view_open_generation and not self.controller._closing:
                self.pool.submit(build)
            else:
                self._finished({'id': session_id, 'recent': recent, 'generation': generation, 'error': True})
        QTimer.singleShot(BUILD_DELAY_MS, self, start)

    @Slot(object)
    def _finished(self, result):
        recent = result['recent']
        self.building.pop(recent.origin, None)
        if self.controller._closing:
            return
        record = self.controller._view
        if record.id != result['id'] or record.transcript is None or not record.transcript.partial:
            return
        if result['generation'] != self.controller._view_open_generation or record.transcript is not recent:
            self.complete(record)
            return
        if result.get('error') or not result['snapshot'].matches_source():
            if recent.matches_source():
                self.complete(record)
            return
        record.history_pending = result
        if record.history_wanted or (result['same'] and record.follow_tail):
            self.apply(record)

    def apply(self, record):
        result, record.history_pending = record.history_pending, None
        if result is None or result['generation'] != self.controller._view_open_generation:
            return
        recent, snapshot = result['recent'], result['snapshot']
        if result['same']:
            # The view inserts the earlier rows above the ones on screen.
            snapshot = replace(snapshot, extends=recent)
        if not record.follow_tail and record.scroll_index >= 0:
            # Partial rows are the last rows of the complete index.
            record.scroll_index += snapshot.count - recent.count
        record.transcript, record.history_wanted = snapshot, False
        record.body_dirty = True
        if record is self.controller._view:
            self.controller.chatChanged.emit()

    @Slot()
    def loadEarlier(self):
        """The reader reached the top of a partial history."""
        record = self.controller._view
        if record.transcript is None or not record.transcript.partial:
            return
        if record.history_pending is not None:
            self.apply(record)
        else:
            record.history_wanted = True
            self.complete(record)

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
