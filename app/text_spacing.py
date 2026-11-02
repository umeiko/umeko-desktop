"""Proportional paragraph spacing for Quick TextEdit prose, including Markdown."""
from PySide6.QtCore import QObject, Property, QTimer, Signal
from PySide6.QtGui import QTextBlockFormat, QTextCursor


class TextSpacing(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._quick = self._document = None
        self._factor = 1.0
        self._applying = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._apply)

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
        self._schedule()
        self.changed.emit()

    document = Property(QObject, get_document, set_document, notify=changed)

    def get_factor(self):
        return self._factor

    def set_factor(self, factor):
        if factor != self._factor:
            self._factor = factor
            self._schedule()
            self.changed.emit()

    factor = Property(float, get_factor, set_factor, notify=changed)

    def _schedule(self):
        if not self._applying:
            self._timer.start(0)

    def _apply(self):
        if self._document is None:
            return
        self._applying = True
        try:
            block = self._document.begin()
            cursor = QTextCursor(self._document)
            cursor.beginEditBlock()
            while block.isValid():
                style = block.blockFormat()
                height = self._factor * 100
                if (style.lineHeightType() != QTextBlockFormat.ProportionalHeight.value
                        or style.lineHeight() != height):
                    style.setLineHeight(height, QTextBlockFormat.ProportionalHeight.value)
                    cursor.setPosition(block.position())
                    cursor.setBlockFormat(style)
                block = block.next()
            cursor.endEditBlock()
        finally:
            self._applying = False
