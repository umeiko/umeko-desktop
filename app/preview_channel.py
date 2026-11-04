"""Preferences-facing source channel jobs, using the existing background job host."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import threading

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication

from .npm_config import npm_environment
from .preview_launch import channel_state, start_channel, wait_for_previous_process
from .preview_source import PreviewSource, PreviewError
from .preview_network import network_failure
from .update import update_environment
from .update_proxy import system_proxy


class PreviewChannel(QObject):
    changed = Signal()
    progress = Signal(object)

    def __init__(self, controller):
        super().__init__(controller)
        self.controller = controller
        self.directory = Path(controller.store.directory)
        self._state = channel_state(self.directory)
        self._status = {}
        self._busy = False
        self._cancel = threading.Event()
        self._plan = None
        self._manager = None
        self.progress.connect(self._progress)
        controller.jobDone.connect(self._finished)
        if getattr(sys, 'frozen', False) and self.cleanupPending:
            QTimer.singleShot(0, self.finishRemoval)

    @Property(str, notify=changed)
    def channel(self): return self._state.get('channel', 'release')

    @Property(bool, notify=changed)
    def supported(self):
        return (sys.platform in ('win32', 'darwin', 'linux') and
                (getattr(sys, 'frozen', False) or bool(self._state.get('releaseExecutable'))))

    @Property(bool, notify=changed)
    def busy(self): return self._busy

    @Property(bool, notify=changed)
    def cleanupPending(self): return bool(self._state.get('removeCheckoutPending'))

    @Property('QVariantMap', notify=changed)
    def status(self): return self._status

    def _environment(self):
        qt = update_environment()
        environment = {key: qt.value(key) for key in qt.keys()}
        environment.update({key: value for key, value in npm_environment(self.controller.store.data.get('agent', {})).items()
                            if key.lower().startswith('npm_config_')})
        # Provider network settings are deliberately not global update settings.
        proxy = system_proxy('https://github.com/umeiko/umeko-desktop.git')
        environment['UMEKO_UPDATE_PROXY'] = proxy
        if getattr(sys, 'frozen', False):
            from .pi_runtime import node_executable
            environment['PATH'] = str(Path(node_executable()).parent) + os.pathsep + environment.get('PATH', '')
        return environment

    def _start(self, operation):
        if self._busy: return
        self._busy = True
        self._cancel.clear()
        self._status = {'state': 'working', 'message': '正在准备预览版操作…'}
        self.changed.emit()

        def work():
            try:
                environment = self._environment()
                if self._manager is None:
                    release = Path(sys.executable) if getattr(sys, 'frozen', False) else None
                    self._manager = PreviewSource(self.directory, release, environment,
                                                  self.progress.emit, self._cancel.is_set)
                else:
                    self._manager.environment = environment
                return operation(self._manager)
            except PreviewError as error:
                if error.category:
                    return {'state': 'error', 'message': error.message, **network_failure(error.category),
                            **({'limitation': error.limitation} if error.limitation else {})}
                return {'state': 'cancelled' if self._cancel.is_set() else 'error',
                        'message': error.message, 'detail': error.detail}
            except (OSError, ValueError, RuntimeError) as error:
                return {'state': 'error', 'message': '预览版操作失败，当前应用保持可用。', 'detail': str(error)}
        self.controller._job('preview-channel', work)

    @Slot(object)
    def _progress(self, value):
        if not self.controller._closing:
            self._status = dict(value)
            self.changed.emit()

    def _finished(self, name, result):
        if name != 'preview-channel': return
        self._busy = False
        if self.controller._closing: return
        self._status = result['value'] if result['ok'] else {'state': 'error', 'message': str(result['value'])}
        self._state = channel_state(self.directory)
        if self._status.get('state') in ('available', 'current'):
            self._plan = dict(self._status)
        self.changed.emit()

    @Slot()
    def preflight(self):
        if not self.supported or self.channel != 'release': return
        def operation(manager):
            result = manager.preflight()
            return {**result, 'state': 'prerequisites', 'message': '请确认运行前提和配置兼容性，再安装预览版。'}
        self._start(operation)

    @Slot()
    def switchToPreview(self):
        if self._status.get('state') != 'prerequisites' or not self._status.get('ready'): return
        self._start(lambda manager: manager.switch_to_preview())

    @Slot()
    def checkUpdates(self):
        if self.channel == 'preview': self._start(lambda manager: manager.check_update())

    @Slot()
    def applyUpdate(self):
        if self.channel == 'preview' and self._plan:
            plan = self._plan
            self._start(lambda manager: manager.apply_update(plan))

    @Slot(bool)
    def switchToRelease(self, remove_checkout=False):
        def operation(manager):
            try:
                return manager.switch_to_release(remove_checkout=remove_checkout)
            except PreviewError as error:
                if manager.read_state().get('channel') != 'release': raise
                return {'state': 'restart-required', 'channel': 'release',
                        'message': '已切回正式版，源码已保留。', 'detail': str(error)}
        self._start(operation)

    @Slot()
    def finishRemoval(self):
        if self.channel != 'release' or not self.cleanupPending: return
        def operation(manager):
            wait_for_previous_process(self._state.get('cleanupParentPid'))
            return manager.remove_retained_checkout()
        self._start(operation)

    @Slot()
    def cancel(self): self._cancel.set()

    @Slot()
    def restart(self):
        if self._busy or self._status.get('state') != 'restart-required': return
        try:
            self.controller.store.save()
            start_channel(self.directory, self._state)
        except OSError as error:
            self._status = {'state': 'error', 'message': '无法启动所选通道，当前应用保持运行。', 'detail': str(error)}
            self.changed.emit()
            return
        self.controller.close()
        QGuiApplication.instance().quit()
