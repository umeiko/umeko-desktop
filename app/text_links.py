"""Decorate rendered chat text without replacing Markdown or changing glyph metrics."""
from urllib.parse import unquote

from PySide6.QtCore import QObject, Property, Signal, Slot
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor, QTextFormat

from .conversation_links import fenced_ranges, recognize_links, web_url

LINK_PROPERTY = QTextFormat.UserProperty + 55


class TextLinks(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._quick = self._document = None
        self._workspace = ""
        self._enabled = False
        self._active = True
        self._color = QColor("#387756")
        self._applying = False
        self._links = {}

    def get_document(self):
        return self._quick

    def set_document(self, quick):
        if quick is self._quick:
            return
        if self._document is not None:
            self._document.contentsChanged.disconnect(self._schedule)
        self._quick = quick
        self._document = quick.textDocument() if quick else None
        if self._document is not None:
            self._document.contentsChanged.connect(self._schedule)
        self.refresh()
        self.changed.emit()

    document = Property(QObject, get_document, set_document, notify=changed)

    def get_workspace(self):
        return self._workspace

    def set_workspace(self, value):
        if value != self._workspace:
            self._workspace = value
            self.refresh()
            self.changed.emit()

    workspace = Property(str, get_workspace, set_workspace, notify=changed)

    def get_enabled(self):
        return self._enabled

    def set_enabled(self, value):
        if value != self._enabled:
            self._enabled = value
            self.refresh()
            self.changed.emit()

    enabled = Property(bool, get_enabled, set_enabled, notify=changed)

    def get_active(self):
        return self._active

    def set_active(self, value):
        if value != self._active:
            self._active = value
            if value:
                self.refresh()
            self.changed.emit()

    active = Property(bool, get_active, set_active, notify=changed)

    def get_color(self):
        return self._color

    def set_color(self, value):
        if value != self._color:
            self._color = value
            self.refresh()
            self.changed.emit()

    color = Property(QColor, get_color, set_color, notify=changed)

    def _schedule(self):
        if not self._applying:
            if not self._active:
                self._links = {}
            self.refresh()

    @Slot(str, result="QVariantMap")
    def linkInfo(self, href):
        return self._links.get(href, {})

    @Slot()
    def refresh(self):
        if self._document is None or self._applying or not self._enabled or not self._active:
            return
        self._applying = True
        try:
            document = self._document
            plain = document.toPlainText()
            fences = [(self._utf16(plain[:a]), self._utf16(plain[:b])) for a, b in fenced_ranges(plain)]
            spans, occupied = [], []
            block = document.begin()
            # Read the already-rendered document. Fenced blocks live in a
            # separate SelectableText with this decorator disabled.
            while block.isValid():
                iterator = block.begin()
                while not iterator.atEnd():
                    fragment = iterator.fragment()
                    style = fragment.charFormat()
                    start, end = fragment.position(), fragment.position() + fragment.length()
                    if any(start < b and end > a for a, b in fences):
                        iterator += 1
                        continue
                    href = style.anchorHref()
                    if href:
                        info = self._links.get(href) if style.property(LINK_PROPERTY) else None
                        if info is None:
                            target = web_url(href)
                            if target:
                                info = {"kind": "url", "target": target}
                            else:
                                local = unquote(href)
                                matches = recognize_links(local, self._workspace)
                                info = self._info(matches[0]) if len(matches) == 1 and matches[0].start == 0 and matches[0].end == len(local) else {}
                        # Recheck local existence when rebuilding/restoring.
                        if info and info["kind"] == "path":
                            from pathlib import Path
                            if not Path(info["target"]).exists():
                                info = {}
                        spans.append((start, end, info))
                        occupied.append((start, end))
                    elif style.fontFixedPitch() or style.hasProperty(QTextFormat.FontFamilies):
                        # Inline-code spans preserve spaces in filenames.
                        for link in recognize_links(fragment.text(), self._workspace):
                            a = start + self._utf16(fragment.text()[:link.start])
                            b = start + self._utf16(fragment.text()[:link.end])
                            spans.append((a, b, self._info(link)))
                            occupied.append((a, b))
                    iterator += 1
                block = block.next()
            for link in recognize_links(plain, self._workspace):
                start = self._utf16(plain[:link.start])
                end = self._utf16(plain[:link.end])
                if not any(start < b and end > a for a, b in occupied):
                    spans.append((start, end, self._info(link)))
            links = {}
            cursor = QTextCursor(document)
            cursor.beginEditBlock()
            for start, end, info in spans:
                style = QTextCharFormat()
                if info:
                    href = "umeko-conversation:" + str(len(links))
                    links[href] = info
                    style.setAnchor(True)
                    style.setAnchorHref(href)
                    style.setProperty(LINK_PROPERTY, True)
                    style.setForeground(self._color)
                    style.setFontUnderline(True)
                else:
                    # Unsupported Markdown schemes remain inert text.
                    style.setAnchor(False)
                    style.setAnchorHref("")
                cursor.setPosition(start)
                cursor.setPosition(end, QTextCursor.KeepAnchor)
                cursor.mergeCharFormat(style)
            self._links = links
            cursor.endEditBlock()
        finally:
            self._applying = False

    @staticmethod
    def _utf16(text):
        return len(text.encode("utf-16-le")) // 2

    @staticmethod
    def _info(link):
        return {"kind": link.kind, "target": link.target,
                "line": link.line or 0, "column": link.column or 0}
