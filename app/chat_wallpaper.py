"""Prepare and save a local image for the chat canvas."""
from concurrent.futures import ThreadPoolExecutor
from math import isfinite
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from uuid import uuid4

from PySide6.QtCore import QObject, Property, QSize, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QImageReader


KEY = 'chatWallpaper'
DEFAULTS = {'mode': 'fill', 'opacity': None, 'zoom': 100, 'offsetX': 0, 'offsetY': 0, 'angle': 0}
MAX_OPACITY = 35
ASSET_NAME = re.compile(r'[a-f0-9]{32}\.(?:jpg|png)')
INVALID_IMAGE = '无法读取背景图，请选择有效的 PNG、JPG 或 WebP 图片。'
LARGE_IMAGE = '背景图须小于 64 MiB，且不超过 6400 万像素。'
SAVE_ERROR = '无法保存聊天背景，请检查应用数据目录。'


def _number(value, default):
    if type(value) is int or (type(value) is float and isfinite(value)):
        return value
    return default


def _options(value):
    opacity = _number(value.get('opacity'), None)
    zoom = _number(value.get('zoom'), DEFAULTS['zoom'])
    offsets = {}
    for axis in ('offsetX', 'offsetY'):
        offset = _number(value.get(axis), 0)
        offsets[axis] = round(max(-1, min(1, offset)), 4)
    angle = _number(value.get('angle'), 0)
    return {
        'mode': 'fit' if value.get('mode') == 'fit' else 'fill',
        'opacity': None if opacity is None else max(0, min(MAX_OPACITY, opacity)),
        'zoom': round(max(50, min(200, zoom))),
        **offsets, 'angle': round((angle % 360 + 180) % 360 - 180, 1),
    }


def _prepare_image(source, directory):
    if not source.is_file():
        raise ValueError(INVALID_IMAGE)
    if source.stat().st_size >= 64 * 1024 * 1024:
        raise ValueError(LARGE_IMAGE)
    reader = QImageReader(str(source))
    reader.setDecideFormatFromContent(True)
    reader.setAutoTransform(True)
    size = reader.size()
    if bytes(reader.format()) not in (b'png', b'jpeg', b'webp') or size.isEmpty():
        raise ValueError(INVALID_IMAGE)
    if size.width() * size.height() > 64_000_000:
        raise ValueError(LARGE_IMAGE)
    if max(size.width(), size.height()) > 3072:
        reader.setScaledSize(size.scaled(QSize(3072, 3072), Qt.KeepAspectRatio))
    image = reader.read()
    if image.isNull():
        raise ValueError(INVALID_IMAGE)

    directory.mkdir(parents=True, exist_ok=True)
    staging = TemporaryDirectory(prefix='.preview-', dir=directory, ignore_cleanup_errors=True)
    suffix = 'png' if image.hasAlphaChannel() else 'jpg'
    path = Path(staging.name) / f'{uuid4().hex}.{suffix}'
    if not image.save(str(path), quality=90 if suffix == 'jpg' else -1):
        staging.cleanup()
        raise ValueError(SAVE_ERROR)
    return staging, path, source.name


class ChatWallpaper(QObject):
    changed = Signal()
    draftChanged = Signal()
    _prepared = Signal(object)

    def __init__(self, store, parent):
        super().__init__(parent)
        self._store = store
        self._directory = store.directory.resolve() / 'chat-wallpaper'
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='chat-wallpaper')
        self._pending = None
        self._cancel_pending = False
        self._candidate = None
        self._error = ''
        self._prepared.connect(self._finish, Qt.QueuedConnection)

    def _stored(self):
        saved = self._store.data.get(KEY)
        if not isinstance(saved, dict):
            return {}
        value = dict(saved)
        asset = value.get('asset')
        if not isinstance(asset, str) or not ASSET_NAME.fullmatch(asset):
            value.pop('asset', None)
        return value

    @Property('QVariantMap', constant=True)
    def defaults(self):
        return dict(DEFAULTS)

    @Property(int, constant=True)
    def maximumOpacity(self):
        return MAX_OPACITY

    @Property('QVariantMap', notify=changed)
    def settings(self):
        saved = self._stored()
        source, name = '', ''
        if saved.get('asset'):
            path = self._directory / saved['asset']
            if path.is_file():
                source = QUrl.fromLocalFile(str(path)).toString()
                name = saved['name'] if isinstance(saved.get('name'), str) else ''
            else:
                return {**DEFAULTS, 'source': '', 'name': ''}
        return {**_options(saved), 'source': source, 'name': name}

    @Property('QVariantMap', notify=draftChanged)
    def draft(self):
        source, name = '', ''
        if self._candidate is not None:
            _, path, name = self._candidate
            source = QUrl.fromLocalFile(str(path)).toString()
        return {'source': source, 'name': name, 'busy': self._pending is not None, 'error': self._error}

    @Slot(QUrl)
    def chooseImage(self, url):
        if self._pending is not None:
            return
        if not url.isLocalFile():
            self._error = INVALID_IMAGE
            self.draftChanged.emit()
            return
        self._error = ''
        self._cancel_pending = False
        self._pending = self._executor.submit(_prepare_image, Path(url.toLocalFile()), self._directory)
        self._pending.add_done_callback(self._notify)
        self.draftChanged.emit()

    def _notify(self, future):
        try:
            self._prepared.emit(future)
        except RuntimeError:
            pass  # The application may have closed while decoding.

    def _release_candidate(self):
        candidate, self._candidate = self._candidate, None
        if candidate is not None:
            candidate[0].cleanup()

    def _finish(self, future):
        self._pending = None
        if not self._cancel_pending:
            try:
                candidate = future.result()
            except (OSError, RuntimeError):
                self._error = SAVE_ERROR
            except ValueError as error:
                self._error = str(error)
            else:
                self._release_candidate()
                self._candidate = candidate
        elif not future.cancelled() and future.exception() is None:
            future.result()[0].cleanup()
        self.draftChanged.emit()

    @Slot()
    def discard(self):
        self._cancel_pending = True
        self._release_candidate()
        self._error = ''
        self.draftChanged.emit()

    @Slot(bool, 'QVariantMap', result=bool)
    def apply(self, clear_saved_image, options):
        if self._pending is not None:
            return False
        previous = self._stored()
        old_value = self._store.data.get(KEY)
        asset = name = ''
        destination = None
        try:
            if self._candidate is not None:
                _, path, name = self._candidate
                asset = path.name
                destination = self._directory / asset
                path.replace(destination)
            elif not clear_saved_image and previous.get('asset') and (self._directory / previous['asset']).is_file():
                asset, name = previous['asset'], previous.get('name', '')
            value = _options(options)
            if asset:
                value.update(asset=asset, name=name)
            if value == DEFAULTS:
                self._store.data.pop(KEY, None)
            else:
                self._store.data[KEY] = value
            if old_value != self._store.data.get(KEY):
                self._store.save()
        except (OSError, RuntimeError):
            if old_value is None:
                self._store.data.pop(KEY, None)
            else:
                self._store.data[KEY] = old_value
            if destination is not None and destination.exists():
                try:
                    destination.replace(path)
                except OSError:
                    self._release_candidate()
            self._error = SAVE_ERROR
            self.draftChanged.emit()
            return False

        current = self._stored().get('asset')
        for unused in {previous.get('asset'), asset} - {None, '', current}:
            try:
                (self._directory / unused).unlink(missing_ok=True)
            except OSError:
                pass
        self.discard()
        self.changed.emit()
        return True

    def close(self):
        self.discard()
        self._executor.shutdown(wait=False, cancel_futures=True)
