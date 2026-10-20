"""Bounded, debounced syntax colors on native QTextDocuments; never HTML rewriting."""
from bisect import bisect_right
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import time
import weakref

import shiboken6
from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot, QCoreApplication
from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat, QTextDocument
from PySide6.QtQml import qmlRegisterType

MAX_CHARS, MAX_LINES, MAX_LINE = 48_000, 1_000, 2_000
MAX_SPANS, MAX_PENDING, CACHE_BYTES, CACHE_ENTRIES = 12_000, 8, 4 * 1024 * 1024, 64
ALIASES = {
    "py": "python", "python3": "python", "js": "javascript", "jsx": "javascript",
    "ts": "typescript", "tsx": "typescript", "sh": "bash", "shell": "bash", "zsh": "bash",
    "ps1": "powershell", "pwsh": "powershell", "yml": "yaml", "c++": "cpp", "cc": "cpp",
    "cs": "csharp", "c#": "csharp", "rs": "rust", "golang": "go", "htm": "html",
}
LANGUAGES = {"python", "javascript", "typescript", "json", "yaml", "bash", "powershell",
             "c", "cpp", "csharp", "java", "go", "rust", "sql", "html", "xml", "css", "diff"}
COLORS = {
    False: {"keyword": "#963b83", "string": "#26784b", "comment": "#7b827b", "number": "#a15d17", "name": "#2b65ad", "type": "#7651a8", "operator": "#596273", "deleted": "#b14444", "inserted": "#26784b"},
    True: {"keyword": "#c99bdc", "string": "#a8cf9c", "comment": "#87978c", "number": "#e5b281", "name": "#8cbce9", "type": "#dfc183", "operator": "#b8c5d2", "deleted": "#ef9a9a", "inserted": "#a8cf9c"},
}


def language_name(value):
    name = value.strip().lower()[:32]
    return ALIASES.get(name, name)


def eligible(text, language):
    return (language in LANGUAGES and 0 < len(text) <= MAX_CHARS
            and text.count("\n") < MAX_LINES and all(len(line) <= MAX_LINE for line in text.split("\n")))


def lexer_for(language):
    # Explicit builtins only: no plugin loading or expensive automatic guessing.
    # Imports stay in the worker; static imports also let the bundler discover them.
    from pygments.lexers.python import PythonLexer
    from pygments.lexers.javascript import JavascriptLexer, TypeScriptLexer
    from pygments.lexers.data import JsonLexer, YamlLexer
    from pygments.lexers.shell import BashLexer, PowerShellLexer
    from pygments.lexers.c_cpp import CLexer, CppLexer
    from pygments.lexers.dotnet import CSharpLexer
    from pygments.lexers.jvm import JavaLexer
    from pygments.lexers.go import GoLexer
    from pygments.lexers.rust import RustLexer
    from pygments.lexers.sql import SqlLexer
    from pygments.lexers.html import HtmlLexer, XmlLexer
    from pygments.lexers.css import CssLexer
    from pygments.lexers.diff import DiffLexer
    return {"python": PythonLexer, "javascript": JavascriptLexer, "typescript": TypeScriptLexer,
            "json": JsonLexer, "yaml": YamlLexer, "bash": BashLexer, "powershell": PowerShellLexer,
            "c": CLexer, "cpp": CppLexer, "csharp": CSharpLexer, "java": JavaLexer, "go": GoLexer,
            "rust": RustLexer, "sql": SqlLexer, "html": HtmlLexer, "xml": XmlLexer,
            "css": CssLexer, "diff": DiffLexer}[language](stripnl=False, ensurenl=False)


@dataclass(frozen=True)
class Tokens:
    lines: dict
    count: int = 0
    weight: int = 0


def tokenize(text, language):
    if not eligible(text, language):
        return Tokens({})
    from pygments.token import Keyword, String, Comment, Number, Name, Operator, Generic
    lexer = lexer_for(language)
    starts, units = [0], [0]
    for pos, character in enumerate(text):
        units.append(units[-1] + (2 if ord(character) > 0xffff else 1))
        if character == "\n": starts.append(pos + 1)
    result, count, deadline = {}, 0, time.monotonic() + 0.15
    for offset, token, value in lexer.get_tokens_unprocessed(text):
        if time.monotonic() > deadline:
            return Tokens({})  # Best-effort time budget, in addition to hard size limits.
        group = ("keyword" if token in Keyword else "string" if token in String else "comment" if token in Comment
                 else "number" if token in Number else "name" if token in Name.Function or token in Name.Builtin
                 else "type" if token in Name.Class or token in Name.Decorator else "operator" if token in Operator
                 else "deleted" if token in Generic.Deleted else "inserted" if token in Generic.Inserted else "")
        if not group: continue
        for part in value.splitlines(keepends=True):
            end = min(len(text), offset + len(part.rstrip("\r\n")))
            line = bisect_right(starts, offset) - 1
            if end > offset:
                result.setdefault(line, []).append((units[offset] - units[starts[line]], units[end] - units[offset], group))
                count += 1
                if count > MAX_SPANS: return Tokens({})
            offset += len(part)
    return Tokens(result, count, len(text.encode("utf-8")) + count * 128)


class HighlightService(QObject):
    ready = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="code-colors")
        self.pending, self.cache, self.weight, self.closed = {}, OrderedDict(), 0, False
        self.ready.connect(self._deliver)

    def request(self, target, generation, text, language):
        if self.closed: return False
        key = (language, hashlib.sha256(text.encode("utf-8")).digest())
        if key in self.cache:
            self.cache.move_to_end(key)
            target.accept(generation, self.cache[key])
            return True
        waiter = (weakref.ref(target), generation)
        if key in self.pending:
            self.pending[key].append(waiter)
            return True
        if len(self.pending) >= MAX_PENDING: return False
        self.pending[key] = [waiter]
        future = self.pool.submit(tokenize, text, language)
        def completed(job):
            try: result = job.result()
            except Exception: result = Tokens({})
            try:
                if not self.closed: self.ready.emit(key, result)
            except RuntimeError: pass  # Application has already destroyed its Qt objects.
        future.add_done_callback(completed)
        return True

    @Slot(object, object)
    def _deliver(self, key, result):
        waiters = self.pending.pop(key, [])
        if self.closed: return
        self.cache[key] = result
        self.weight += result.weight
        while self.weight > CACHE_BYTES or len(self.cache) > CACHE_ENTRIES:
            _, old = self.cache.popitem(last=False)
            self.weight -= old.weight
        for reference, generation in waiters:
            target = reference()
            if target is not None and shiboken6.isValid(target): target.accept(generation, result)

    def close(self):
        self.closed = True
        self.pending.clear(); self.cache.clear(); self.weight = 0
        self.pool.shutdown(wait=False, cancel_futures=True)


_service, _registered = None, False


def service():
    global _service
    if _service is None:
        _service = HighlightService(QCoreApplication.instance())
        QCoreApplication.instance().aboutToQuit.connect(_service.close)
    return _service


class SpanHighlighter(QSyntaxHighlighter):
    def __init__(self, parent):
        super().__init__(parent)
        self.lines, self.formats, self.valid = {}, {}, False

    def highlightBlock(self, text):
        if not self.valid: return
        for start, length, group in self.lines.get(self.currentBlock().blockNumber(), []):
            self.setFormat(start, length, self.formats[group])


class SyntaxHighlighter(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._quick = self._doc = None
        self._language, self._dark, self._enabled = "", False, True
        self._generation, self._attempts, self._status = 0, 0, "plain"
        self.native = SpanHighlighter(self)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True); self.timer.setInterval(180)
        self.timer.timeout.connect(self._prepare)
        self._palette()

    def _palette(self):
        self.native.formats = {}
        for group, color in COLORS[self._dark].items():
            value = QTextCharFormat(); value.setForeground(QColor(color))
            self.native.formats[group] = value

    def _schedule(self, *change):
        if change and change[1:] == (0, 0): return  # Formatting is not a text edit.
        self._generation += 1; self._attempts = 0
        self.native.valid = False
        self._status = "pending" if self._enabled else "plain"
        self.changed.emit()
        if self._enabled: self.timer.start()
        else: self.timer.stop(); self.native.setDocument(None)

    def get_document(self): return self._quick

    def set_document(self, quick):
        if quick is self._quick: return
        if self._doc is not None and shiboken6.isValid(self._doc):
            self._doc.contentsChange.disconnect(self._schedule)
        self.native.setDocument(None)
        self._quick = quick
        if quick is not None and self.parent() is None: self.setParent(quick)
        self._doc = quick if isinstance(quick, QTextDocument) else quick.textDocument() if quick else None
        if self._doc is not None: self._doc.contentsChange.connect(self._schedule)
        self._schedule()

    document = Property(QObject, get_document, set_document, notify=changed)

    def get_language(self): return self._language

    def set_language(self, value):
        value = language_name(value)
        if value != self._language: self._language = value; self._schedule()

    language = Property(str, get_language, set_language, notify=changed)

    def get_enabled(self): return self._enabled

    def set_enabled(self, value):
        if value != self._enabled: self._enabled = value; self._schedule()

    enabled = Property(bool, get_enabled, set_enabled, notify=changed)

    def get_dark(self): return self._dark

    def set_dark(self, value):
        if value != self._dark:
            self._dark = value; self._palette()
            if self.native.document(): self.native.rehighlight()
            self.changed.emit()

    dark = Property(bool, get_dark, set_dark, notify=changed)
    status = Property(str, lambda self: self._status, notify=changed)

    def _prepare(self):
        if not self._enabled or self._doc is None: return
        if self._doc.characterCount() > MAX_CHARS + 1 or self._language not in LANGUAGES:
            self.accept(self._generation, Tokens({})); return
        text = self._doc.toPlainText()
        if not eligible(text, self._language):
            self.accept(self._generation, Tokens({})); return
        if not service().request(self, self._generation, text, self._language):
            self._attempts += 1
            if self._attempts < 4: self.timer.start(400)
            else: self.accept(self._generation, Tokens({}))

    def accept(self, generation, result):
        if generation != self._generation or not self._enabled or self._doc is None: return
        if not result.count:
            self.native.setDocument(None)
            self._status = "plain"
        else:
            self.native.lines = result.lines
            self.native.valid = True
            if self.native.document() is not self._doc: self.native.setDocument(self._doc)
            self.native.rehighlight()
            self._status = "highlighted"
        self.changed.emit()


def register_text_types():
    global _registered
    if not _registered:
        qmlRegisterType(SyntaxHighlighter, "Umeko.Text", 1, 0, "SyntaxHighlighter")
        _registered = True
