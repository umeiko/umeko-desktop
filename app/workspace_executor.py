"""Single workspace execution layer shared by all desktop plugins.

Local workspaces execute directly on this machine; remote workspaces forward
through the desktop RemoteServiceClient (Codex exec-server over SSH).
"""
from __future__ import annotations

import base64
import hashlib
import os
import posixpath
import ntpath
import shutil
import subprocess
from pathlib import Path

from .pi_runtime import CREATE_NO_WINDOW

MAX_PREVIEW_BYTES = 10 * 1024 * 1024


def _remote_join(base: str, relative: str, platform: str) -> str:
    rel = str(relative or '').strip()
    if not rel or rel == '.':
        return base
    if platform == 'windows':
        if ntpath.isabs(rel):
            return ntpath.normpath(rel)
        return ntpath.normpath(ntpath.join(base, rel.replace('/', '\\')))
    if posixpath.isabs(rel):
        return posixpath.normpath(rel)
    return posixpath.normpath(posixpath.join(base, rel.replace('\\', '/')))


def _remote_within(root: str, target: str, platform: str) -> bool:
    if platform == 'windows':
        r = ntpath.normcase(ntpath.normpath(root)).rstrip('\\')
        t = ntpath.normcase(ntpath.normpath(target)).rstrip('\\')
        return t == r or t.startswith(r + '\\')
    r = posixpath.normpath(root).rstrip('/') or '/'
    t = posixpath.normpath(target).rstrip('/') or '/'
    if r == '/':
        return t.startswith('/')
    return t == r or t.startswith(r + '/')


class WorkspaceExecutor:
    def __init__(self, controller):
        self._controller = controller

    def _remote_info(self, session: dict | None) -> dict | None:
        if not isinstance(session, dict):
            return None
        remote = session.get('remoteWorkspace')
        if isinstance(remote, dict) and remote.get('environment') and remote.get('remotePath'):
            return remote
        workspace = session.get('workspace', '')
        if workspace:
            lookup = getattr(self._controller, '_remote_project_for_workspace', None)
            if callable(lookup):
                return lookup(workspace)
        return None

    def _local_root(self, session: dict) -> Path:
        raw = str((session or {}).get('workspace') or '')
        if not raw:
            raise ValueError('A workspace directory is required')
        root = Path(raw).resolve()
        if not root.is_dir():
            raise ValueError('Workspace directory does not exist')
        return root

    def _local_resolve(self, root: Path, relative: str = '.') -> Path:
        target = (root / str(relative or '.')).resolve()
        if not target.is_relative_to(root):
            raise ValueError('Path is outside the current workspace')
        return target

    def _remote_resolve(self, remote: dict, relative: str = '.', *, allow_outside: bool = False) -> str:
        platform = remote.get('platform', 'linux')
        root = remote['remotePath']
        target = _remote_join(root, relative, platform)
        if not allow_outside and not _remote_within(root, target, platform):
            raise ValueError('Path is outside the remote workspace')
        return target

    def _service(self):
        return self._controller._remote_service

    def execute(self, session: dict, operation: str, args: dict | None = None) -> dict:
        args = dict(args or {})
        remote = self._remote_info(session)
        if remote:
            return self._execute_remote(remote, operation, args)
        return self._execute_local(session, operation, args)

    def _execute_remote(self, remote: dict, operation: str, args: dict) -> dict:
        env_name = remote['environment']
        platform = remote.get('platform', 'linux')
        root = remote['remotePath']
        timeout = max(5.0, min(float(args.get('timeoutMs', 30000)) / 1000.0 + 15.0, 240.0))

        if operation == 'workspace.sshTarget':
            res = self._service().call('workspaceOp', {'name': env_name, 'op': 'sshTarget'}, timeout=20.0)
            if res.get('ok'):
                res['remotePath'] = root
            return res

        if operation == 'workspace.home':
            return self._service().call('workspaceOp', {'name': env_name, 'op': 'home'}, timeout=30.0)

        if operation == 'workspace.exec':
            cwd = self._remote_resolve(remote, args.get('cwd', '.'), allow_outside=bool(args.get('allowOutside')))
            payload = {
                'name': env_name,
                'op': 'exec',
                'cwd': cwd,
                'env': args.get('env') if isinstance(args.get('env'), dict) else {},
                'timeoutMs': int(args.get('timeoutMs', 30000)),
                'maxOutputBytes': int(args.get('maxOutputBytes', 1024 * 1024)),
            }
            if isinstance(args.get('argv'), list):
                payload['argv'] = [str(item) for item in args['argv']]
            elif isinstance(args.get('command'), str):
                payload['command'] = args['command']
            else:
                return {'ok': False, 'error': 'argv or command is required'}
            return self._service().call('workspaceOp', payload, timeout=timeout)

        if operation == 'workspace.readDir':
            target = self._remote_resolve(remote, args.get('path', '.'), allow_outside=bool(args.get('allowOutside')))
            return self._service().call('workspaceOp', {
                'name': env_name, 'op': 'readDir', 'cwd': root, 'path': target,
                'withMetadata': bool(args.get('withMetadata', False)),
            }, timeout=30.0)

        if operation == 'workspace.stat':
            target = self._remote_resolve(remote, args.get('path', '.'), allow_outside=bool(args.get('allowOutside')))
            return self._service().call('workspaceOp', {
                'name': env_name, 'op': 'stat', 'cwd': root, 'path': target,
                'followSymlinks': args.get('followSymlinks', True) is not False,
            }, timeout=30.0)

        if operation == 'workspace.readFile':
            target = self._remote_resolve(remote, args.get('path', ''), allow_outside=bool(args.get('allowOutside')))
            max_bytes = max(1, min(int(args.get('maxBytes', 512 * 1024)), 2 * 1024 * 1024))
            return self._service().call('workspaceOp', {
                'name': env_name, 'op': 'readFile', 'cwd': root, 'path': target, 'maxBytes': max_bytes,
            }, timeout=60.0)

        if operation == 'workspace.writeFile':
            target = self._remote_resolve(remote, args.get('path', ''), allow_outside=bool(args.get('allowOutside')))
            payload = {'name': env_name, 'op': 'writeFile', 'cwd': root, 'path': target}
            if isinstance(args.get('dataBase64'), str):
                payload['dataBase64'] = args['dataBase64']
            else:
                payload['content'] = str(args.get('content', ''))
            return self._service().call('workspaceOp', payload, timeout=60.0)

        if operation == 'workspace.mkdir':
            target = self._remote_resolve(remote, args.get('path', ''), allow_outside=bool(args.get('allowOutside')))
            return self._service().call('workspaceOp', {'name': env_name, 'op': 'mkdir', 'cwd': root, 'path': target}, timeout=30.0)

        if operation == 'workspace.remove':
            target = self._remote_resolve(remote, args.get('path', ''), allow_outside=bool(args.get('allowOutside')))
            if target == root:
                return {'ok': False, 'error': 'Cannot remove the workspace root'}
            return self._service().call('workspaceOp', {
                'name': env_name, 'op': 'remove', 'cwd': root, 'path': target,
                'recursive': args.get('recursive', True) is not False,
                'force': args.get('force', True) is not False,
            }, timeout=60.0)

        if operation == 'workspace.rename':
            source = self._remote_resolve(remote, args.get('path', ''))
            dest = self._remote_resolve(remote, args.get('destination', ''))
            if source == root or dest == root:
                return {'ok': False, 'error': 'Cannot rename the workspace root'}
            return self._service().call('workspaceOp', {
                'name': env_name, 'op': 'rename', 'cwd': root, 'path': source, 'destination': dest,
            }, timeout=30.0)

        if operation == 'workspace.previewFile':
            target = self._remote_resolve(remote, args.get('path', ''))
            max_bytes = max(1, min(int(args.get('maxBytes', MAX_PREVIEW_BYTES)), MAX_PREVIEW_BYTES))
            res = self._service().call('workspaceOp', {
                'name': env_name, 'op': 'readFile', 'cwd': root, 'path': target, 'maxBytes': max_bytes,
            }, timeout=60.0)
            if not res.get('ok'):
                return res
            raw = base64.b64decode(res.get('dataBase64', ''))
            name = (ntpath.basename(target) if platform == 'windows' else posixpath.basename(target)) or 'preview.txt'
            safe_name = ''.join(ch if ch not in '<>:"/\\|?*' else '_' for ch in name)[:120] or 'preview.txt'
            digest = hashlib.sha256(f"{env_name}:{target}".encode('utf-8')).hexdigest()[:16]
            cache_dir = self._controller.store.directory / 'cache' / 'remote-previews' / digest
            cache_dir.mkdir(parents=True, exist_ok=True)
            local_file = cache_dir / safe_name
            local_file.write_bytes(raw)
            return {'ok': True, 'localPath': str(local_file), 'name': safe_name, 'size': res.get('size', len(raw)), 'truncated': bool(res.get('truncated'))}

        return {'ok': False, 'error': 'Unknown workspace operation: ' + operation}

    def _execute_local(self, session: dict, operation: str, args: dict) -> dict:
        root = self._local_root(session)
        if operation == 'workspace.sshTarget':
            return {'ok': False, 'error': 'Current workspace is local'}
        if operation == 'workspace.home':
            return {'ok': True, 'home': str(Path.home()), 'cwd': str(root), 'platform': 'windows' if os.name == 'nt' else 'linux'}
        if operation == 'workspace.exec':
            cwd = self._local_resolve(root, args.get('cwd', '.'))
            env = {k: v for k, v in os.environ.items() if not k.upper().endswith(('API_KEY', 'ACCESS_TOKEN', 'SECRET_KEY', 'PASSWORD', '_AK', '_SK'))}
            env.update(GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0', PAGER='cat', GIT_PAGER='cat')
            if isinstance(args.get('env'), dict):
                for k, v in args['env'].items():
                    if isinstance(k, str) and isinstance(v, str):
                        env[k] = v
            timeout_s = max(1.0, min(float(args.get('timeoutMs', 30000)) / 1000.0, 240.0))
            max_bytes = max(1024, min(int(args.get('maxOutputBytes', 1024 * 1024)), 4 * 1024 * 1024))
            argv = args.get('argv')
            if isinstance(argv, list) and argv:
                cmd = [str(item) for item in argv]
            elif isinstance(args.get('command'), str) and args['command'].strip():
                cmd = ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', args['command']] if os.name == 'nt' else ['/bin/sh', '-c', args['command']]
            else:
                return {'ok': False, 'error': 'argv or command is required'}
            try:
                proc = subprocess.run(cmd, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout_s, creationflags=CREATE_NO_WINDOW)
            except subprocess.TimeoutExpired:
                return {'ok': True, 'stdout': '', 'stderr': '', 'exitCode': None, 'timedOut': True, 'truncated': False}
            except OSError as error:
                return {'ok': False, 'error': str(error)}
            out = proc.stdout[:max_bytes]
            err = proc.stderr[:max_bytes]
            return {
                'ok': True,
                'stdout': out.decode('utf-8', 'replace'),
                'stderr': err.decode('utf-8', 'replace'),
                'exitCode': proc.returncode,
                'timedOut': False,
                'truncated': len(proc.stdout) > max_bytes or len(proc.stderr) > max_bytes,
            }
        if operation == 'workspace.readDir':
            target = self._local_resolve(root, args.get('path', '.'))
            entries = []
            for entry in os.scandir(target):
                row = {'name': entry.name, 'path': str(Path(entry.path)), 'isDirectory': entry.is_dir(follow_symlinks=False), 'isFile': entry.is_file(follow_symlinks=False)}
                if args.get('withMetadata'):
                    try:
                        st = entry.stat(follow_symlinks=False)
                        row.update(size=st.st_size, modifiedAtMs=int(st.st_mtime * 1000), isSymlink=entry.is_symlink())
                    except OSError:
                        pass
                entries.append(row)
            return {'ok': True, 'path': str(target), 'entries': entries}
        if operation == 'workspace.stat':
            target = self._local_resolve(root, args.get('path', '.'))
            if not target.exists():
                return {'ok': True, 'exists': False, 'path': str(target)}
            st = target.stat() if args.get('followSymlinks', True) is not False else target.lstat()
            return {'ok': True, 'exists': True, 'path': str(target), 'isDirectory': target.is_dir(), 'isFile': target.is_file(), 'isSymlink': target.is_symlink(), 'size': st.st_size, 'modifiedAtMs': int(st.st_mtime * 1000)}
        if operation == 'workspace.readFile':
            target = self._local_resolve(root, args.get('path', ''))
            max_bytes = max(1, min(int(args.get('maxBytes', 512 * 1024)), 2 * 1024 * 1024))
            size = target.stat().st_size
            with target.open('rb') as handle:
                raw = handle.read(max_bytes)
            return {'ok': True, 'path': str(target), 'dataBase64': base64.b64encode(raw).decode('ascii'), 'size': size, 'truncated': size > len(raw)}
        if operation == 'workspace.writeFile':
            target = self._local_resolve(root, args.get('path', ''))
            target.parent.mkdir(parents=True, exist_ok=True)
            raw = base64.b64decode(args['dataBase64']) if isinstance(args.get('dataBase64'), str) else str(args.get('content', '')).encode('utf-8')
            target.write_bytes(raw)
            return {'ok': True, 'path': str(target)}
        if operation == 'workspace.mkdir':
            target = self._local_resolve(root, args.get('path', ''))
            target.mkdir(parents=True, exist_ok=True)
            return {'ok': True, 'path': str(target)}
        if operation == 'workspace.remove':
            target = self._local_resolve(root, args.get('path', ''))
            if target == root:
                return {'ok': False, 'error': 'Cannot remove the workspace root'}
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            elif target.exists() or target.is_symlink():
                target.unlink()
            return {'ok': True, 'path': str(target)}
        if operation == 'workspace.rename':
            source = self._local_resolve(root, args.get('path', ''))
            dest = self._local_resolve(root, args.get('destination', ''))
            source.rename(dest)
            return {'ok': True, 'path': str(source), 'destination': str(dest)}
        if operation == 'workspace.previewFile':
            target = self._local_resolve(root, args.get('path', ''))
            return {'ok': True, 'localPath': str(target), 'name': target.name, 'size': target.stat().st_size, 'truncated': False}
        return {'ok': False, 'error': 'Unknown workspace operation: ' + operation}
