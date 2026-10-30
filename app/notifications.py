"""Native task notifications. The operating system owns banners, sound and dismissal."""
import ctypes
import os
import sys
import uuid
from pathlib import Path
from PySide6.QtCore import QObject, QTimer, Signal, Slot, QStandardPaths, QEvent
from PySide6.QtGui import QWindow, QGuiApplication


class NativeCenter:
    def __init__(self, root, icon):
        self.library = None
        self.desktop = None
        if sys.platform.startswith('linux'):
            try:
                from app.desktop_notifications import DesktopCenter
                self.desktop = DesktopCenter(icon)
            except ImportError: pass
            return
        name = 'umeko_notifications.dll' if os.name == 'nt' else 'libumeko_notifications.dylib'
        if sys.platform not in ('win32', 'darwin'): return
        if os.name == 'nt' and not getattr(sys, 'frozen', False): return
        path = Path(root) / 'notification-runtime' / name
        if not path.is_file(): path = Path(root) / 'build/notification-runtime' / name
        if not path.is_file(): return
        try:
            library = ctypes.CDLL(str(path))
            library.umeko_notify_init.argtypes = [ctypes.c_char_p] * 3
            library.umeko_notify_show.argtypes = [ctypes.c_char_p] * 3
            library.umeko_notify_poll.restype = ctypes.c_char_p
            if library.umeko_notify_init(b'io.github.umeiko.umeko-desktop', b'Umeko', icon.encode()): self.library = library
        except (OSError, AttributeError): pass

    def send(self, identifier, title, body):
        if self.desktop is not None: return self.desktop.send(identifier, title, body)
        if self.library is None: return 0
        return self.library.umeko_notify_show(identifier.encode(), title.encode(), body.encode())

    def poll(self):
        if self.desktop is not None: return self.desktop.poll()
        if self.library is None: return None
        value = self.library.umeko_notify_poll()
        return value.decode('utf-8') if value else None

    def close(self):
        if self.desktop is not None: self.desktop.close()


class TaskNotifications(QObject):
    activated = Signal(str)
    posted = Signal(str, str, str)

    def __init__(self, window, tray, root, parent=None, native=None):
        super().__init__(parent)
        self.window, self.tray = window, tray
        self.language = 'zh'; self.closing = False
        self.pending = {}; self.dbus_ids = {}; self.fallback = ''
        cache = Path(QStandardPaths.writableLocation(QStandardPaths.CacheLocation)) / 'notifications'
        self.icon = ''
        try:
            cache.mkdir(parents=True, exist_ok=True)
            self.icon = str(cache/'yanami.png')
            if not tray.icon().pixmap(96, 96).save(self.icon): self.icon = ''
        except OSError: pass
        self.native = native or NativeCenter(root, self.icon)
        self.timer = QTimer(self); self.timer.setInterval(150); self.timer.timeout.connect(self.poll); self.timer.start()
        tray.messageClicked.connect(self.fallback_clicked)
        window.installEventFilter(self)
        window.destroyed.connect(self.close)
        QGuiApplication.instance().aboutToQuit.connect(self.close)

    def eventFilter(self, watched, event):
        if watched is self.window and event.type() == QEvent.Hide: self.fallback = ''
        return False

    @Slot()
    def close(self):
        self.closing = True; self.timer.stop(); self.pending.clear()
        if hasattr(self.native, 'close'): self.native.close()

    @Slot(str, str, bool, bool)
    def task_finished(self, session_id, title, success, long_running=False):
        if self.closing or not session_id: return
        if self.window.isVisible() and self.window.visibility() != QWindow.Minimized and not long_running: return
        english = self.language == 'en'
        heading = 'Umeko · ' + (('Task complete' if success else 'Task needs attention') if english else ('任务完成' if success else '任务未完成'))
        label = ' '.join(title.split())[:160] or ('Conversation' if english else '会话')
        body = label + '\n' + ('Click to view the result.' if english else '点击查看结果。')
        identifier = uuid.uuid4().hex
        self.pending[identifier] = session_id
        # Keep routing memory bounded even if notifications are never dismissed.
        while len(self.pending) > 128: self.pending.pop(next(iter(self.pending)))
        result = self.native.send(identifier, heading, body)
        if result == 0:
            self.fallback = identifier
            self.tray.showMessage(heading, body, self.tray.icon(), 8000)
        elif result < 0:
            self.pending.pop(identifier, None)
            return
        self.posted.emit(session_id, heading, body)

    def activate(self, identifier):
        session = self.pending.pop(identifier, '')
        if session and not self.closing: self.activated.emit(session)

    @Slot()
    def fallback_clicked(self):
        identifier, self.fallback = self.fallback, ''
        self.activate(identifier)

    @Slot()
    def poll(self):
        for _ in range(128):
            value = self.native.poll()
            if not value: break
            kind, _, identifier = value.partition(':')
            if kind == 'clicked': self.activate(identifier)
            else: self.pending.pop(identifier, None)
