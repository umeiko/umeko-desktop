"""Settings bridge and login launch policy; reuse the normal desktop/proxy runtime."""
from __future__ import annotations

from PySide6.QtCore import QObject, Property, QLockFile, Signal, Slot

from .login_startup import LoginStartup


class LoginStartupSettings(QObject):
    changed = Signal()

    def __init__(self, controller, *, manager=None, background=False):
        super().__init__(controller)
        self.controller = controller
        self.manager = manager if manager is not None else LoginStartup()
        self._background = background
        self._state = {}
        self.refresh()

    @Property('QVariantMap', notify=changed)
    def state(self):
        return self._state

    @Property(bool, constant=True)
    def background(self):
        return self._background

    @Slot()
    def refresh(self):
        try:
            self._state = self.manager.refresh()
        except (OSError, ValueError):
            self._state = {'available': False, 'reason': '无法读取系统开机启动设置。',
                           'umeko': False, 'proxy': False}
        self.changed.emit()

    @Slot(bool, bool)
    def setEnabled(self, umeko, proxy):
        try:
            self._state = self.manager.set_enabled(umeko, proxy)
        except (OSError, ValueError):
            self.controller.toast.emit('保存开机启动设置失败。')
            self.refresh()
            return
        self.changed.emit()


def start_login_proxy(controller, arguments):
    """Never toggle a running listener off or change its network/key policy."""
    if '--login-startup' in arguments and '--login-proxy' in arguments and not controller.serverRunning:
        controller.toggleServer()


def acquire_instance(directory):
    """One desktop instance per profile, without adding an IPC/network listener."""
    directory.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(directory / 'desktop-instance.lock'))
    # A slow but live process must not lose its lock based on elapsed time.
    lock.setStaleLockTime(0)
    return lock if lock.tryLock(0) else None
