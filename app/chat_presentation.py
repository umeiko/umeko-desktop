"""Prepare immutable history bodies in the paging worker, never in the GUI loop."""
import hashlib
import re
from pathlib import Path

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
        self.script = (Path(__file__).parent / 'qml/markdown.js').read_text(encoding='utf-8').replace('.pragma library', '', 1)

    def prepare(self, rows, cancelled=lambda: False):
        engine = None
        def blocks(text, compact=False):
            nonlocal engine
            key = hashlib.sha256((str(compact) + '\0' + text).encode('utf-8')).digest()
            cached = self.cache.get(key)
            if cached is not None:
                return cached
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
            return self.cache.put(key, result)

        prepared = {}
        try:
            for index, row in rows.items():
                if cancelled():
                    break
                result = dict(row)
                activity = row.get('activity', [])
                if activity:
                    result['activity'] = [dict(step) for step in activity]
                    for position, step in enumerate(result['activity']):
                        if step.get('kind') == 'text' and not step.get('error'):
                            step['_rendered'] = blocks(step.get('text', ''), position < len(activity) - 1)
                elif row.get('role') == 'assistant' and not row.get('error'):
                    result['_rendered'] = blocks(row.get('text', ''))
                if not cancelled():
                    prepared[index] = result
            return prepared
        finally:
            if engine is not None:
                shiboken6.delete(engine)
