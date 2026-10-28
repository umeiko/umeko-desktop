"""Read one bounded text preview off the GUI thread; rapid requests keep only the latest."""
import codecs
import os
import re
import stat
import threading
from pathlib import Path
from PySide6.QtCore import QObject, Property, Signal, Slot
from PySide6.QtGui import QTextDocument

READ_LIMIT, TEXT_LIMIT, LINE_LIMIT, LINE_LENGTH = 256 * 1024, 48000, 1000, 2000
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


def read_preview(path, kind=''):
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
            raw = stream.read(READ_LIMIT)
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

    def __init__(self, parent=None, store=None):
        super().__init__(parent)
        self._store = store
        modes = store.data.get('ui', {}).get('documentPreviewModes', {}) if store else {}
        self._modes = {kind:mode for kind,mode in modes.items() if kind in ('html','markdown') and mode in ('source','rendered')} if isinstance(modes,dict) else {}
        self._static = None
        self._state, self._pending = {}, None
        self._generation, self._reading = 0, False
        self.completed.connect(self._completed)

    @Property('QVariantMap', notify=changed)
    def state(self):
        return self._state

    def _presentation(self):
        from .static_preview import HTML_LIMIT, StaticPreview
        kind = self._state.get('fileType', '')
        self._state['mode'] = self._modes.get(kind, 'rendered' if kind in ('markdown', 'html') else 'source')
        self._state['previewUrl'] = ''
        if kind == 'html' and not self._state.get('error') and not self._state.get('busy'):
            from .webview import configuration
            available = configuration()['available']
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

    @Slot(str, str)
    def setMode(self, file_type, mode):
        if file_type not in ('markdown', 'html') or mode not in ('source', 'rendered'):
            return
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
        self._state, self._pending = {}, None
        if self._static:
            self._static.revoke()
        self.changed.emit()

    @Slot(str, str)
    def load(self, path, kind):
        self._generation += 1
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
                result = read_preview(path, kind)
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
            self._state = result
            self._presentation()
            self.changed.emit()
        self._start()

    def close(self):
        self.cancel()
        if self._static:
            self._static.close()
            self._static = None
