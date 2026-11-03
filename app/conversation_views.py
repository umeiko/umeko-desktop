"""Three retained viewport models; one shared paging worker and HTML LRU."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QObject, Signal
from .chat_model import ChatModel
from .chat_presentation import HistoryPresentation


class ConversationViews(QObject):
    evicted = Signal(str)

    def __init__(self, parent=None, capacity=3):
        super().__init__(parent)
        self.capacity = capacity
        self.models = OrderedDict()
        self.current = ''
        self.reader = ThreadPoolExecutor(max_workers=1, thread_name_prefix='chat-pages')
        self.presentation = HistoryPresentation()

    def select(self, key):
        previous = self.models.get(self.current)
        if previous is not None and self.current != key:
            previous.suspend(True)
        self.current = key
        model = self.models.get(key)
        if model is None:
            model = ChatModel(self, reader=self.reader, presentation=self.presentation)
            self.models[key] = model
        self.models.move_to_end(key)
        model.suspend(False)
        while len(self.models) > self.capacity:
            self.discard(next(iter(self.models)))
        return model

    def discard(self, key):
        model = self.models.pop(key, None)
        if model is not None:
            self.evicted.emit(key)
            model.close()
            model.deleteLater()

    def close(self):
        for model in self.models.values():
            model.close()
        self.reader.shutdown(wait=False, cancel_futures=True)
