"""Bound the retained chat views independently of the Pi kernel pool."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QObject, QTimer, Signal
from .chat_model import ChatModel
from .chat_presentation import HistoryPresentation


class ConversationViews(QObject):
    evicted = Signal(str)

    def __init__(self, parent=None, capacity=3, byte_limit=32 * 1024 * 1024):
        super().__init__(parent)
        self.capacity = capacity
        self.byte_limit = byte_limit
        self.models = OrderedDict()
        self.model_bytes = {}
        self.image_bytes = {}
        self.current = ''
        self.reader = ThreadPoolExecutor(max_workers=1, thread_name_prefix='chat-pages')
        self.presentation = HistoryPresentation()
        self._budget_update = QTimer(self)
        self._budget_update.setSingleShot(True)
        self._budget_update.setInterval(100)
        self._budget_update.timeout.connect(self._trim_current)

    def select(self, key, generation=0, staged=False):
        previous = self.models.get(self.current)
        if previous is not None and self.current != key:
            previous.suspend(True)
            self.model_bytes[self.current] = previous.retainedBytes()
        self.current = key
        model = self.models.get(key)
        cold = model is None
        if model is None:
            model = ChatModel(self, reader=self.reader, presentation=self.presentation)
            self.models[key] = model
            model.viewportChanged.connect(self._schedule_trim)
            model.sourceChanged.connect(self._schedule_trim)
            model.rowsInserted.connect(self._schedule_trim)
            model.dataChanged.connect(self._schedule_trim)
        self.models.move_to_end(key)
        if generation:
            model.begin_open(generation, cold=cold and staged)
        model.suspend(False)
        self.trim()
        return model

    def _schedule_trim(self, *_):
        if not self._budget_update.isActive():
            self._budget_update.start()

    def _trim_current(self):
        current = self.models.get(self.current)
        if current is not None:
            self.model_bytes[self.current] = current.retainedBytes()
        self.trim()

    def weight(self, key):
        return self.model_bytes.get(key, 0) + self.image_bytes.get(key, 0)

    def retained_bytes(self):
        current = self.models.get(self.current)
        if current is not None:
            self.model_bytes[self.current] = current.retainedBytes()
        return sum(self.weight(key) for key in self.models) + self.presentation.cache.weight

    def trim(self):
        weights = {key: self.weight(key) for key in self.models}
        shared = self.presentation.cache.weight
        current = self.models.get(self.current)
        if current is not None and self.current not in self.model_bytes:
            weights[self.current] = current.retainedBytes() + self.image_bytes.get(self.current, 0)
        total = sum(weights.values()) + shared
        for key, weight in weights.items():
            if len(self.models) <= self.capacity and total <= self.byte_limit:
                break
            if key != self.current:
                self.discard(key)
                total -= weight

    def set_images(self, key, size):
        if key in self.models:
            self.image_bytes[key] = size
            if key == self.current:
                self.model_bytes[key] = self.models[key].retainedBytes()
            self.trim()

    def discard(self, key):
        self.image_bytes.pop(key, None)
        self.model_bytes.pop(key, None)
        model = self.models.pop(key, None)
        if model is not None:
            self.evicted.emit(key)
            model.close()
            model.deleteLater()

    def close(self):
        self._budget_update.stop()
        for model in self.models.values():
            model.close()
        self.reader.shutdown(wait=False, cancel_futures=True)
