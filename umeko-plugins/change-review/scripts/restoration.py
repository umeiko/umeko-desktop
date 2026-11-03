from pathlib import Path, PurePosixPath
import hashlib
import os
import stat
import tempfile
import time

from .snapshots import MAX_FILE, SNAPSHOT_SECONDS, SnapshotError


def same(left, right):
    if left is None or right is None:
        return left is right
    if left.get('omitted') or right.get('omitted'):
        return False
    return left.get('blob') == right.get('blob') and left.get('mode') == right.get('mode')


def parts(path):
    value = PurePosixPath(path)
    if not path or value.is_absolute() or any(part in ('', '.', '..', '.git') for part in value.parts):
        raise SnapshotError('检查点包含无效路径')
    return value.parts


def target(snapshot, path):
    relative = parts(path)
    value = snapshot.workspace.joinpath(*relative)
    try:
        if not value.resolve().is_relative_to(snapshot.workspace):
            raise SnapshotError('恢复路径超出工作目录')
    except FileNotFoundError:
        pass
    return value


def ensure_parent(snapshot, path):
    value = target(snapshot, path)
    current = value.parent
    missing = []
    while current != snapshot.workspace:
        if current.exists():
            break
        missing.append(current)
        current = current.parent
    if current != snapshot.workspace and (current.is_symlink() or not current.is_dir()):
        raise SnapshotError('恢复路径包含链接或非目录')
    for folder in reversed(missing):
        folder.mkdir()
        if folder.is_symlink() or not folder.is_dir():
            raise SnapshotError('无法建立安全的恢复目录')
    return value


def read_record(snapshot, path):
    value = target(snapshot, path)
    try:
        info = value.lstat()
        if not stat.S_ISREG(info.st_mode) or value.is_symlink():
            raise SnapshotError('恢复目标不是普通文件')
        record = {'size': info.st_size, 'stamp': [info.st_mtime_ns, info.st_ctime_ns],
                  'mode': '100755' if info.st_mode & 0o111 else '100644'}
        if info.st_size > MAX_FILE:
            record['omitted'] = True
            return record
        descriptor = os.open(value, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise SnapshotError('恢复目标不是普通文件')
            content = stream.read(MAX_FILE + 1)
            after = os.fstat(stream.fileno())
        if len(content) > MAX_FILE or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            record['omitted'] = True
            return record
        digest = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
        record.update(blob=digest, binary=b'\0' in content)
        return record
    except FileNotFoundError:
        return None


def restore_plan(snapshot, known_states=None, current_snapshot=None):
    if not snapshot.base or not snapshot.end or not hasattr(snapshot, 'entries'):
        raise SnapshotError('检查点尚未完成，不能恢复')
    current_snapshot = current_snapshot or snapshot
    target_state = snapshot.end
    current = snapshot.capture()
    known_states = [current_snapshot.end['files']] if known_states is None else known_states
    rows = []
    paths = sorted(target_state['files'].keys() | current['files'].keys())
    for path in paths:
        parts(path)
        left = target_state['files'].get(path)
        now = current['files'].get(path)
        omitted = any((item or {}).get('omitted') for item in (left, now))
        known_later = not same(now, left) and any(same(now, files.get(path)) for files in known_states)
        if same(now, left):
            action = 'none'
        elif omitted:
            action = 'unavailable'
        elif not known_later:
            action = 'conflict'
        elif left is None:
            action = 'delete'
        elif now is None:
            action = 'create'
        else:
            action = 'restore'
        rows.append({'path': path, 'status': 'A' if left is None else 'D' if now is None else 'M',
                     'binary': bool((left or {}).get('binary') or (now or {}).get('binary')),
                     'omitted': omitted, 'added': -1, 'removed': -1,
                     'action': action, 'knownLater': known_later, 'diff': '', '_target': left, '_now': now})
    conflicts = sum(row['action'] in ('conflict', 'unavailable') for row in rows)
    changes = sum(row['action'] in ('restore', 'create', 'delete') for row in rows)
    overwrites = sum(row['knownLater'] and row['action'] in ('restore', 'create', 'delete') for row in rows)
    return {'entries': rows, 'conflicts': conflicts, 'changes': changes, 'overwrites': overwrites,
            'partial': bool(snapshot.limited or current['limited']), '_current': current}


def public_plan(plan):
    return {key: value for key, value in plan.items() if not key.startswith('_')} | {
        'entries': [{key: value for key, value in row.items() if not key.startswith('_')} for row in plan['entries']]}


def restore_diff(snapshot, path, plan):
    row = next((item for item in plan['entries'] if item['path'] == path), None)
    if not row:
        raise SnapshotError('该文件不在恢复预览中')
    left = snapshot.end['files'].get(path)
    current = plan['_current']['files'].get(path)
    if (left or {}).get('omitted') or (current or {}).get('omitted'):
        return {'text': '文件超过采集限制或在采集时发生变化，仅显示状态。', 'truncated': True}
    if (left or {}).get('binary') or (current or {}).get('binary'):
        return {'text': '二进制文件，仅显示变更状态。', 'truncated': False}
    snapshot.deadline = time.monotonic() + SNAPSHOT_SECONDS
    raw = snapshot.run(['diff-tree', '-p', '--no-commit-id', '-r', '--no-renames', '--no-ext-diff', '--no-textconv',
        '--unified=3', snapshot.end['tree'], plan['_current']['tree'], '--', ':(literal)' + path], private=True, limit=12 * MAX_FILE)
    text = raw[:48000].decode('utf-8', 'replace')
    lines = text.splitlines()
    truncated = len(raw) > 48000 or len(lines) > 1000 or any(len(line) > 2000 for line in lines)
    return {'text': '\n'.join(line[:2000] for line in lines[:1000]), 'truncated': truncated}


def execute_restore(snapshot, plan):
    if plan['conflicts']:
        raise SnapshotError('存在冲突或未覆盖文件，已阻止恢复')
    completed = []
    rows = [row for row in plan['entries'] if row['action'] in ('restore', 'create', 'delete')]
    for index, row in enumerate(rows):
        path, action = row['path'], row['action']
        try:
            if not same(read_record(snapshot, path), row['_now']):
                raise SnapshotError('文件在恢复前再次变化')
            left = row['_target']
            value = ensure_parent(snapshot, path)
            if action == 'delete':
                if value.is_symlink() or not value.is_file():
                    raise SnapshotError('删除目标不是普通文件')
                value.unlink()
            else:
                if not left or left.get('omitted') or not left.get('blob'):
                    raise SnapshotError('基线内容不可用')
                snapshot.deadline = time.monotonic() + SNAPSHOT_SECONDS
                content = snapshot.run(['cat-file', 'blob', left['blob']], private=True, limit=MAX_FILE)
                descriptor, temporary = tempfile.mkstemp(prefix='.umeko-restore-', dir=value.parent)
                try:
                    with os.fdopen(descriptor, 'wb') as stream:
                        stream.write(content)
                        stream.flush()
                        os.fsync(stream.fileno())
                    if left.get('mode') == '100755':
                        os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
                    if value.exists() and (value.is_symlink() or not value.is_file()):
                        raise SnapshotError('替换目标不是普通文件')
                    os.replace(temporary, value)
                finally:
                    try:
                        os.unlink(temporary)
                    except FileNotFoundError:
                        pass
            if not same(read_record(snapshot, path), left):
                raise SnapshotError('恢复后校验失败')
            completed.append({'path': path, 'action': action})
        except (OSError, SnapshotError, ValueError) as error:
            return {'ok': False, 'completed': completed,
                    'failed': {'path': path, 'action': action, 'error': str(error)[:500]},
                    'pending': [{'path': item['path'], 'action': item['action']} for item in rows[index + 1:]]}
    return {'ok': True, 'completed': completed, 'failed': None, 'pending': []}
