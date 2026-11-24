"""Workspace chooser for ordinary Pi sessions."""
from __future__ import annotations

import glob
import hashlib
import os
import posixpath
import re
import shlex
import shutil
from pathlib import Path

from PySide6.QtCore import QObject, Property, QProcess, QTimer, QUrl, Signal, Slot

HOST = re.compile(r'(?:[a-zA-Z0-9_][a-zA-Z0-9_.-]*@)?(?:[a-zA-Z0-9_][a-zA-Z0-9_.-]*|\[[a-fA-F0-9:.]+\])')
SSH_OPTIONS = [
    '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
    '-o', 'ClearAllForwardings=yes', '-o', 'ForwardAgent=no', '-o', 'ForwardX11=no',
    '-o', 'ControlPath=none', '-o', 'RemoteCommand=none', '-o', 'PermitLocalCommand=no',
    '-o', 'ConnectTimeout=8', '-o', 'ServerAliveInterval=15',
    '-o', 'ServerAliveCountMax=2',
]
BROWSE_LIMIT = 512


def ssh_client():
    system = Path('/usr/bin/ssh') if os.name != 'nt' else Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/OpenSSH/ssh.exe'
    return str(system) if system.is_file() else shutil.which('ssh')


def ssh_hosts(home):
    base = home / '.ssh'
    seen, hosts = set(), {}

    def read(path, depth):
        try:
            if depth > 8 or not path.is_file() or path.stat().st_size > 131072:
                return
            path = path.resolve()
            if path in seen or len(seen) >= 64:
                return
            seen.add(path)
            lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
        except OSError:
            return
        for line in lines:
            fields = re.match(r'^\s*(Host|Include)\s*(?:=\s*|\s+)(.+)$', line, re.I)
            if not fields:
                continue
            try:
                values = shlex.split(fields[2], comments=True)
            except ValueError:
                continue
            if fields[1].lower() == 'host':
                hosts.update((value, None) for value in values if HOST.fullmatch(value))
            else:
                for value in values:
                    pattern = Path(value.replace('~/', str(home) + '/', 1) if value.startswith('~/') else value)
                    for included in glob.iglob(str(base / pattern)):
                        read(Path(included), depth + 1)
                        if len(seen) >= 64:
                            break

    read(base / 'config', 0)
    return list(hosts)[:64]


def browse_command(path):
    if path in ('', '~'):
        directory = '"$HOME"'
    elif path.startswith('~/'):
        directory = '"$HOME"/' + shlex.quote(path[2:])
    elif path.startswith('/'):
        directory = shlex.quote(path)
    else:
        raise ValueError('Use an absolute path or a path beginning with ~/.')
    script = f'''CDPATH=; cd -P {directory} >/dev/null || exit 2
printf 'umeko-ssh-workspace\\0%s\\0' "$PWD"
count=0
for entry in ./.[!.]* ./..?* ./*; do
    [ -d "$entry" ] || continue
    printf '%s\\0' "${{entry#./}}"
    count=$((count + 1))
    [ "$count" -le {BROWSE_LIMIT} ] || break
done
exit 0'''
    return 'sh -c ' + shlex.quote(script)


class SessionWorkspace(QObject):
    browseFinished = Signal('QVariantMap')
    busyChanged = Signal()

    def __init__(self, controller):
        super().__init__(controller)
        self.controller = controller
        self.remote_root = (controller.store.directory / 'ssh-workspaces').resolve()
        self._process = None
        self._verified = None
        self._stderr = b''
        self._timer = QTimer(self, singleShot=True, interval=15000)
        self._timer.timeout.connect(self._timeout)

    def remote(self, workspace):
        if not workspace or not workspace.startswith(str(self.remote_root) + os.sep):
            return None
        project = next((p for p in self.controller.store.data['projects'] if p['path'] == workspace), {})
        return project.get('ssh', {})

    def runtime(self, workspace):
        destination = self.remote(workspace)
        if destination is None:
            return None
        if not destination or not HOST.fullmatch(destination.get('host', '')) or not destination.get('path', '').startswith('/'):
            raise RuntimeError(self._text('找不到远程会话的 SSH 配置。', 'The SSH configuration for this conversation is missing.'))
        executable = ssh_client()
        if not executable:
            raise RuntimeError(self._text('找不到本机 OpenSSH 客户端。', 'OpenSSH client is unavailable on this computer.'))
        return {**destination, 'executable': executable, 'args': [*SSH_OPTIONS, '--', destination['host']]}

    def _text(self, zh, en):
        return en if self.controller.language == 'en' else zh

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._process is not None

    @Slot(result='QVariantMap')
    def choices(self):
        data = self.controller.store.data
        projects = [p for p in data['projects'] if not p.get('archived')]
        active = next((p for p in projects if p['id'] == data['activeProject']), {})
        folders = [{'name': p['name'], 'path': p['path']} for p in projects if self.remote(p['path']) is None]
        hosts = list(dict.fromkeys([active.get('ssh', {}).get('host', ''), *ssh_hosts(Path.home()),
                                    *(p['ssh']['host'] for p in projects if p.get('ssh'))]))
        return {'folders': folders, 'hosts': [host for host in hosts if host], 'active': active,
                'homeUrl': QUrl.fromLocalFile(str(Path.home())).toString()}

    @Slot(str, result=str)
    def localPath(self, url):
        path = QUrl(url).toLocalFile()
        return path if path and Path(path).is_dir() else ''

    @Slot(str, result=str)
    def folderUrl(self, path):
        return QUrl.fromLocalFile(path).toString()

    @Slot(str, result=bool)
    def startLocal(self, path):
        try:
            if not path or not Path(path).is_dir() or self.remote(str(Path(path).resolve())) is not None:
                return False
            self.controller._start_workspace_session(path)
            return True
        except OSError:
            return False

    @Slot(str, str, result=bool)
    def startRemote(self, host, path):
        if self._verified != (host, path):
            return False
        workspace = self.remote_root / hashlib.sha256(f'{host}\0{path}'.encode()).hexdigest()[:24]
        try:
            workspace.mkdir(parents=True, exist_ok=True)
            self.controller._start_workspace_session(str(workspace), {'host': host, 'path': path})
        except OSError:
            return False
        return True

    @Slot(str, str)
    def browse(self, host, path):
        self.cancel()
        if not HOST.fullmatch(host):
            return self._fail('请输入 SSH 主机别名或 user@host。', 'Enter an SSH host alias or user@host.')
        if '\x00' in path or (path not in ('', '~') and not path.startswith(('/', '~/'))):
            return self._fail('请输入绝对路径或以 ~/ 开头的路径。', 'Enter an absolute path or a path beginning with ~/.')
        executable = ssh_client()
        if not executable:
            return self._fail('找不到本机 OpenSSH 客户端。', 'OpenSSH client is unavailable on this computer.')
        process = self._process = QProcess(self)
        self._stderr = b''
        process.readyReadStandardOutput.connect(lambda: self._limit_stdout(process))
        process.readyReadStandardError.connect(lambda: self._read_stderr(process))
        process.finished.connect(lambda code, status: self._finish(process, host, code, status))
        process.errorOccurred.connect(lambda error: self._start_error(process, error))
        self.busyChanged.emit()
        self._timer.start()
        process.start(executable, [*SSH_OPTIONS, '-n', '--', host, browse_command(path)])

    @Slot()
    def cancel(self):
        self._verified = None
        if process := self._process:
            self._release(process)
            process.kill()

    def _release(self, process):
        self._timer.stop()
        self._process = None
        process.deleteLater()
        self.busyChanged.emit()

    def _timeout(self):
        self.cancel()
        self._fail('SSH 连接超时，请检查主机和网络。', 'SSH connection timed out. Check the host and network.')

    def _start_error(self, process, error):
        if process is self._process and error == QProcess.ProcessError.FailedToStart:
            self._release(process)
            self._fail('无法启动 OpenSSH。', 'Could not start OpenSSH.')

    def _limit_stdout(self, process):
        if process is self._process and process.bytesAvailable() > 1024 * 1024:
            self.cancel()
            self._fail('远程主机返回的目录信息过长。', 'The SSH host returned too much directory data.')

    def _read_stderr(self, process):
        if process is self._process:
            self._stderr = (self._stderr + bytes(process.readAllStandardError()))[-800:]

    def _fail(self, zh, en, detail=''):
        self.browseFinished.emit({'error': self._text(zh, en), 'detail': detail})

    def _finish(self, process, host, code, status):
        if process is not self._process:
            return
        output = bytes(process.readAllStandardOutput())
        self._read_stderr(process)
        detail = self._stderr.decode('utf-8', 'replace').strip()
        self._release(process)
        if status != QProcess.ExitStatus.NormalExit or code:
            return self._fail('无法打开远程目录。', 'Could not open the remote folder.', detail)
        _, marker, payload = output.partition(b'umeko-ssh-workspace\0')
        fields = payload.decode('utf-8', 'replace').split('\0')
        path, names = fields[0], fields[1:-1]
        if not marker or not path.startswith('/'):
            return self._fail('SSH 主机没有返回有效目录。', 'The SSH host did not return a valid folder.')
        self._verified = (host, path)
        entries = [{'name': name, 'path': posixpath.join(path, name)} for name in sorted(names[:BROWSE_LIMIT], key=str.casefold)
                   if name and '/' not in name and name not in ('.', '..')]
        self.browseFinished.emit({'host': host, 'path': path, 'parent': posixpath.dirname(path),
                                  'entries': entries, 'limited': len(names) > BROWSE_LIMIT})
