"""Read cold transcripts off the UI thread; keep one reader and the latest request."""
import copy
import threading

from PySide6.QtCore import QObject, Signal, Slot
from .transcripts import preview


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
        self.completed.connect(self._completed)

    @Slot()
    def cancel(self):
        self.request = 0
        self.pending = self.prepared = None

    @Slot(str, int)
    def prepare(self, session_id, token):
        self.cancel()
        self.request = token
        saved = next((row for row in self.controller._sessions if row['id'] == session_id), None)
        if not saved:
            self.ready.emit(token, False)
            return
        saved = dict(saved)
        if self.controller._pool.find(session_id):
            self.prepared = {'token': token, 'saved': saved}
            self.ready.emit(token, True)
            return
        self.pending = {'token': token, 'saved': saved}
        self._start()

    def _start(self):
        if self.reading or not self.pending or self.controller._closing:
            return
        job, self.pending = self.pending, None
        self.reading = True
        def read():
            result = dict(job)
            try:
                saved = job['saved']
                result['messages'], result['tree'] = preview(saved['file']) if saved.get('file') else (copy.deepcopy(saved.get('messages', [])), [])
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
        if result['token'] == self.request:
            if result.get('error'):
                self.controller.toast.emit('聊天记录暂时无法读取，请稍后重试')
            else:
                self.prepared = result
            self.ready.emit(result['token'], not result.get('error', False))
        self._start()

    @Slot(int, result=bool)
    def activate(self, token):
        result = self.prepared
        if not result or token != self.request or result['token'] != token:
            return False
        saved = next((row for row in self.controller._sessions if row['id'] == result['saved']['id']), None)
        if not saved:
            return False
        if not self.controller._pool.find(saved['id']):
            record = self.controller._new_view(saved.get('workspace', ''))
            record.id, record.file, record.title = saved['id'], saved.get('file', ''), saved['title']
            record.history = copy.deepcopy(saved.get('history', []))
            record.messages, record.tree = result.get('messages', []), result.get('tree', [])
            record.model = saved.get('model') or record.model
            record.provider = saved.get('provider') or record.provider
            self.controller._pool.touch(record)
        self.cancel()
        self.controller.openSession(saved['id'])
        return True
