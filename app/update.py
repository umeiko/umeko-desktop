"""Detached installer host; all file replacement runs in the shared Node engine."""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, Property, QProcess, QProcessEnvironment, QStandardPaths, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication
from .pi_runtime import node_executable


def update_environment():
    env = QProcessEnvironment.systemEnvironment()
    env.remove('NODE_OPTIONS'); env.remove('NODE_PATH')
    env.insert('PYINSTALLER_RESET_ENVIRONMENT', '1')
    if getattr(sys, 'frozen', False):
        for key in ('QT_PLUGIN_PATH', 'QML2_IMPORT_PATH', 'QML_IMPORT_PATH'):
            env.remove(key)
        if env.contains('LD_LIBRARY_PATH_ORIG'):
            env.insert('LD_LIBRARY_PATH', env.value('LD_LIBRARY_PATH_ORIG'))
        else:
            env.remove('LD_LIBRARY_PATH')
    return env


def save_job(file, job):
    file.write_text(json.dumps(job), encoding='utf-8')
    file.chmod(0o600)


class AppUpdater(QObject):
    changed = Signal(object)

    def __init__(self, controller):
        super().__init__(controller)
        self.controller = controller
        self.process = None
        self.job = {}
        self.job_file = None
        self.state = ''
        self.buffer = b''

    def publish(self, **value):
        self.state = value.get('state', self.state)
        if self.state == 'error' and 'message' in value: self._error = value['message']
        self.changed.emit(value)

    def install(self, release, download):
        if self.process: return
        if not getattr(sys, 'frozen', False):
            self.publish(state='error', message='仅打包版支持安装更新；源码版本请使用 Git 更新。', busy=False)
            return
        cache = Path(QStandardPaths.writableLocation(QStandardPaths.CacheLocation)) / 'updates' / uuid.uuid4().hex
        try:
            cache.mkdir(parents=True, mode=0o700)
            directory = Path(sys.executable).resolve().parent
            if sys.platform == 'darwin': directory = directory.parent.parent
            self.job = dict(repo='umeko-desktop', version=download.get('version', release['version']),
                archive=download['path'], archiveName=download.get('name', Path(download['path']).name), sha256=download['sha256'], cache=str(cache),
                installDir=str(directory), executable=sys.executable,
                resourceRelative=os.path.relpath(self.controller.root, directory),
                payloadRelative='Umeko.app' if sys.platform == 'darwin' else 'Umeko', parentPid=os.getpid(),
                restartArgs=[], profileDir=str(self.controller.store.directory), language=self.controller.language)
            self.job_file = cache / 'job.json'; save_job(self.job_file, self.job)
            self.run('prepare')
        except (OSError, KeyError, ValueError) as error:
            self.publish(state='error', message=str(error), busy=False)

    def run(self, mode):
        self.publish(state='downloading' if mode == 'download' else 'preparing', message='正在准备下载…' if mode == 'download' else '正在准备独立安装器…', busy=True, progress=-1)
        self.buffer = b''
        p = QProcess(self); self.process = p
        p.setProcessEnvironment(update_environment())
        p.readyReadStandardOutput.connect(lambda: self.consume(p))
        p.errorOccurred.connect(lambda error: self.process_error(p, error))
        p.finished.connect(lambda code, status: self.finished(p, mode, code, status))
        try:
            p.start(node_executable(), [str(self.controller.root / 'runtime/update-engine.mjs'), mode, str(self.job_file)])
        except RuntimeError as error:
            self.process = None; p.deleteLater()
            self.publish(state='error', message=str(error), busy=False)

    def process_error(self, p, error):
        self.publish(state='error', message='更新引擎运行失败：' + p.errorString(), busy=False)
        if error == QProcess.FailedToStart:
            self.process = None; p.deleteLater()

    def consume(self, p):
        self.buffer += bytes(p.readAllStandardOutput())
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            try:
                value = json.loads(line)
                if value.get('state') == 'ready':
                    self.job.update(archive=value['archive'], sha256=value['sha256'])
                    save_job(self.job_file, self.job)
                self.publish(**value)
            except (ValueError, OSError, KeyError) as error:
                self.publish(state='error', message='无法保存安装任务：' + str(error))

    def finished(self, p, mode, code, status):
        self.consume(p)
        self.process = None; p.deleteLater()
        if code or status != QProcess.NormalExit:
            self.publish(state='error', message='更新操作失败，请重试。' if self.state != 'error' else self.last_error, busy=False)
        elif mode == 'prepare' and self.state == 'prepared':
            self.launch_installer()
        else:
            self.publish(busy=False)

    @property
    def last_error(self):
        return getattr(self, '_error', '更新操作失败，请重试。')

    def cancel(self):
        if not self.process or self.state not in ('downloading', 'verifying'): return
        p = self.process
        p.readyReadStandardOutput.disconnect(); p.errorOccurred.disconnect(); p.finished.disconnect()
        p.kill(); p.waitForFinished(1000); p.deleteLater(); self.process = None
        shutil.rmtree(self.job_file.parent, ignore_errors=True)
        self.publish(state='available', message='下载已取消，可以重新下载。', busy=False)

    def launch_installer(self):
        try:
            job = json.loads(self.job_file.read_text(encoding='utf-8'))
            p = QProcess(self)
            p.setProgram(job['helperExe']); p.setArguments(['--install-update', str(self.job_file)])
            p.setWorkingDirectory(str(Path(job['helperExe']).parent)); p.setProcessEnvironment(update_environment())
            ok = p.startDetached(); p.deleteLater()
            if not ok: raise OSError('独立安装器启动失败，当前程序保持运行。')
            self.deadline = time.monotonic() + 30
            self.timer = QTimer(self); self.timer.timeout.connect(self.wait_ready); self.timer.start(150)
        except (OSError, ValueError, KeyError) as error:
            self.publish(state='error', message=str(error), busy=False)

    def wait_ready(self):
        if Path(str(self.job_file) + '.ready').is_file():
            self.timer.stop()
            try: save_job(Path(str(self.job_file) + '.commit'), dict(confirmed=True))
            except OSError as error:
                self.publish(state='error', message='无法确认安装交接，当前程序保持运行：' + str(error), busy=False)
                return
            self.publish(message='正在停止所有 Agent 并保存工作记录…')
            self.controller.close()
            QGuiApplication.instance().quit()
        elif time.monotonic() > self.deadline:
            self.timer.stop()
            try: save_job(Path(str(self.job_file) + '.cancel'), dict(cancelled=True))
            except OSError: pass
            self.publish(state='error', message='安装器未能就绪，当前程序保持运行。请重新下载后重试。', busy=False)


class UpdateInstaller(QObject):
    changed = Signal()

    def __init__(self, root, job_file):
        super().__init__()
        self.root, self.job_file = root, Path(job_file)
        self._status = dict(state='waiting', message='正在准备安装…', progress=-1)
        self.buffer = b''
        self.job = {}
        self.terminal_status = None
        self.process = QProcess(self)
        self.process.setProcessEnvironment(update_environment())
        self.process.readyReadStandardOutput.connect(self.consume)
        self.process.errorOccurred.connect(lambda _: self.set_error('安装引擎启动失败：' + self.process.errorString()))
        self.process.finished.connect(self.finished)

    @Property('QVariantMap', notify=changed)
    def status(self): return self._status

    @Property(str, notify=changed)
    def language(self): return self.job.get('language', 'zh')

    def set_error(self, message):
        self._status = dict(state='error', message=message); self.changed.emit()

    def begin(self):
        try:
            self.job = json.loads(self.job_file.read_text(encoding='utf-8'))
            self.changed.emit()
            self.process.start(node_executable(), [str(self.root / 'runtime/update-engine.mjs'), 'install', str(self.job_file)])
        except (OSError, ValueError, RuntimeError) as error:
            self.set_error(str(error))

    def ready(self):
        try: save_job(Path(str(self.job_file) + '.ready'), dict(pid=os.getpid()))
        except OSError as error:
            self.process.kill(); self.set_error('无法创建安装器启动信号：' + str(error))

    def consume(self):
        self.buffer += bytes(self.process.readAllStandardOutput())
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            try:
                self._status = json.loads(line)
                if self._status['state'] in ('complete', 'error'):
                    self.terminal_status = self._status
                    self._status = dict(state='finishing', message='正在完成安装…', progress=1)
                self.changed.emit()
            except ValueError: self.set_error('安装状态信息无效')
            if self._status['state'] == 'waiting': self.ready()

    def finished(self, code, exit_status):
        self.consume()
        if self.terminal_status:
            self._status = self.terminal_status; self.changed.emit()
        if (code or exit_status != QProcess.NormalExit or not self.terminal_status) and self._status['state'] != 'error':
            self.set_error('安装中断。旧版本备份和安装日志已保留。')

    @Slot()
    def finish(self):
        if self._status['state'] == 'error':
            QGuiApplication.instance().quit(); return
        if self._status['state'] != 'complete': return
        p = QProcess(self)
        p.setProgram(self.job['executable']); p.setArguments(self.job.get('restartArgs', []))
        p.setWorkingDirectory(self.job['installDir'])
        environment = update_environment()
        if self.job.get('profileDir'): environment.insert('UMEKO_DATA_DIR', self.job['profileDir'])
        p.setProcessEnvironment(environment)
        ok = p.startDetached(); p.deleteLater()
        if ok:
            resources = Path(self.job['installDir']) / self.job['resourceRelative']
            cleaner = QProcess(self)
            cleaner.setProgram(str(resources / 'runtime/node' / ('node.exe' if os.name == 'nt' else 'bin/node')))
            cleaner.setArguments([str(resources / 'runtime/update-engine.mjs'), 'cleanup', str(self.job_file)])
            cleaner.setWorkingDirectory(self.job['installDir']); cleaner.setProcessEnvironment(update_environment())
            cleaner.startDetached(); cleaner.deleteLater()
            QGuiApplication.instance().quit()
        else:
            self._status['launchError'] = ('Launch failed. Retry or open: ' if self.language == 'en' else '启动失败，请重试或从安装目录手动启动：') + self.job['executable']
            self.changed.emit()
