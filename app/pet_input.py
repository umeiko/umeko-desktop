"""Native input regions for transparent desktop pet windows."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QRect, QRectF, QSize, QSizeF, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QBitmap, QImage, QImageReader, QPainter, QPainterPath, QRegion, QTransform, QWindow


def _animation_silhouette(path):
    reader = QImageReader(path)
    size = reader.size()
    if size.isEmpty():
        return QImage()
    size = size.scaled(QSize(320, 480), Qt.KeepAspectRatio)
    reader.setScaledSize(size)
    silhouette = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    silhouette.fill(Qt.transparent)
    # Exclude nearly invisible matte remnants without removing pale artwork.
    threshold = bytes([0] * 16 + [255] * 240)
    painter = QPainter(silhouette)
    try:
        for _ in range(max(1, reader.imageCount())):
            frame = reader.read()
            if frame.isNull():
                break
            alpha = frame.convertToFormat(QImage.Format.Format_Alpha8)
            data = bytes(alpha.constBits()).translate(threshold)
            mask = QImage(data, alpha.width(), alpha.height(), alpha.bytesPerLine(), alpha.format())
            painter.drawImage(0, 0, mask)
    finally:
        painter.end()
    return silhouette


class PetInputMask(QObject):
    changed = Signal()
    _decoded = Signal(object)

    def __init__(self, parent):
        super().__init__(parent)
        self._cache = OrderedDict()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='pet-input-mask')
        self._pending = None
        self._path = ''
        self._last_shape = None
        self._decoded.connect(self._finish, Qt.QueuedConnection)

    def clear(self):
        if self._pending is not None:
            self._pending.cancel()
            self._pending = None
        self._cache.clear()
        self._path = ''
        self._last_shape = None
        self.changed.emit()

    def close(self):
        self._executor.shutdown(wait=False, cancel_futures=True)
        self.clear()

    def _finish(self, future):
        if future is not self._pending:
            return
        self._pending = None
        try:
            image = future.result()
        except (RuntimeError, ValueError):
            image = QImage()
        region = QRegion(QBitmap.fromImage(image.createAlphaMask())) if not image.isNull() else QRegion()
        self._cache[self._path] = (image.size(), region)
        if len(self._cache) > 16:
            self._cache.popitem(last=False)
        self.changed.emit()

    def _shape(self, path):
        if path in self._cache:
            self._cache.move_to_end(path)
            self._last_shape = self._cache[path]
        elif path != self._path and path:
            if self._pending is not None:
                self._pending.cancel()
            self._path = path
            self._pending = self._executor.submit(_animation_silhouette, path)

            def finished(future):
                try:
                    self._decoded.emit(future)
                except RuntimeError:
                    pass  # The pet may have closed during decode.

            self._pending.add_done_callback(finished)
        return self._last_shape if path else None

    @Slot(QWindow, QUrl, QRectF, float, QRectF, QRectF)
    def update(self, window, source, art, tilt, bubble, reminder):
        region = QRegion()
        shape = self._shape(source.toLocalFile())
        if shape is not None:
            size, silhouette = shape
            if not silhouette.isEmpty() and not art.isEmpty():
                fitted = QSizeF(size).scaled(art.size(), Qt.KeepAspectRatio)
                center = art.center()
                transform = QTransform().translate(center.x(), center.y()).rotate(tilt)
                transform.translate(-fitted.width() / 2, art.height() / 2 - fitted.height())
                transform.scale(fitted.width() / size.width(), fitted.height() / size.height())
                outline = transform.map(silhouette)
                # Allow for antialiased pixels at the displayed outline.
                region = outline | outline.translated(-1, 0) | outline.translated(1, 0)
                region |= outline.translated(0, -1) | outline.translated(0, 1)
        for rectangle in (bubble, reminder):
            if not rectangle.isEmpty():
                path = QPainterPath()
                path.addRoundedRect(rectangle, 12, 12)
                region |= QRegion(path.toFillPolygon().toPolygon())
        # An empty Qt mask resets the window to its full rectangular hit area.
        if region.isEmpty():
            region = QRegion(QRect(-1, -1, 1, 1))
        if region != window.mask():
            window.setMask(region)
