"""Close the main window into the system tray without stopping its agents."""
from PySide6.QtCore import QObject, QEvent, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QGuiApplication, QWindow
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


class TrayController(QObject):
    quitRequested = Signal()
    notificationRequested = Signal(str)

    def __init__(self, window, icon, parent=None):
        super().__init__(parent)
        self.window = window
        self.quitting = False
        self.english = False
        self.previous_visibility = QWindow.Windowed
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setObjectName('umekoTrayIcon')
        self.tray.setToolTip('Umeko')
        self.menu = QMenu()
        self.menu.setObjectName('umekoTrayMenu')
        self.open_action = self.menu.addAction('打开 Umeko')
        self.open_action.setObjectName('trayShowAction')
        self.menu.addSeparator()
        self.quit_action = self.menu.addAction('退出')
        self.quit_action.setObjectName('trayQuitAction')
        self.quit_action.setMenuRole(QAction.QuitRole)
        self.tray.setContextMenu(self.menu)
        self.open_action.triggered.connect(self.restore)
        self.quit_action.triggered.connect(self.requestQuit)
        self.tray.activated.connect(self.activated)
        self.tray.messageClicked.connect(self.restore)
        self.app = QGuiApplication.instance()
        self.app.setQuitOnLastWindowClosed(False)
        self.app.aboutToQuit.connect(self.mark_quitting)
        window.destroyed.connect(self.window_destroyed)
        window.installEventFilter(self)
        self.app.installEventFilter(self)
        self.availability = QTimer(self)
        self.availability.setInterval(2000)
        self.availability.timeout.connect(self.refresh)
        if not self.refresh(): self.availability.start()

    def window_destroyed(self):
        self.window = None
        self.availability.stop()
        self.tray.hide()
        self.app.removeEventFilter(self)

    def tray_available(self):
        return QSystemTrayIcon.isSystemTrayAvailable()

    def set_language(self, language):
        self.english = language == 'en'
        self.open_action.setText('Open Umeko' if self.english else '打开 Umeko')
        self.quit_action.setText('Quit' if self.english else '退出')

    def refresh(self):
        if self.tray_available() and not self.tray.icon().isNull() and not self.quitting:
            self.tray.show(); self.availability.stop(); return True
        return False

    def eventFilter(self, watched, event):
        if watched is self.app and event.type() == QEvent.Quit:
            self.mark_quitting()
        if watched is self.window and event.type() == QEvent.Close and not self.quitting:
            event.ignore()
            self.minimize_to_tray()
            return True
        return super().eventFilter(watched, event)

    def minimize_to_tray(self):
        if self.window is None: return
        if self.window.visibility() not in (QWindow.Minimized, QWindow.Hidden):
            self.previous_visibility = self.window.visibility()
        if self.tray_available() and not self.tray.icon().isNull():
            self.tray.show()
            self.window.hide()
            message = 'Minimized to the system tray. Agents keep running. Right-click the Yanami icon to quit.' if self.english else '已最小化到系统托盘。Agent 继续运行，右键八奈见头像可退出。'
            self.notificationRequested.emit(message)
            self.tray.showMessage('Umeko', message, self.tray.icon(), 4000)
        else:
            self.window.showMinimized()
            self.notificationRequested.emit('System tray unavailable. Minimized to the taskbar; agents keep running.' if self.english else '系统托盘不可用，已最小化到任务栏。Agent 继续运行。')

    def activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick): self.restore()

    @Slot()
    def restore(self):
        if self.window is None or self.quitting: return
        if not self.window.isVisible() or self.window.visibility() == QWindow.Minimized:
            if self.previous_visibility == QWindow.Maximized: self.window.showMaximized()
            elif self.previous_visibility == QWindow.FullScreen: self.window.showFullScreen()
            else: self.window.showNormal()
        self.window.raise_(); self.window.requestActivate()

    def mark_quitting(self):
        self.quitting = True; self.availability.stop(); self.tray.hide()

    @Slot()
    def requestQuit(self):
        if self.quitting: return
        self.mark_quitting()
        self.quitRequested.emit()
