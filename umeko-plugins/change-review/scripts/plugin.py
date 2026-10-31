"""Opt-in loop review: active baselines and a single transient completed review."""
from pathlib import Path
import json
import shutil
from umeko_plugin_sdk import Plugin, PluginError
from .snapshots import Snapshot, SnapshotError, remove_snapshot

class ChangeReview(Plugin):
    def __init__(self, context):
        super().__init__(context)
        self.active = {}
        self.latest = None
        for child in context.state_dir.glob('review-*'):
            if child.is_dir() and not child.is_symlink():
                remove_snapshot(child)

    def key(self):
        target = self.context.capture_session()
        return (target['token'], str(Path(target['workspace']).resolve()))

    @staticmethod
    def dispose(item):
        if item and item.get('snapshot'):
            item['snapshot'].close()
            item['snapshot'] = None

    def clear_latest(self):
        if self.latest:
            self.dispose(self.latest[1])
            self.latest = None

    def item(self, key):
        return self.active.get(key) or (self.latest[1] if self.latest and self.latest[0] == key else None)

    def changed(self):
        # Clearing the single result can affect a different visible chat too.
        # Invalidate its page, but open_page still targets only the finishing chat.
        self.context.publish('review.changed', {})

    def capture_error(self, item, error):
        item['error'] = str(error)[:500]
        item['entries'] = []
        self.dispose(item)

    def handle(self, method, arguments):
        key = self.key()
        if method == 'begin':
            self.clear_latest()
            self.dispose(self.active.pop(key, None))
            # These are concurrent in-flight baselines, never a review history.
            if len(self.active) >= 8:
                return {'captured': False, 'error': '同时审查的会话过多，本轮未采集'}
            item = {'loopId': arguments.get('loopId', ''), 'active': True,
                    'snapshot': None, 'entries': [], 'error': '', 'reason': ''}
            self.active[key] = item
            try:
                item['snapshot'] = Snapshot(key[1], self.context.state_dir, self.context.cancelled)
                item['snapshot'].begin()
            except (SnapshotError, OSError, ValueError, TimeoutError) as error:
                self.capture_error(item, error)
            self.changed()
            return {'captured': not bool(item['error']), 'error': item['error']}

        item = self.item(key)
        if arguments.get('loopId') and (not item or item['loopId'] != arguments['loopId']):
            raise PluginError('本轮记录已替换')
        if method == 'finish':
            item = self.active.get(key)
            if not item or item['loopId'] != arguments.get('loopId'):
                return {'reviewed': False}
            self.active.pop(key)
            self.clear_latest()
            item['active'] = False
            item['reason'] = arguments.get('reason', 'completed')
            if item['snapshot']:
                try:
                    item.update(item['snapshot'].finish())
                except (SnapshotError, OSError, ValueError, TimeoutError) as error:
                    self.capture_error(item, error)
            self.latest = (key, item)
            self.changed()
            if self.context.config.get('autoOpen',True):
                self.context.open_page()
            return {'reviewed': True, 'files': len(item['entries']), 'error': item['error']}
        if method == 'refresh':
            if item and item.get('snapshot') and not item['active']:
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
            if not item or item['active'] or item['error'] or not item.get('snapshot'):
                raise PluginError('本轮差异尚不可用')
            try:
                return item['snapshot'].diff(arguments.get('path', ''))
            except (SnapshotError, OSError) as error:
                raise PluginError(str(error)) from None
        path = arguments.get('path', '')
        if method in ('attach', 'reveal', 'explorer'):
            if not item or not any(row['path'] == path for row in item['entries']):
                raise PluginError('该文件不在本轮变更中')
            if method == 'attach': self.context.attach_file(path)
            elif method == 'reveal': self.context.reveal_file(path)
            else: self.context.reveal_in_explorer(path)
            return {'done': True}
        raise PluginError('未知审查操作')

    @staticmethod
    def page(rows, offset):
        page = []
        size = 0
        for row in rows[offset:offset + 200]:
            weight = len(json.dumps(row, ensure_ascii=True))
            if page and size + weight > 256 * 1024: break
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
                'hasMore': offset + len(page) < len(item['entries']), 'empty': False}

    def tree(self, item, args):
        path = args.get('path', '')
        prefix = path + '/' if path else ''
        children = {}
        for row in item['entries'] if item and not item['active'] else []:
            if not row['path'].startswith(prefix): continue
            name, separator, _ = row['path'][len(prefix):].partition('/')
            if not name: continue
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
                'hasMore': offset + len(page) < len(rows),
                'loopId': item['loopId'] if item else ''}

    def close(self):
        super().close()
        self.clear_latest()
        for item in self.active.values(): self.dispose(item)
        self.active.clear()

def create_plugin(context):
    return ChangeReview(context)
