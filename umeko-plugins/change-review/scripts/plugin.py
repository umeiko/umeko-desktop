from pathlib import Path
from collections import OrderedDict
import json
import uuid

from umeko_plugin_sdk import Plugin, PluginError
from .restoration import execute_restore, public_plan, restore_diff, restore_plan, same
from .snapshots import Snapshot, SnapshotError, remove_snapshot


class ChangeReview(Plugin):
    def __init__(self, context):
        super().__init__(context)
        self.active = {}
        self.latest = None
        self.history = {}
        self.loaded = OrderedDict()
        self.restore_plans = {}
        self.notice = ''
        try:
            self.current = json.loads((context.state_dir / 'current.json').read_text(encoding='utf-8')).get('versions', {})
        except (OSError, ValueError, AttributeError):
            self.current = {}
        for child in context.state_dir.glob('review-*'):
            if child.is_dir() and not child.is_symlink():
                remove_snapshot(child)
        for child in context.state_dir.glob('checkpoint-*'):
            if not child.is_dir() or child.is_symlink():
                continue
            try:
                data = json.loads((child / 'checkpoint.json').read_text(encoding='utf-8'))
                identifier = data['id']
                if not isinstance(identifier, str) or len(identifier) != 32 or identifier in self.history:
                    continue
                if data.get('state') == 'active':
                    data['state'] = 'interrupted'
                self.history[identifier] = self.summary(data, child)
            except (OSError, ValueError, KeyError, TypeError):
                continue

    def target(self):
        source = self.context.request_session or self.context.session
        return {**self.context.capture_session(), 'title': source.get('title', '')}

    def key(self):
        target = self.context.capture_session()
        return target['token'], str(Path(target['workspace']).resolve())

    def owns(self, item, key):
        target = self.target()
        return str(Path(item.get('workspace', '')).resolve()) == key[1] and (
            item.get('token') == key[0] or item.get('sessionId') and item.get('sessionId') == target['id'])

    @staticmethod
    def summary(data, folder):
        entries = data.get('entries', [])
        return {key: data.get(key) for key in ('id', 'token', 'sessionId', 'workspace', 'loopId', 'title', 'reason', 'kind', 'state', 'started', 'ended', 'limited')} | {
            'checkpointId': data['id'], 'folder': str(folder), 'entries': entries,
            'total': len(entries), 'added': sum(max(0, row.get('added', 0)) for row in entries),
            'removed': sum(max(0, row.get('removed', 0)) for row in entries),
            'pinned': bool(data.get('pinned')), 'error': data.get('error', ''),
            'active': data.get('state') == 'active', 'restorable': data.get('state') == 'complete' and bool(data.get('base') and data.get('end'))}

    def identity(self, key):
        return (self.target()['id'] or key[0]) + '|' + key[1]

    def ordered(self, key):
        return sorted([item for item in self.history.values() if self.owns(item, key) and item['kind'] != 'recovery'],
                      key=lambda item: (item.get('started') or item.get('ended') or 0, item['checkpointId']))

    def current_id(self, key):
        identifier = self.current.get(self.identity(key), '')
        item = self.history.get(identifier)
        if item and self.owns(item, key) and item['kind'] != 'recovery':
            return identifier
        rows = self.ordered(key)
        return rows[-1]['checkpointId'] if rows else ''

    def set_current(self, key, identifier):
        self.current[self.identity(key)] = identifier
        temporary = self.context.state_dir / 'current.tmp'
        temporary.write_text(json.dumps({'version': 1, 'versions': self.current}, ensure_ascii=False), encoding='utf-8')
        temporary.replace(self.context.state_dir / 'current.json')

    def future(self, key):
        rows = self.ordered(key)
        identifier = self.current_id(key)
        index = next((index for index, item in enumerate(rows) if item['checkpointId'] == identifier), -1)
        return rows[index + 1:] if index >= 0 else []

    def ensure_origin(self, key, source=None):
        existing = next((item for item in self.ordered(key) if item['kind'] == 'origin'), None)
        if existing:
            return existing['checkpointId']
        rows = self.ordered(key)
        if source is None and not rows:
            return ''
        try:
            snapshot = source['snapshot'] if source is not None else self.snapshot_for(rows[0]['checkpointId'], key)
            origin = self.new_item(key, '初始状态', 'origin')
            origin['loopId'], origin['reason'], origin['active'] = '', 'origin', False
            origin['snapshot'] = Snapshot(key[1], self.context.state_dir, self.context.cancelled, prefix='checkpoint-')
            origin['snapshot'].run(['fetch', str(snapshot.repo), 'refs/review/base:refs/review/base'], private=True)
            origin['snapshot'].base = snapshot.base
            origin['snapshot'].end = snapshot.base
            origin['snapshot'].entries = []
            origin['snapshot'].limited = getattr(snapshot, 'limited', False)
            origin['snapshot'].started = origin['snapshot'].ended = snapshot.base['captured']
            origin['snapshot'].run(['update-ref', 'refs/review/end', snapshot.base['tree']], private=True)
            self.save_item(origin, 'complete')
            origin['snapshot'].close(remove=False)
            return origin['checkpointId']
        except (SnapshotError, OSError, ValueError):
            return ''

    @staticmethod
    def different_files(left, right):
        return any(not same(left.get(path), right.get(path)) for path in left.keys() | right.keys())

    def diverged(self, key, after_files=None):
        identifier = self.current_id(key)
        if not identifier:
            return False
        snapshot = self.snapshot_for(identifier, key)
        files = after_files if after_files is not None else snapshot.capture()['files']
        return self.different_files(snapshot.end['files'], files)

    def delete_checkpoint(self, identifier):
        item = self.history.pop(identifier, None)
        if not item:
            return
        snapshot = self.loaded.pop(identifier, None)
        if snapshot:
            snapshot.close(remove=False)
        if self.latest and self.latest[1].get('checkpointId') == identifier:
            self.latest = None
        self.restore_plans.pop(identifier, None)
        remove_snapshot(item['folder'])
        for identity, current in list(self.current.items()):
            if current == identifier:
                self.current.pop(identity)
        temporary = self.context.state_dir / 'current.tmp'
        temporary.write_text(json.dumps({'version': 1, 'versions': self.current}, ensure_ascii=False), encoding='utf-8')
        temporary.replace(self.context.state_dir / 'current.json')

    def truncate_future(self, key, after_files=None):
        future = self.future(key)
        if not future or not self.diverged(key, after_files):
            return 0
        for item in future:
            self.delete_checkpoint(item['checkpointId'])
        self.notice = f'已放弃当前点之后的 {len(future)} 个检查点'
        return len(future)

    def save_item(self, item, state):
        item['state'] = state
        snapshot = item['snapshot']
        metadata = {key: item.get(key) for key in ('checkpointId', 'title', 'reason', 'kind', 'loopId', 'state')}
        metadata.update(id=item['checkpointId'], token=item['token'], sessionId=item['sessionId'],
                        workspace=item['workspace'], pinned=item.get('pinned', False), error=item.get('error', ''))
        metadata.pop('checkpointId', None)
        snapshot.save(**metadata)
        self.history[item['checkpointId']] = self.summary({
            **metadata, 'base': snapshot.base, 'end': snapshot.end, 'entries': getattr(snapshot, 'entries', []),
            'limited': getattr(snapshot, 'limited', False), 'started': getattr(snapshot, 'started', 0),
            'ended': getattr(snapshot, 'ended', 0)}, snapshot.folder)

    def dispose(self, item, interrupted=False):
        if not item or not item.get('snapshot'):
            return
        snapshot = item['snapshot']
        persistent = bool(item.get('checkpointId'))
        if persistent and interrupted and snapshot.base and not snapshot.end:
            try:
                self.save_item(item, 'interrupted')
            except (OSError, ValueError):
                pass
        snapshot.close(remove=not persistent)
        item['snapshot'] = None

    def clear_latest(self):
        if self.latest:
            self.dispose(self.latest[1])
            self.latest = None

    def item(self, key):
        return self.active.get(key) or (self.latest[1] if self.latest and self.latest[0] == key else None)

    def changed(self):
        self.context.publish('review.changed', {})

    def capture_error(self, item, error):
        item['error'] = str(error)[:500]
        item['entries'] = []
        if item.get('checkpointId') and item.get('snapshot'):
            if item['snapshot'].base:
                try:
                    self.save_item(item, 'error')
                except (OSError, ValueError):
                    pass
                self.dispose(item)
            else:
                item['snapshot'].close()
                item['snapshot'] = None
                self.history.pop(item['checkpointId'], None)
            return
        self.dispose(item)

    def persistent(self):
        return self.context.config.get('checkpoints') is True

    def new_item(self, key, title='', kind='agent'):
        target = self.target()
        return {'loopId': '', 'active': True, 'snapshot': None, 'entries': [], 'error': '', 'reason': '',
                'checkpointId': uuid.uuid4().hex if self.persistent() or kind in ('recovery', 'origin') else '',
                'token': key[0], 'sessionId': target['id'], 'workspace': key[1],
                'title': title or target['title'] or '代码检查点', 'kind': kind, 'pinned': False}

    def snapshot_for(self, identifier, key):
        item = self.history.get(identifier)
        if not item or not self.owns(item, key):
            raise PluginError('检查点不存在或不属于当前会话')
        if self.latest and self.latest[1].get('checkpointId') == identifier and self.latest[1].get('snapshot'):
            return self.latest[1]['snapshot']
        if identifier in self.loaded:
            return self.loaded[identifier]
        snapshot = Snapshot.load(key[1], item['folder'], self.context.cancelled)
        self.loaded[identifier] = snapshot
        while len(self.loaded) > 4:
            _, old = self.loaded.popitem(last=False) if hasattr(self.loaded, 'popitem') else (None, None)
            if old:
                old.close(remove=False)
        return snapshot

    def plan_for(self, identifier, key):
        snapshot = self.snapshot_for(identifier, key)
        current = self.snapshot_for(self.current_id(key) or identifier, key)
        states = []
        for item in self.history.values():
            if item['state'] != 'complete' or str(Path(item['workspace']).resolve()) != key[1]:
                continue
            other = Snapshot.load(key[1], item['folder'], self.context.cancelled)
            if other.end:
                states.append(other.end['files'])
        return restore_plan(snapshot, states, current)

    def selected(self, arguments, key):
        identifier = arguments.get('checkpointId', '')
        if identifier:
            item = self.history.get(identifier)
            if not item or not self.owns(item, key):
                raise PluginError('检查点不存在或不属于当前会话')
            return item
        return self.item(key)

    def handle(self, method, arguments):
        key = self.key()
        if method == 'begin':
            self.notice = ''
            self.truncate_future(key)
            self.clear_latest()
            previous = self.active.pop(key, None)
            self.dispose(previous, interrupted=True)
            if len(self.active) >= 8:
                return {'captured': False, 'error': '同时审查的会话过多，本轮未采集'}
            item = self.new_item(key)
            item['loopId'] = arguments.get('loopId', '')
            self.active[key] = item
            try:
                item['snapshot'] = Snapshot(key[1], self.context.state_dir, self.context.cancelled,
                                            prefix='checkpoint-' if item['checkpointId'] else 'review-')
                item['snapshot'].begin()
                if item['checkpointId']:
                    self.ensure_origin(key, item)
                    self.save_item(item, 'active')
            except (SnapshotError, OSError, ValueError, TimeoutError) as error:
                self.capture_error(item, error)
            self.changed()
            return {'captured': not bool(item['error']), 'error': item['error'], 'checkpointId': item['checkpointId']}

        if method == 'finish':
            item = self.active.get(key)
            if not item or item['loopId'] != arguments.get('loopId', ''):
                return {'reviewed': False}
            self.active.pop(key)
            self.clear_latest()
            item['active'] = False
            item['reason'] = arguments.get('reason', 'completed')
            item['sessionId'] = self.target()['id'] or item['sessionId']
            if arguments.get('title'):
                item['title'] = str(arguments['title']).strip()[:80] or item['title']
            if item['snapshot']:
                try:
                    item.update(item['snapshot'].finish())
                    if item['checkpointId'] and not item['entries']:
                        self.delete_checkpoint(item['checkpointId'])
                        item['checkpointId'] = ''
                        item['snapshot'] = None
                    elif item['checkpointId']:
                        self.truncate_future(key, item['snapshot'].end['files'])
                        self.save_item(item, 'complete')
                        self.set_current(key, item['checkpointId'])
                        self.retention()
                except (SnapshotError, OSError, ValueError, TimeoutError) as error:
                    self.capture_error(item, error)
            self.latest = (key, item)
            self.changed()
            if self.context.config.get('autoOpen', True):
                self.context.open_page()
            return {'reviewed': True, 'files': len(item['entries']), 'error': item['error'], 'checkpointId': item['checkpointId']}

        if method == 'timeline':
            return self.timeline(key, arguments)
        if method == 'restorePreview':
            identifier = arguments.get('checkpointId', '')
            snapshot = self.snapshot_for(identifier, key)
            if self.history[identifier]['state'] != 'complete':
                raise PluginError('只有完整检查点可以恢复')
            plan = self.plan_for(identifier, key)
            self.restore_plans[identifier] = plan
            return {**public_plan(plan), 'checkpointId': identifier, 'title': self.history[identifier]['title']}
        if method == 'restoreDiff':
            identifier = arguments.get('checkpointId', '')
            snapshot = self.snapshot_for(identifier, key)
            plan = self.restore_plans.get(identifier)
            if not plan:
                plan = self.plan_for(identifier, key)
                self.restore_plans[identifier] = plan
            return restore_diff(snapshot, arguments.get('path', ''), plan)
        if method == 'restore':
            return self.restore(key, arguments)
        if method in ('rename', 'pin', 'delete', 'cleanup'):
            return self.edit_history(key, method, arguments)

        item = self.selected(arguments, key)
        if arguments.get('loopId') and (not item or item['loopId'] != arguments['loopId']):
            raise PluginError('本轮记录已替换')
        if method == 'refresh':
            if item and item.get('snapshot') and not item['active'] and not item.get('checkpointId'):
                try:
                    item.update(item['snapshot'].finish())
                    item['error'] = ''
                except (SnapshotError, OSError, ValueError, TimeoutError) as error:
                    self.capture_error(item, error)
            return self.status(item, arguments)
        if method == 'status':
            return self.status(item, arguments)
        if method == 'tree':
            return self.tree(item, arguments)
        if method == 'diff':
            if not item or item['active'] or item.get('state') == 'error' or (item.get('error') and not item.get('entries')):
                raise PluginError('本轮差异尚不可用')
            try:
                snapshot = self.snapshot_for(arguments['checkpointId'], key) if arguments.get('checkpointId') else item.get('snapshot')
                if not snapshot:
                    raise PluginError('本轮差异尚不可用')
                return snapshot.diff(arguments.get('path', ''))
            except (SnapshotError, OSError) as error:
                raise PluginError(str(error)) from None
        path = arguments.get('path', '')
        if method in ('attach', 'reveal', 'explorer'):
            if not item or not any(row['path'] == path for row in item['entries']):
                raise PluginError('该文件不在本轮变更中')
            if method == 'attach':
                self.context.attach_file(path)
            elif method == 'reveal':
                self.context.reveal_file(path)
            else:
                self.context.reveal_in_explorer(path)
            return {'done': True}
        raise PluginError('未知审查操作')

    def timeline(self, key, args):
        self.ensure_origin(key)
        kind = args.get('kind', 'all')
        rows = [item for item in self.history.values() if self.owns(item, key) and item['kind'] != 'recovery' and (kind == 'all' or item['kind'] == kind)]
        for item in self.active.values():
            if item['checkpointId'] and self.owns(item, key) and kind in ('all', 'agent'):
                rows.append(self.summary({**item, 'state': 'active', 'base': item['snapshot'].base if item.get('snapshot') else None,
                    'end': None}, item['snapshot'].folder if item.get('snapshot') else Path('')))
        unique = {item['checkpointId']: item for item in rows}
        rows = sorted(unique.values(), key=lambda item: (item['kind'] == 'origin', -(item.get('ended') or item.get('started') or 0), item['checkpointId']))
        current = self.current_id(key)
        future = self.future(key)
        try:
            diverged = self.diverged(key) if future else False
        except (SnapshotError, OSError, ValueError):
            diverged = True
        offset = max(0, min(100000, int(args.get('offset', 0))))
        size = max(1, min(100, int(args.get('limit', 50))))
        page = [{**{k: v for k, v in item.items() if k not in ('entries', 'folder', 'token', 'sessionId', 'workspace')},
                 'current': item['checkpointId'] == current} for item in rows[offset:offset + size]]
        return {'entries': page, 'total': len(rows), 'offset': offset, 'hasMore': offset + len(page) < len(rows),
                'checkpoints': self.persistent(), 'currentId': current, 'futureCount': len(future),
                'diverged': diverged, 'notice': self.notice}

    def restore(self, key, arguments):
        identifier = arguments.get('checkpointId', '')
        if not isinstance(arguments.get('lockToken'), str) or len(arguments['lockToken']) != 32:
            raise PluginError('恢复前需要取得工作目录写锁')
        snapshot = self.snapshot_for(identifier, key)
        plan = self.restore_plans.get(identifier)
        if not plan:
            plan = self.plan_for(identifier, key)
        if plan['conflicts']:
            raise PluginError('存在冲突或未覆盖文件，已阻止恢复')
        if not plan['changes']:
            self.set_current(key, identifier)
            self.changed()
            return {'ok': True, 'completed': [], 'failed': None, 'pending': [], 'recoveryId': '', 'currentId': identifier}
        original = self.history[identifier]
        recovery = self.new_item(key, original['title'], 'recovery')
        recovery['loopId'] = original['loopId']
        recovery['reason'] = 'restore'
        recovery['active'] = False
        recovery['snapshot'] = Snapshot(key[1], self.context.state_dir, self.context.cancelled, prefix='checkpoint-')
        try:
            recovery['snapshot'].begin()
            self.save_item(recovery, 'active')
            try:
                result = execute_restore(snapshot, plan)
            except (SnapshotError, OSError, ValueError) as error:
                result = {'ok': False, 'completed': [], 'failed': {'path': '', 'action': '', 'error': str(error)[:500]}, 'pending': []}
            try:
                recovery['snapshot'].finish()
                recovery['error'] = '' if result['ok'] else '恢复未全部完成；此副本记录恢复前与当前实际状态'
                self.save_item(recovery, 'complete')
            except (SnapshotError, OSError, ValueError, TimeoutError) as error:
                result['recoveryError'] = str(error)[:500]
                self.save_item(recovery, 'error')
            result['recoveryId'] = recovery['checkpointId']
            self.set_current(key, identifier if result['ok'] and 'recoveryError' not in result else recovery['checkpointId'])
            result['currentId'] = self.current_id(key)
            self.clear_latest()
            recovery.update(entries=recovery['snapshot'].entries, limited=recovery['snapshot'].limited,
                            started=recovery['snapshot'].started, ended=recovery['snapshot'].ended)
            self.latest = (key, recovery)
            self.restore_plans.pop(identifier, None)
            self.changed()
            return result
        finally:
            if self.latest is None or self.latest[1] is not recovery:
                if recovery.get('snapshot') and recovery['checkpointId'] in self.history:
                    recovery['snapshot'].close(remove=False)

    def edit_history(self, key, method, args):
        if method == 'cleanup':
            self.retention(force=True)
            self.changed()
            return {'done': True}
        identifier = args.get('checkpointId', '')
        item = self.history.get(identifier)
        if not item or not self.owns(item, key) or item['state'] == 'active':
            raise PluginError('检查点不存在或仍在采集')
        if method == 'delete':
            current = self.current_id(key)
            self.delete_checkpoint(identifier)
            if current == identifier:
                self.set_current(key, self.current_id(key))
        else:
            snapshot = self.snapshot_for(identifier, key)
            metadata = dict(snapshot.metadata)
            if method == 'rename':
                title = str(args.get('title', '')).strip()[:80]
                if not title:
                    raise PluginError('检查点名称不能为空')
                metadata['title'] = title
            else:
                metadata['pinned'] = not item['pinned']
            snapshot.save(**metadata)
            self.history[identifier] = self.summary({**metadata, 'base': snapshot.base, 'end': snapshot.end,
                'entries': snapshot.entries, 'limited': snapshot.limited, 'started': snapshot.started,
                'ended': snapshot.ended}, snapshot.folder)
        self.changed()
        return {'done': True}

    def retention(self, force=False):
        limit = max(1, min(200, int(self.context.config.get('maxCheckpoints', 20))))
        capacity = max(16, min(4096, int(self.context.config.get('maxCheckpointMB', 512)))) * 1024 * 1024
        rows = sorted(self.history.values(), key=lambda item: item.get('ended') or item.get('started') or 0)
        protected = {item['checkpointId'] for item in self.active.values()} | set(self.current.values())
        if self.latest:
            protected.add(self.latest[1].get('checkpointId'))
        def folder_size(item):
            try:
                return sum(path.stat().st_size for path in Path(item['folder']).rglob('*') if path.is_file())
            except OSError:
                return 0
        while len(self.history) > limit or sum(folder_size(item) for item in self.history.values()) > capacity:
            candidates = [item for item in rows if item['checkpointId'] in self.history and not item['pinned'] and item['checkpointId'] not in protected]
            if not candidates:
                break
            item = candidates[0]
            self.delete_checkpoint(item['checkpointId'])
            rows = rows[1:]
            if not force and len(self.history) <= limit:
                continue

    @staticmethod
    def page(rows, offset):
        page = []
        size = 0
        for row in rows[offset:offset + 200]:
            weight = len(json.dumps(row, ensure_ascii=True))
            if page and size + weight > 256 * 1024:
                break
            page.append(row)
            size += weight
        return page

    def status(self, item, args):
        if not item:
            return {'entries': [], 'total': 0, 'active': False, 'empty': True,
                    'error': '', 'limited': False, 'reason': '', 'loopId': ''}
        offset = max(0, min(4000, int(args.get('offset', 0))))
        page = self.page(item['entries'], offset)
        return {**{k: v for k, v in item.items() if k not in ('snapshot', 'entries')},
                'entries': page, 'total': len(item['entries']), 'offset': offset,
                'addedTotal': sum(max(0, row.get('added', 0)) for row in item['entries']),
                'removedTotal': sum(max(0, row.get('removed', 0)) for row in item['entries']),
                'hasMore': offset + len(page) < len(item['entries']), 'empty': False}

    def tree(self, item, args):
        path = args.get('path', '')
        prefix = path + '/' if path else ''
        children = {}
        for row in item['entries'] if item and not item['active'] else []:
            if not row['path'].startswith(prefix):
                continue
            name, separator, _ = row['path'][len(prefix):].partition('/')
            if not name:
                continue
            if separator:
                child = children.setdefault(name, {'name': name, 'path': prefix + name,
                    'directory': True, 'status': '', 'count': 0, 'added': -1,
                    'removed': -1, 'omitted': False, 'binary': False})
                child['count'] += 1
            else:
                children[name] = {**row, 'name': name, 'directory': False, 'count': 1}
        rows = sorted(children.values(), key=lambda row: (not row['directory'], row['name'].casefold(), row['name']))
        offset = max(0, min(4000, int(args.get('offset', 0))))
        page = self.page(rows, offset)
        return {'entries': page, 'path': path, 'offset': offset,
                'hasMore': offset + len(page) < len(rows), 'loopId': item['loopId'] if item else '',
                'checkpointId': item.get('checkpointId', '') if item else ''}

    def close(self):
        for item in self.active.values():
            self.dispose(item, interrupted=True)
        self.active.clear()
        self.clear_latest()
        for snapshot in self.loaded.values():
            snapshot.close(remove=False)
        self.loaded.clear()
        super().close()


def create_plugin(context):
    return ChangeReview(context)
