"""Official application-lifetime Widget: a low-frequency activity companion.

No model calls, token listeners or transcript scans. Only the current animation
is decoded by QML; hiding the window unloads its decoder.
"""
from __future__ import annotations

import copy
import json
import random
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, Property, QTimer, QUrl, Qt, Signal, Slot

from .pet_packs import STATES, import_pack, read_pack

ID = 'desktop-pet'
DEFAULTS = {'visible': False, 'appearance': 'yanami', 'size': 192, 'alwaysOnTop': True,
            'paused': False, 'sampleIntervalMs': 1500, 'minimumStateMs': 3000}


class PetMotion:
    """Monotonic clock, latest-wins transitions, and bounded interaction holds."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.state = 'idle'
        self.since = clock()
        self.target = 'idle'
        self.interaction = ''
        self.until = 0

    def request(self, state):
        self.target = state if state in STATES else 'idle'

    def interact(self, state, minimum):
        self.interaction = state
        self.until = max(self.clock(), self.since + minimum) + minimum

    def step(self, minimum=3, paused=False):
        now = self.clock()
        if self.interaction and now >= self.until:
            self.interaction = ''
        wanted = self.interaction or self.target
        if not paused and wanted != self.state and now - self.since >= minimum:
            self.state, self.since = wanted, now
            return True
        return False


class DesktopPet(QObject):
    changed = Signal()
    reaction = Signal(str)
    restoreRequested = Signal()
    settingsRequested = Signal()
    resetPositionRequested = Signal()
    imported = Signal(str, object)

    def __init__(self, manager):
        super().__init__(manager)
        self.manager = manager
        self.b = manager.b
        self.motion = PetMotion()
        self.running = False
        self.closed = False
        self.importing = False
        self.last_error = ''
        self._packs = {}
        self._config = dict(DEFAULTS)
        self._activity = {'state': 'idle', 'activeChats': 0, 'activeSubagents': 0}
        self._observed = {}
        self._terminal = None
        self._last_interaction = -10.0
        self._last_interaction_kind = ''
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='pet-import')
        self._future = None
        self.directory = manager.root / 'state' / ID
        self.pack_directory = self.directory / 'appearances'
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.CoarseTimer)
        self.timer.timeout.connect(self.sample)
        self.imported.connect(self.finish_import)
        self.load_packs()
        try:
            self.configure(manager.settings.get('config', {}).get(ID, {}), persist=False)
        except ValueError:
            self.last_error = '桌宠配置或形象不可用，已恢复默认设置'
            self.configure(DEFAULTS, persist=False)

    def load_packs(self):
        assets = self.b.root / 'umeko-plugins' / ID / 'assets'
        builtins = sorted((p for p in assets.glob('*') if p.is_dir() and not p.name.startswith('.')),
                          key=lambda p: (p.name != 'yanami', p.name))
        self._packs = {}
        for path, builtin_flag in [*((p, True) for p in builtins), *((p, False) for p in self.pack_directory.glob('*') if p.is_dir() and not p.name.startswith('.'))]:
            try:
                pack = read_pack(path)
                if pack['id'] in self._packs:
                    continue
                self._packs[pack['id']] = {**pack, 'directory': path, 'builtin': builtin_flag}
            except (OSError, ValueError, TypeError):
                continue

    @Property('QVariantMap', notify=changed)
    def config(self):
        return copy.deepcopy(self._config)

    @Property(bool, notify=changed)
    def visible(self):
        return self.running and self._config['visible'] and not self.closed

    @Property('QVariantList', notify=changed)
    def appearances(self):
        return [{'id': p['id'], 'name': p['name'], 'builtin': p['builtin']} for p in self._packs.values()]

    @Property('QVariantMap', notify=changed)
    def state(self):
        pack = self._packs.get(self._config['appearance']) or self._packs.get('yanami', {})
        asset = pack.get('states', {}).get(self.motion.state) or pack.get('states', {}).get('idle', '')
        source = QUrl.fromLocalFile(str(pack['directory'] / asset)).toString() if asset else ''
        top = pack.get('images', {}).get(asset, {}).get('contentTop', 0)
        top = top if type(top) in (int, float) and 0 <= top <= 1 else 0
        return {'action': self.motion.state, 'source': source, 'animated': pack.get('images', {}).get(asset, {}).get('animated', True),
                'contentTop': top,
                'appearance': pack.get('id', 'yanami'), 'name': pack.get('name', ''), 'running': self.running,
                'activity': copy.deepcopy(self._activity), 'importing': self.importing, 'error': self.last_error}

    def start(self):
        if self.running or self.closed:
            return
        self.running = True
        self.timer.start(self._config['sampleIntervalMs'])
        self.sample()
        self.changed.emit()

    def stop(self):
        self.running = False
        self.timer.stop()
        self.changed.emit()

    def close(self):
        self.closed = True
        self.stop()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def configure(self, patch, persist=True):
        if not isinstance(patch, dict) or patch.keys() - DEFAULTS.keys():
            raise ValueError('未知的桌宠配置项')
        value = {**self._config, **patch}
        for name in ('visible', 'alwaysOnTop', 'paused'):
            if type(value[name]) is not bool:
                raise ValueError(name + ' 必须是布尔值')
        for name, low, high in (('size', 96, 320), ('sampleIntervalMs', 1000, 2000), ('minimumStateMs', 3000, 30000)):
            if type(value[name]) is not int or not low <= value[name] <= high:
                raise ValueError(f'{name} 必须是 {low}–{high} 的整数')
        if not isinstance(value['appearance'], str) or value['appearance'] not in self._packs:
            raise ValueError('形象不存在，请先导入并通过 appearances 查询可用 id')
        if persist:
            old = copy.deepcopy(self.manager.settings)
            self.manager.settings.setdefault('config', {})[ID] = value
            if not self.manager.save():
                self.manager.settings = old
                raise ValueError('桌宠设置保存失败')
        self._config = value
        self.timer.setInterval(value['sampleIntervalMs'])
        self.changed.emit()
        self.manager.changed.emit()
        return self.status()

    def sample(self):
        if not self.running:
            return
        pool = getattr(getattr(self.b, '_pool', None), 'records', {})
        records = list(pool.values()) or [self.b._view]
        live = []
        subagents = 0
        for record in records:
            busy = bool(getattr(record, 'busy', False))
            key = record.key
            previous = self._observed.get(key)
            if previous is True and not busy and not getattr(record, 'cancelled', False):
                self._terminal = ('error' if getattr(record, 'failed', False) else 'done', time.monotonic() + 6)
            self._observed[key] = busy
            if busy:
                live.append(record)
            subagents += sum(row.get('status') in ('running','starting','queued','waiting') for row in getattr(record, 'subagents', {}).values())
        self._observed = {r.key: self._observed[r.key] for r in records}
        if any(getattr(r, 'approval', None) or getattr(r, 'network_retry', None) for r in live):
            target = 'waiting'
        elif live:
            # A tiny event-fed enum, never parse message text or a localized label.
            target = 'working' if any(getattr(r, 'pet_activity', '') == 'working' for r in live) else 'thinking'
        elif subagents:
            target = 'working'
        elif self._terminal and time.monotonic() < self._terminal[1]:
            target = self._terminal[0]
        else:
            target = 'idle'
        activity = {'state': target, 'activeChats': len(live), 'activeSubagents': subagents}
        announce = target in ('done', 'error') and self._activity['state'] != target
        changed = activity != self._activity
        self._activity = activity
        self.motion.request(target)
        changed = self.motion.step(self._config['minimumStateMs'] / 1000, self._config['paused']) or changed
        if announce:
            self._speak(target)
        if changed:
            self.changed.emit()

    def status(self):
        return {'config': self.config, 'state': self.state, 'appearances': self.appearances, 'visible': self.visible}

    @Slot(str)
    def interact(self, kind):
        now = time.monotonic()
        if not self.running or kind == self._last_interaction_kind and now - self._last_interaction < .4:
            return
        self._last_interaction = now
        self._last_interaction_kind = kind
        self._speak(kind)
        if kind in ('tap', 'hover', 'drag'):
            if kind != 'hover' or self.motion.target == 'idle':
                self.motion.interact('done' if kind == 'tap' else 'waiting', self._config['minimumStateMs'] / 1000)
                if self.motion.step(self._config['minimumStateMs'] / 1000, self._config['paused']):
                    self.changed.emit()

    def _speak(self, kind):
        pack = self._packs.get(self._config['appearance'], {})
        lines = pack.get('dialogue', {}).get(kind, [])
        if lines:
            self.reaction.emit(random.choice(lines))

    @Slot(str, 'QVariantMap', result='QVariantMap')
    def ui(self, method, arguments):
        try:
            return {'ok': True, 'result': self.handle(method, arguments)}
        except (ValueError, OSError) as error:
            self.last_error = str(error)
            self.changed.emit()
            return {'ok': False, 'error': str(error)}

    def handle(self, method, args):
        specification=self.manager.entries[ID].get('agent',{}).get('methods',{}).get(method)
        if not specification or not isinstance(args,dict):
            raise ValueError('未知的桌宠方法或无效参数，请读取 widgets.docs')
        schema=specification['parameters']
        if args.keys()-schema.get('properties',{}).keys() or any(key not in args for key in schema.get('required',[])):
            raise ValueError('桌宠方法参数缺失或包含未知字段')
        for key,value in args.items():
            spec=schema['properties'][key]
            if spec['type']=='string' and (not isinstance(value,str) or len(value)>spec.get('maxLength',65536)) or 'enum' in spec and value not in spec['enum']:
                raise ValueError('桌宠方法参数无效：'+key)
        if method in ('status', 'appearances'):
            return self.status() if method == 'status' else {'appearances': self.appearances}
        if method == 'configure':
            return self.configure(args)
        if method == 'show':
            return self.configure({'visible': True})
        if method == 'hide':
            return self.configure({'visible': False})
        if method == 'interact':
            self.interact(args.get('kind', 'tap'))
            return self.status()
        if method == 'importAppearance':
            return self.begin_import(args.get('path', ''))
        if method == 'selectAppearance':
            return self.configure({'appearance': args.get('id')})
        if method == 'removeAppearance':
            identifier = args.get('id')
            if self.importing or identifier not in self._packs or self._packs[identifier]['builtin']:
                raise ValueError('不能删除内置形象，或形象正在导入')
            if self._config['appearance'] == identifier:
                self.configure({'appearance': 'yanami'})
            import shutil
            shutil.rmtree(self._packs[identifier]['directory'])
            self.load_packs()
            self.changed.emit()
            return self.status()
        if method == 'resetPosition':
            self.resetPositionRequested.emit()
            self.savePosition(-1, -1)
            return self.status()
        raise ValueError('未知的桌宠方法，请读取 widgets.docs')

    def begin_import(self, source):
        if self.importing or self.closed:
            raise ValueError('正在导入形象，请稍候')
        url = QUrl(source)
        path = url.toLocalFile() if url.isLocalFile() else source
        if not isinstance(path, str) or not Path(path).expanduser().is_absolute():
            raise ValueError('path 必须是本机绝对路径')
        self.importing = True
        self.last_error = ''
        token = uuid.uuid4().hex
        reserved = tuple(p['id'] for p in self._packs.values() if p['builtin'])
        self._future = self._executor.submit(import_pack, path, self.pack_directory, reserved)
        def finish(future):
            try:
                result = {'ok': True, 'appearance': future.result()}
            except Exception as error:
                result = {'ok': False, 'error': str(error)}
            try:self.imported.emit(token, result)
            except RuntimeError:pass  # The application may have exited during validation.
        self._future.add_done_callback(finish)
        self.changed.emit()
        return {'status': 'importing', 'importId': token}

    def finish_import(self, token, result):
        self.importing = False
        if not self.closed:
            self.last_error = '' if result['ok'] else result['error']
            self.load_packs()
            self.changed.emit()

    @Slot(int, int)
    def savePosition(self, x, y):
        if self.closed:
            return
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            target = self.directory / 'position.json'
            temporary = target.with_suffix('.tmp')
            temporary.write_text(json.dumps({'x': x, 'y': y}), encoding='utf-8')
            temporary.replace(target)
        except OSError:
            self.b.toast.emit('桌宠位置保存失败')

    @Slot(result='QVariantMap')
    def position(self):
        try:
            value = json.loads((self.directory / 'position.json').read_text(encoding='utf-8'))
            if type(value['x']) is int and type(value['y']) is int:
                return value
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return {'x': -1, 'y': -1}

    @Slot(int, int, result='QVariantMap')
    def screenBounds(self, x, y):
        from PySide6.QtGui import QGuiApplication
        screens = QGuiApplication.screens()
        if not screens:
            return {'x':0,'y':0,'width':1920,'height':1080}
        def distance(screen):
            area=screen.availableGeometry()
            dx=max(area.left()-x,0,x-area.right())
            dy=max(area.top()-y,0,y-area.bottom())
            return dx*dx+dy*dy
        screen=QGuiApplication.screenAt(QPoint(x,y)) or min(screens,key=distance)
        area=screen.availableGeometry()
        return {'x':area.x(),'y':area.y(),'width':area.width(),'height':area.height()}
