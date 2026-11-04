"""Decorate explicit web links in the unchanged rendered document."""
import queue
import threading

from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor, QTextFormat
import shiboken6

from .conversation_links import fenced_ranges, recognize_links, web_url

LINK_PROPERTY = QTextFormat.UserProperty + 55
_SCANNERS = threading.BoundedSemaphore(2)


def utf16_offsets(text):
    result = [0]
    for character in text:
        result.append(result[-1] + (2 if ord(character) > 0xffff else 1))
    return result


def link_info(link, source):
    return {'kind':link.kind, 'target':link.target, '_source':source}


def resolve_spans(plain, fragments, previous, cancelled):
    """Only plain Python values enter the scanner; no Qt object crosses threads."""
    units = utf16_offsets(plain)
    fences = [(units[a], units[b]) for a,b in fenced_ranges(plain)]
    spans, occupied = [], []
    for start, end, text, href, generated, inline in fragments:
        if cancelled(): return []
        if any(start < b and end > a for a,b in fences): continue
        if href:
            original = previous.get(href, {}).get('_source', href) if generated else href
            target = web_url(original)
            info = {'kind':'url','target':target,'_source':original} if target else {}
            spans.append((start, end, info));occupied.append((start,end))
        elif inline:
            offsets = utf16_offsets(text)
            for link in recognize_links(text, cancelled=cancelled):
                a, b = start+offsets[link.start], start+offsets[link.end]
                spans.append((a,b,link_info(link,text[link.start:link.end])));occupied.append((a,b))
    for link in recognize_links(plain, cancelled=cancelled):
        start, end = units[link.start], units[link.end]
        if not any(start < b and end > a for a,b in occupied):
            spans.append((start,end,link_info(link,plain[link.start:link.end])))
    return spans


class TextLinks(QObject):
    changed = Signal()
    resolved = Signal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._quick = self._document = None
        self._enabled, self._active = False, True
        self._color = QColor('#387756')
        self._applying, self._reading = False, False
        self._links, self._generation, self._pending = {}, 0, None
        self._results = queue.SimpleQueue()
        self._lifetime = {'alive': True, 'generation': 0}
        lifetime = self._lifetime
        self.destroyed.connect(lambda: lifetime.update(alive=False))
        self._applied_generation = -1
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._poll)
        self.resolved.connect(self._deliver)

    def get_document(self): return self._quick

    def set_document(self, quick):
        if quick is self._quick: return
        if self._document is not None and shiboken6.isValid(self._document):
            self._document.contentsChanged.disconnect(self._schedule)
        self._quick = quick
        self._document = quick.textDocument() if quick else None
        self._links = {}
        if self._document is not None:
            self._document.contentsChanged.connect(self._schedule)
        self.refresh()

    document = Property(QObject, get_document, set_document, notify=changed)

    def get_enabled(self): return self._enabled
    def set_enabled(self, value):
        if value != self._enabled:
            self._enabled = value;self.refresh()
    enabled = Property(bool, get_enabled, set_enabled, notify=changed)

    def get_active(self): return self._active
    def set_active(self, value):
        if value != self._active:
            current = self._applied_generation == self._generation
            self._active = value
            if current:
                # Hiding a retained page does not change its text or links.
                # Resume without rescanning and reformatting the document.
                self.changed.emit()
            else:
                self.refresh()
    active = Property(bool, get_active, set_active, notify=changed)

    def get_color(self): return self._color
    def set_color(self, value):
        if value != self._color:
            self._color = value;self.refresh()
    color = Property(QColor, get_color, set_color, notify=changed)
    pending = Property(bool, lambda self: self._reading or self._pending is not None, notify=changed)

    def _schedule(self):
        if not self._applying: self.refresh()

    @Slot(str, result='QVariantMap')
    def linkInfo(self, href):
        return self._links.get(href, {}) if self._applied_generation == self._generation else {}

    @Slot()
    def refresh(self):
        if self._applying: return
        self._generation += 1
        self._lifetime['generation'] = self._generation
        self._pending = None
        if self._document is not None and self._enabled and self._active:
            plain, fragments = self._document.toPlainText(), []
            block = self._document.begin()
            while plain and block.isValid():
                iterator = block.begin()
                while not iterator.atEnd():
                    fragment = iterator.fragment();style = fragment.charFormat()
                    fragments.append((fragment.position(), fragment.position()+fragment.length(),
                        fragment.text(), style.anchorHref(), bool(style.property(LINK_PROPERTY)),
                        style.fontFixedPitch() or style.hasProperty(QTextFormat.FontFamilies)))
                    iterator += 1
                block = block.next()
            if plain:
                self._pending = (self._generation, plain, fragments, self._links)
                self._timer.start(0)
        self.changed.emit()

    def _poll(self):
        if not self._reading:
            self._start()
            return
        try:
            generation, spans = self._results.get_nowait()
        except queue.Empty:
            self._timer.start(16)
            return
        self.resolved.emit(generation, spans)

    def _start(self):
        if self._reading or self._pending is None: return
        generation, plain, fragments, previous = self._pending
        self._pending, self._reading = None, True
        lifetime, results = self._lifetime, self._results
        def cancelled():
            return not lifetime['alive'] or lifetime['generation'] != generation
        def read():
            acquired = False
            try:
                while not cancelled():
                    acquired = _SCANNERS.acquire(timeout=.05)
                    if acquired: break
                result = resolve_spans(plain, fragments, previous, cancelled) if acquired and not cancelled() else []
            except Exception:
                result = []
            finally:
                if acquired: _SCANNERS.release()
            # QML can destroy the C++ owner while this thread is scanning.
            # Hand off only Python data; its GUI timer owns Qt delivery.
            results.put((generation, result))
        threading.Thread(target=read, daemon=True, name='conversation-links').start()
        # Poll only while a scanner is active, at the desktop frame cadence.
        self._timer.start(16)
        self.changed.emit()

    @Slot(int, object)
    def _deliver(self, generation, spans):
        self._reading = False
        if generation == self._generation and self._document is not None and shiboken6.isValid(self._document) and self._enabled and self._active:
            self._applying = True
            try:
                links, cursor = {}, QTextCursor(self._document)
                cursor.beginEditBlock()
                for start, end, info in spans:
                    style = QTextCharFormat()
                    if info:
                        href = 'umeko-conversation:' + str(len(links))
                        links[href] = info
                        style.setAnchor(True);style.setAnchorHref(href)
                        style.setProperty(LINK_PROPERTY, True)
                        style.setForeground(self._color);style.setFontUnderline(True)
                    else:
                        style.setAnchor(False);style.setAnchorHref('')
                    cursor.setPosition(start);cursor.setPosition(end, QTextCursor.KeepAnchor)
                    cursor.mergeCharFormat(style)
                self._links = links
                self._applied_generation = generation
                cursor.endEditBlock()
            finally:
                self._applying = False
        self.changed.emit()
        self._start()
