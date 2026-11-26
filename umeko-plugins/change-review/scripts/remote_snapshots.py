"""Remote worktree snapshots executed on the remote machine via WorkspaceExecutor.

Uses an isolated private bare git repository under the remote user's cache/temp
folder so the remote workspace's own Git index and history are never touched.
"""
from __future__ import annotations

import json
import ntpath
import posixpath
import tempfile
import threading
import time
import uuid
from pathlib import Path

from .snapshots import SnapshotError, remove_snapshot

MAX_OUTPUT = 1024 * 1024
SNAPSHOT_TIMEOUT_MS = 30000


class RemoteSnapshot:
    def __init__(self, context, session, state_dir, cancelled=None, prefix='review-'):
        self.context = context
        self.session = dict(session)
        remote = self.session.get('remoteWorkspace') or {}
        if not remote.get('environment') or not remote.get('remotePath'):
            raise SnapshotError('缺少远程工作目录信息')
        self.workspace = Path(self.session['workspace']).resolve()
        self.remote_path = remote['remotePath']
        self.platform = remote.get('platform', 'linux')
        self.devnull = 'NUL' if self.platform == 'windows' else '/dev/null'
        self.folder = Path(tempfile.mkdtemp(prefix=prefix, dir=state_dir))
        self.cancelled = cancelled or threading.Event()
        self.base = None
        self.end = None
        self.entries = []
        self.limited = False
        self.started = 0
        self.ended = 0
        self.metadata = {}
        self.closed = False
        home_info = self.context.workspace_home(session=self.session)
        base_temp = home_info.get('tempDir') or (
            ntpath.join(home_info.get('home', ''), 'AppData', 'Local', 'Temp')
            if self.platform == 'windows'
            else posixpath.join(home_info.get('home', '/tmp'), '.cache')
        )
        run_id = uuid.uuid4().hex[:16]
        join = ntpath.join if self.platform == 'windows' else posixpath.join
        self.remote_root = join(base_temp, 'umeko-change-review', f'{prefix}{run_id}')
        self.repo = join(self.remote_root, 'objects.git')
        try:
            self.context.workspace_mkdir(self.remote_root, allow_outside=True, session=self.session)
            self._git(['init', '--bare', '--template=', self.repo], private=False)
        except Exception as error:
            self.close(remove=True)
            raise SnapshotError('远端未能初始化变更审查快照：' + str(error)) from None

    def _git(self, args, *, private=True, index_file=None, allow=(0,), limit=MAX_OUTPUT):
        if self.cancelled.is_set():
            raise SnapshotError('审查已取消')
        env = {
            'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_CONFIG_GLOBAL': self.devnull,
            'GIT_TERMINAL_PROMPT': '0',
            'GIT_OPTIONAL_LOCKS': '0',
        }
        if index_file:
            env['GIT_INDEX_FILE'] = index_file
        argv = ['git', '--no-pager', '-c', 'core.fsmonitor=false', '-c', 'core.quotepath=false',
                '-c', 'core.autocrlf=false', '-c', 'core.hooksPath=' + self.devnull]
        if private:
            argv += ['--git-dir=' + self.repo, '--work-tree=' + self.remote_path]
        argv += list(args)
        res = self.context.workspace_exec(
            argv, cwd='.', env=env, timeout_ms=SNAPSHOT_TIMEOUT_MS,
            max_output_bytes=limit, session=self.session,
        )
        if res.get('timedOut'):
            raise SnapshotError('远端快照超时，本轮审查不可用')
        if res.get('exitCode') not in allow:
            detail = (res.get('stderr') or res.get('stdout') or '').strip()[:300]
            raise SnapshotError('远端 Git 快照失败：' + (detail or f"exit {res.get('exitCode')}"))
        return res.get('stdout') or ''

    def capture(self):
        join = ntpath.join if self.platform == 'windows' else posixpath.join
        index_file = join(self.remote_root, f'index-{uuid.uuid4().hex[:8]}')
        try:
            probe = self._git(['rev-parse', '--is-inside-work-tree'], private=False, allow=(0, 128))
            repository = probe.strip() == 'true'
            # Stage a private snapshot index of non-ignored workspace files without touching workspace .git.
            self._git(['read-tree', '--empty'], private=True, index_file=index_file)
            self._git(['add', '-A', '--', '.'], private=True, index_file=index_file)
            tree = self._git(['write-tree'], private=True, index_file=index_file).strip()
            listing = self._git(['ls-tree', '-r', '-z', tree], private=True)
            files = {}
            for row in listing.split('\0'):
                if '\t' not in row:
                    continue
                meta_part, rel_path = row.split('\t', 1)
                parts = meta_part.split()
                if len(parts) >= 3:
                    files[rel_path] = {'mode': parts[0], 'blob': parts[2], 'size': 0, 'stamp': [0, 0]}
            return {'files': files, 'tree': tree, 'limited': False, 'repository': repository, 'captured': time.time()}
        finally:
            try:
                self.context.workspace_remove(index_file, recursive=False, force=True, allow_outside=True, session=self.session)
            except Exception:
                pass

    def begin(self):
        self.base = self.capture()
        self._git(['update-ref', 'refs/review/base', self.base['tree']], private=True)

    def finish(self):
        if self.base is None:
            raise SnapshotError('未取得本轮开始前的基线，请开启后重新开始一轮任务')
        self.end = self.capture()
        status_out = self._git(
            ['diff-tree', '--no-commit-id', '--name-status', '-r', '-z', '--no-renames', self.base['tree'], self.end['tree']],
            private=True,
        )
        numstat_out = self._git(
            ['diff-tree', '--no-commit-id', '--numstat', '-r', '-z', '--no-renames', '--no-ext-diff', '--no-textconv', self.base['tree'], self.end['tree']],
            private=True,
        )
        counts = {}
        for line in numstat_out.split('\0'):
            parts = line.split('\t', 2)
            if len(parts) == 3:
                counts[parts[2]] = parts[:2]
        tokens = [t for t in status_out.split('\0') if t]
        rows = []
        i = 0
        while i + 1 < len(tokens):
            code = tokens[i][:1]
            rel_path = tokens[i + 1]
            i += 2
            stat_pair = counts.get(rel_path)
            binary = bool(stat_pair and (stat_pair[0] == '-' or stat_pair[1] == '-'))
            added = int(stat_pair[0]) if stat_pair and stat_pair[0].isdigit() else -1
            removed = int(stat_pair[1]) if stat_pair and stat_pair[1].isdigit() else -1
            rows.append({
                'path': rel_path,
                'status': code if code in ('A', 'M', 'D') else 'M',
                'binary': binary,
                'omitted': False,
                'added': added,
                'removed': removed,
            })
        rows.sort(key=lambda r: r['path'])
        self._git(['update-ref', 'refs/review/end', self.end['tree']], private=True)
        self.entries = rows
        self.limited = False
        self.started, self.ended = self.base['captured'], self.end['captured']
        return {
            'entries': rows,
            'limited': self.limited,
            'repository': self.base['repository'],
            'started': self.started,
            'ended': self.ended,
        }

    def diff(self, path):
        if not self.base or not self.end:
            raise SnapshotError('尚无已完成的快照')
        left = self.base['files'].get(path)
        right = self.end['files'].get(path)
        if not left and not right:
            raise SnapshotError('该文件不在本轮快照中')
        raw = self._git(
            ['diff-tree', '-p', '--no-commit-id', '-r', '--no-renames', '--no-ext-diff', '--no-textconv',
             '--unified=3', self.base['tree'], self.end['tree'], '--', ':(literal)' + path],
            private=True, limit=MAX_OUTPUT,
        )
        text = raw[:48000]
        lines = text.splitlines()
        truncated = len(raw) > 48000 or len(lines) > 1000 or any(len(x) > 2000 for x in lines)
        return {'text': '\n'.join(x[:2000] for x in lines[:1000]), 'truncated': truncated}

    def save(self, **metadata):
        data = {
            'version': 1, 'remote': True, 'remoteRoot': self.remote_root, 'remoteWorkspace': self.session.get('remoteWorkspace'),
            'workspace': str(self.workspace), 'base': self.base, 'end': self.end,
            'entries': getattr(self, 'entries', []), 'limited': getattr(self, 'limited', False),
            'started': getattr(self, 'started', self.base['captured'] if self.base else 0),
            'ended': getattr(self, 'ended', self.end['captured'] if self.end else 0), **metadata,
        }
        temporary = self.folder / 'checkpoint.tmp'
        temporary.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        temporary.replace(self.folder / 'checkpoint.json')
        self.metadata = metadata

    def close(self, remove=True):
        if self.closed:
            return
        self.closed = True
        if remove:
            try:
                self.context.workspace_remove(self.remote_root, recursive=True, force=True, allow_outside=True, session=self.session)
            except Exception:
                pass
            remove_snapshot(self.folder)
