"""Read and cache local documents off the GUI thread; render large Markdown in blocks."""
import codecs
import json
import os
import re
import stat
import threading
from collections import OrderedDict
from pathlib import Path
from PySide6.QtCore import QObject, Property, Signal, Slot
from PySide6.QtGui import QTextDocument, QGuiApplication
from .document_blocks import DocumentBlocks, parse_markdown, source_blocks

READ_LIMIT, TEXT_LIMIT, LINE_LIMIT, LINE_LENGTH = 256 * 1024, 48000, 1000, 2000
MARKDOWN_LIMIT = 32 * 1024 * 1024
CODE_EXTENSIONS = set('c h cpp hpp cxx cc cs java kt go rs py pyw js mjs cjs jsx ts tsx json jsonc yaml yml toml ini cfg conf css scss html htm xml svg sh bash zsh fish ps1 bat cmd sql diff patch vue svelte qml cmake rb php lua dart swift r asm'.split())
TEXT_EXTENSIONS = {'txt', 'log', 'csv', 'tsv', 'rst', 'text'}


def document_kind(path, kind=''):
    if kind in ('markdown', 'code', 'text'):
        return kind
    if kind not in ('', 'auto', 'file'):
        return ''
    name = Path(path).name.lower()
    suffix = Path(path).suffix.lower().lstrip('.')
    if suffix in ('md', 'markdown', 'mdown'):
        return 'markdown'
    if suffix in TEXT_EXTENSIONS and name != 'cmakelists.txt':
        return 'text'
    if suffix in CODE_EXTENSIONS or name in ('dockerfile', 'makefile', 'cmakelists.txt', '.gitignore', '.env'):
        return 'code'
    return ''


class LocalDocument(QTextDocument):
    def loadResource(self, kind, url):
        return None


def read_preview(path, kind='', cancelled=lambda: False):
    result = {'path': path, 'busy': False}
    def fail(message):
        return {**result, 'error': message}
    kind = document_kind(path, kind)
    if not Path(path).is_absolute() or not kind:
        return fail('文件不存在或不支持文本预览')
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                return fail('文件不存在或不支持文本预览')
            raw = stream.read(MARKDOWN_LIMIT if kind == 'markdown' else READ_LIMIT)
    except OSError:
        return fail('文件暂时无法读取')
    truncated = info.st_size > len(raw)
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        decoder = codecs.getincrementaldecoder('utf-16-le' if raw.startswith(b'\xff\xfe') else 'utf-16-be')(errors='replace')
        text = decoder.decode(raw[2:], final=not truncated)
    else:
        if b'\0' in raw:
            return fail('这是二进制文件，无法作为文本预览')
        text = codecs.getincrementaldecoder('utf-8-sig')(errors='replace').decode(raw, final=not truncated)
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    if cancelled():
        raise InterruptedError('Document changed')
    # Markdown is a document, not a code snippet. Keep its source intact and
    # virtualize large documents instead of cutting lines or flattening tables.
    if kind == 'markdown' and (len(text) > 24000 or text.count('\n') > 400 or text.count('|') > 256 or text.count('[') > 256 or any(len(line) > 1000 for line in text.split('\n'))):
        note = ''
        try:
            blocks = parse_markdown(text, cancelled)
        except InterruptedError:
            raise
        except (OSError, RuntimeError, ValueError, KeyError, TimeoutError):
            blocks = list(source_blocks(text))
            note = 'Markdown 渲染暂不可用，已显示完整源码'
        return {**result, 'kind': kind, 'fileType': 'markdown', 'text': text,
                'html': '', 'bytes': info.st_size, 'truncated': truncated,
                'simple': False, 'highlight': False, 'language': 'markdown',
                'chunked': True, '_blocks': blocks, '_source': list(source_blocks(text)),
                'renderNote': note}
    if len(text) > TEXT_LIMIT:
        text, truncated = text[:TEXT_LIMIT], True
    source = text.split('\n')
    truncated |= len(source) > LINE_LIMIT
    lines = []
    for line in source[:LINE_LIMIT]:
        if len(line) > LINE_LENGTH:
            line, truncated = line[:LINE_LENGTH] + ' …', True
        lines.append(line)
    text = '\n'.join(lines)
    html, simple = '', False
    if kind == 'markdown':
        simple = len(text) > 24000 or len(lines) > 400 or text.count('|') > 256 or text.count('[') > 256 or any(len(line) > 1000 for line in lines)
        if not simple:
            document = LocalDocument()
            document.setMarkdown(text)
            html = re.sub(r'<img\b[^>]*>', '[图片]', document.toHtml(), flags=re.IGNORECASE)
            html = re.sub(r'<body[^>]*>', '<body>', html)
            html = re.sub(r'''\b(?:src|background)\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)''', '', html, flags=re.IGNORECASE)
            html = re.sub(r'url\([^)]*\)', '', html, flags=re.IGNORECASE)
            if len(html) > 256 * 1024:
                html, simple = '', True
    highlight = kind == 'code' and len(text) <= 24000 and len(lines) <= 500 and all(len(line) <= 1000 for line in lines)
    suffix = Path(path).suffix.lower()
    file_type = 'html' if suffix in ('.html', '.htm') else 'markdown' if kind == 'markdown' else kind
    result.update(kind=kind, fileType=file_type, text=text, html=html, language=suffix.lstrip('.'), bytes=info.st_size, truncated=truncated, simple=simple, highlight=highlight)
    return result


class DocumentPreview(QObject):
    changed = Signal()
    completed = Signal(int, object)
    copyReady = Signal(int, str)

    def __init__(self, parent=None, store=None):
        super().__init__(parent)
        self._store = store
        modes = store.data.get('ui', {}).get('documentPreviewModes', {}) if store else {}
        self._modes = {kind:mode for kind,mode in modes.items() if kind in ('html','markdown') and mode in ('source','rendered')} if isinstance(modes,dict) else {}
        self._static = None
        self._state, self._pending = {}, None
        self._generation, self._reading = 0, False
        self._copy_serial = 0
        self._blocks = DocumentBlocks(self)
        self._text = ''
        self._cache, self._cache_bytes = OrderedDict(), 0
        self._cache_lock = threading.Lock()
        self.completed.connect(self._completed)
        self.copyReady.connect(self._copy_ready)

    @Property(QObject, constant=True)
    def blocks(self):
        return self._blocks

    @Slot()
    def copyAll(self):
        self._copy_serial += 1
        QGuiApplication.clipboard().setText(self._text)

    @Slot(str, result=int)
    def anchorIndex(self, name):
        from urllib.parse import unquote
        return self._blocks.anchor(unquote(name.lstrip('#')))

    @Slot(str)
    def copySelection(self, raw):
        try:
            value = json.loads(raw)
            first, last = sorted((value['anchor'], value['cursor']), key=lambda p:(p['row'], p['block'], p['offset']))
            start, end = int(first['row']), int(last['row'])
            rows = self._blocks.rows
            if not 0 <= start <= end < len(rows): return
        except (ValueError, KeyError, TypeError):
            return
        self._copy_serial += 1
        request = self._copy_serial
        def copy():
            pieces = []
            for index in range(start, end + 1):
                if request != self._copy_serial: return
                row = rows[index]
                if row.get('html'):
                    document = LocalDocument(); document.setHtml(row['html']); text = document.toPlainText()
                else: text = row['text']
                units = text.encode('utf-16-le')
                left = first['offset'] * 2 if index == start and first['block'] >= 0 else 0
                right = last['offset'] * 2 if index == end and last['block'] <= 0 else len(units)
                if pieces and row['kind'] != 'source' and not row.get('continued'):
                    pieces.append('\n\n')
                pieces.append(units[left:right].decode('utf-16-le', 'replace'))
            try: self.copyReady.emit(request, ''.join(pieces))
            except RuntimeError: pass
        threading.Thread(target=copy, daemon=True).start()

    @Slot(int, str)
    def _copy_ready(self, request, text):
        if request == self._copy_serial:
            QGuiApplication.clipboard().setText(text)

    @Property('QVariantMap', notify=changed)
    def state(self):
        return self._state

    def _presentation(self):
        from .static_preview import HTML_LIMIT, StaticPreview
        kind = self._state.get('fileType', '')
        self._state['mode'] = self._modes.get(kind, 'rendered' if kind in ('markdown', 'html') else 'source')
        self._state['previewUrl'] = ''
        self._blocks.set_mode(self._state['mode'])
        if kind == 'html':
            self._state.pop('renderNote', None)
        if kind == 'html' and not self._state.get('error') and not self._state.get('busy'):
            from .webview import configuration
            available = configuration(self._store.data.get('desktop'))['available'] if self._store else configuration()['available']
            self._state['renderable'] = available and self._state.get('bytes', 0) <= HTML_LIMIT
            if self._state['mode'] == 'rendered' and self._state['renderable']:
                try:
                    if self._static is None:
                        self._static = StaticPreview()
                    self._state['previewUrl'] = self._static.open(self._state['path'])
                except OSError:
                    self._state['renderable'] = False
            if not self._state['renderable']:
                self._state['mode'] = 'source'
                self._state['renderNote'] = 'HTML 较大，已使用源码预览' if available else '网页预览组件尚未安装或无法加载'

    def refreshWebPolicy(self):
        if self._state.get('fileType') == 'html':
            if self._static: self._static.revoke()
            self._presentation()
            self.changed.emit()

    @Slot(str, str)
    def setMode(self, file_type, mode):
        if file_type not in ('markdown', 'html') or mode not in ('source', 'rendered'):
            return
        self._copy_serial += 1
        self._modes[file_type] = mode
        if self._store:
            self._store.data.setdefault('ui', {})['documentPreviewModes'] = dict(self._modes)
            self._store.save()
        if self._state.get('fileType') == file_type:
            self._presentation()
            self.changed.emit()

    @Slot()
    def cancel(self):
        self._generation += 1
        self._copy_serial += 1
        self._state, self._pending = {}, None
        self._text = ''
        self._blocks.load([], [])
        if self._static:
            self._static.revoke()
        self.changed.emit()

    @Slot(str, str)
    def load(self, path, kind):
        self._generation += 1
        self._copy_serial += 1
        self._pending = (self._generation, path, kind)
        self._state = {'path': path, 'busy': True}
        self.changed.emit()
        self._start()

    def _start(self):
        if self._reading or self._pending is None:
            return
        generation, path, kind = self._pending
        self._pending, self._reading = None, True
        def read():
            try:
                try:
                    info = Path(path).stat()
                    key = (path, kind, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
                except OSError:
                    key = None
                with self._cache_lock:
                    result = self._cache.get(key)
                    if result is not None:
                        self._cache.move_to_end(key)
                if result is None:
                    result = read_preview(path, kind, cancelled=lambda: generation != self._generation)
                    current = Path(path).stat() if key else None
                    unchanged = current and (current.st_ino, current.st_size, current.st_mtime_ns) == (info.st_ino, info.st_size, info.st_mtime_ns)
                    if key and unchanged and result.get('chunked') and not result.get('error') and not result.get('renderNote') and generation == self._generation:
                        weight = self._weight(result)
                        if weight <= 32 * 1024 * 1024:
                            with self._cache_lock:
                                if generation == self._generation:
                                    self._cache[key] = result
                                    self._cache_bytes += weight
                                    while len(self._cache) > 3 or self._cache_bytes > 32 * 1024 * 1024:
                                        _, old = self._cache.popitem(last=False)
                                        self._cache_bytes -= self._weight(old)
                result = dict(result)
            except Exception:
                result = {'path': path, 'busy': False, 'error': '文件读取失败'}
            try:
                self.completed.emit(generation, result)
            except RuntimeError:
                pass
        threading.Thread(target=read, daemon=True).start()

    @Slot(int, object)
    def _completed(self, generation, result):
        self._reading = False
        if generation == self._generation:
            self._text = result.get('text', '')
            self._blocks.load(result.pop('_blocks', []), result.pop('_source', []))
            if result.get('chunked'):
                result['text'] = ''  # Avoid copying the full source into QML.
            self._state = result
            self._presentation()
            self.changed.emit()
        self._start()

    def close(self):
        self.cancel()
        with self._cache_lock:
            self._cache.clear(); self._cache_bytes = 0
        if self._static:
            self._static.close()
            self._static = None

    @staticmethod
    def _weight(result):
        return 2 * (len(result.get('text', '')) + sum(
            len(row.get('html', '')) + len(row.get('text', ''))
            for name in ('_blocks', '_source') for row in result.get(name, [])))
