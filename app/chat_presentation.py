"""Prepare immutable history bodies in the paging worker, never in the GUI loop."""
import copy
import re
from pathlib import Path
from threading import RLock

from PySide6.QtGui import QGuiApplication, QTextDocument
from PySide6.QtQml import QJSEngine
import shiboken6


class LocalDocument(QTextDocument):
    def loadResource(self, kind, url):
        return None


class HistoryPresentation:
    def __init__(self):
        from .transcript_index import WeightedLRU
        self.cache = WeightedLRU(24 * 1024 * 1024)
        self.sessions = {}
        self.lock = RLock()
        self.script = (Path(__file__).parent / 'qml/markdown.js').read_text(encoding='utf-8').replace('.pragma library', '', 1)

    def session_cache(self, session, context):
        from .transcript_index import WeightedLRU
        with self.lock:
            state = self.sessions.get(session)
            if state is None or state[0] != context:
                state = copy.deepcopy(context), WeightedLRU(24 * 1024 * 1024)
                self.sessions[session] = state
            return state[1]

    def discard_session(self, session):
        with self.lock:
            self.sessions.pop(session, None)

    def clear(self):
        from .transcript_index import WeightedLRU
        with self.lock:
            self.sessions.clear()
            self.cache = WeightedLRU(24 * 1024 * 1024)

    @staticmethod
    def signature(row):
        activity = row.get('activity', [])
        if activity:
            return tuple((position, step.get('text', ''), position < len(activity) - 1)
                         for position, step in enumerate(activity)
                         if step.get('kind') == 'text' and not step.get('error'))
        if row.get('role') == 'assistant' and not row.get('error'):
            return ((-1, row.get('text', ''), False),)
        return ()

    @staticmethod
    def attach(row, rendered):
        result = dict(row)
        if row.get('activity'):
            result['activity'] = [dict(step) for step in row['activity']]
        for position, blocks in rendered:
            if position < 0:
                result['_rendered'] = blocks
            else:
                result['activity'][position]['_rendered'] = blocks
        return result

    def cached(self, index, row, cache):
        value = cache.get(index) if cache is not None else None
        if value is not None and value[0] == self.signature(row):
            return self.attach(row, value[1])

    @staticmethod
    def invalidate(cache, first, last=None):
        if cache is None:
            return
        with cache.lock:
            for index in list(cache.items):
                if index >= first and (last is None or index <= last):
                    _, weight = cache.items.pop(index)
                    cache.weight -= weight

    def prepare(self, rows, cancelled=lambda: False, cache=None, use_default=True):
        cache = self.cache if cache is None and use_default else cache
        engine = None
        def blocks(text, compact=False):
            nonlocal engine
            if engine is None:
                engine = QJSEngine()
                engine.evaluate(self.script)
            result = engine.globalObject().property('blocks').call([
                engine.toScriptValue(text), engine.toScriptValue(True), engine.toScriptValue(compact)]).toVariant()
            if isinstance(QGuiApplication.instance(), QGuiApplication):
                for block in result:
                    if cancelled():
                        return None
                    if not block['code']:
                        normalized = engine.globalObject().property('forQt').call([engine.toScriptValue(block['text'])]).toString()
                        document = LocalDocument()
                        document.setMarkdown(normalized)
                        html = document.toHtml()
                        # Inherit the current theme/font instead of baking the
                        # worker's application default font into cached HTML.
                        html = re.sub(r'<body[^>]*>', '<body>', html)
                        html = re.sub(r'<img\b[^>]*>', '[图片]', html, flags=re.I)
                        block['html'] = html
            return result

        prepared = {}
        try:
            for index, row in rows.items():
                if cancelled():
                    break
                result = self.cached(index, row, cache)
                if result is None:
                    signature = self.signature(row)
                    rendered = [(position, blocks(text, compact)) for position, text, compact in signature]
                    if cancelled():
                        break
                    if cache is not None:
                        with cache.lock:
                            if cancelled():
                                break
                            cache.put(index, (signature, rendered))
                    result = self.attach(row, rendered)
                if not cancelled():
                    prepared[index] = result
            return prepared
        finally:
            if engine is not None:
                shiboken6.delete(engine)
