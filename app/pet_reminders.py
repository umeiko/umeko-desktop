"""Profile-local, one-shot reminders owned by the desktop-pet Qt service.

The wall clock returns aware datetimes. An optional timer driver implements
``call_later(milliseconds, callback)`` and returns a handle with ``cancel()``.
Only committed snapshots become visible; a due occurrence is claimed on disk
before any presentation request. No network or model services are involved.
"""
from __future__ import annotations

import copy
import json
import math
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal


_TIME = re.compile(r'^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:[Zz]|[+-]\d{2}:\d{2})$')
_FIELDS = {'id', 'title', 'notes', 'dueAt', 'completed', 'createdAt', 'updatedAt',
           'revision', 'occurrence', 'firedOccurrence', 'processedAt', 'notificationOutcome'}
_OUTCOMES = {'claimed', 'suppressed_hidden', 'suppressed_preference', 'presentation_requested'}


def _utc(value):
    if not isinstance(value, str) or not _TIME.fullmatch(value):
        raise ValueError('dueAt must be an ISO 8601 time with Z or a UTC offset')
    try:
        # fromisoformat accepts invalid-looking offsets such as +01:60; reject
        # those explicitly rather than silently normalizing user input.
        if value[-1:] not in ('Z', 'z'):
            hours, minutes = map(int, value[-5:].split(':'))
            if hours > 23 or minutes > 59:
                raise ValueError()
        parsed = datetime.fromisoformat(value.upper().replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ValueError('Invalid ISO 8601 date or UTC offset') from exc


def _stamp(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _text(value, name, limit, required=False):
    if not isinstance(value, str):
        raise ValueError(name + ' must be a string')
    value = value.strip() if required else value
    if len(value) > limit or required and not value:
        raise ValueError(f'{name} must contain {1 if required else 0}–{limit} characters')
    return value


def _id(value):
    if not isinstance(value, str):
        raise ValueError('id must be a UUID string')
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError()
    except (ValueError, AttributeError) as exc:
        raise ValueError('id must be a UUID string') from exc
    return value


class _QtHandle:
    def __init__(self, parent, milliseconds, callback):
        self.timer = QTimer(parent)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(callback)
        self.timer.start(milliseconds)

    def cancel(self):
        self.timer.stop()
        self.timer.deleteLater()


class PetReminders(QObject):
    changed = Signal()
    due = Signal(object)

    def __init__(self, directory, parent=None, clock=None, timer=None,
                 visible=lambda: False, notifications=lambda: True):
        super().__init__(parent)
        self.directory = Path(directory)
        self.path = self.directory / 'reminders.json'
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.timer = timer
        self.visible = visible
        self.notifications = notifications
        self.running = False
        self.closed = False
        self.error = ''
        self._items = []
        self._invalid = False
        self._paused = False
        self._generation = 0
        self._handle = None
        self._load()

    def _now(self):
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('Reminder clock must return an aware datetime')
        return value.astimezone(timezone.utc)

    def time_info(self):
        now = self._now()
        return {'now': _stamp(now), 'localNow': now.astimezone().isoformat()}

    def _load(self):
        try:
            raw = self.path.read_text(encoding='utf-8')
        except FileNotFoundError:
            return
        except (OSError, UnicodeError) as exc:
            self._load_error(exc)
            return
        try:
            value = json.loads(raw)
            if (not isinstance(value, dict) or set(value) != {'schemaVersion', 'items'}
                    or type(value['schemaVersion']) is not int or value['schemaVersion'] != 1
                    or not isinstance(value['items'], list)):
                raise ValueError('Unsupported reminders file schema')
            seen = set()
            for item in value['items']:
                self._validate_stored(item)
                if item['id'] in seen:
                    raise ValueError('Duplicate reminder id')
                seen.add(item['id'])
            self._items = value['items']
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            self._load_error(exc)

    def _load_error(self, exc):
        self._invalid = True
        self.error = 'Cannot load reminders.json: ' + str(exc)

    @staticmethod
    def _validate_stored(item):
        if not isinstance(item, dict) or set(item) != _FIELDS:
            raise ValueError('Invalid reminder fields')
        _id(item['id'])
        if _text(item['title'], 'title', 200, True) != item['title']:
            raise ValueError('Invalid stored title')
        _text(item['notes'], 'notes', 2000)
        for key in ('createdAt', 'updatedAt'):
            if _stamp(_utc(item[key])) != item[key]:
                raise ValueError('Stored times must be normalized UTC')
        if item['dueAt'] is not None and _stamp(_utc(item['dueAt'])) != item['dueAt']:
            raise ValueError('Stored dueAt must be normalized UTC')
        if type(item['completed']) is not bool:
            raise ValueError('Invalid completed flag')
        for key, minimum in (('revision', 1), ('occurrence', 0)):
            if type(item[key]) is not int or item[key] < minimum:
                raise ValueError('Invalid ' + key)
        if item['dueAt'] is not None and item['occurrence'] == 0:
            raise ValueError('Timed reminder must have an occurrence')
        fired = item['firedOccurrence']
        if fired is not None and (type(fired) is not int or not 1 <= fired <= item['occurrence']):
            raise ValueError('Invalid firedOccurrence')
        if fired is None:
            if item['processedAt'] is not None or item['notificationOutcome'] is not None:
                raise ValueError('Unexpected processed reminder fields')
        elif (item['processedAt'] is None or item['notificationOutcome'] not in _OUTCOMES
              or _stamp(_utc(item['processedAt'])) != item['processedAt']):
            raise ValueError('Invalid processed reminder fields')

    def _write(self, items):
        """Replace one complete snapshot, leaving the old file intact on failure."""
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.directory,
                                             prefix='.reminders-', suffix='.tmp', delete=False) as stream:
                temporary = stream.name
                json.dump({'schemaVersion': 1, 'items': items}, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass

    def _commit(self, items):
        try:
            self._write(items)
        except OSError as exc:
            self.error = 'Cannot save reminders.json: ' + str(exc)
            self.changed.emit()
            raise ValueError(self.error) from exc
        self._items = items
        self.error = ''
        self._paused = False
        self.changed.emit()

    def _cancel(self):
        self._generation += 1
        if self._handle is not None:
            self._handle.cancel()
            self._handle = None

    def start(self):
        if self.closed or self.running:
            return
        self.running = True
        self.check()

    def stop(self):
        self.running = False
        self._cancel()

    def close(self):
        self.closed = True
        self.stop()

    @staticmethod
    def _pending(item):
        return (not item['completed'] and item['dueAt'] is not None
                and item['firedOccurrence'] != item['occurrence'])

    def check(self):
        if not self.running or self.closed or self._invalid or self._paused:
            return
        self._cancel()
        now = self._now()
        due = [item for item in self._ordered(now) if self._pending(item) and _utc(item['dueAt']) <= now]
        if due:
            enabled = bool(self.notifications())
            show = enabled and bool(self.visible())
            outcome = ('claimed' if show else 'suppressed_preference' if not enabled
                       else 'suppressed_hidden')
            items = copy.deepcopy(self._items)
            identifiers = {item['id'] for item in due}
            for item in items:
                if item['id'] in identifiers:
                    item.update(firedOccurrence=item['occurrence'], processedAt=_stamp(now),
                                notificationOutcome=outcome)
            try:
                self._commit(items)
                if show and self.running:
                    # A separate durable claim survives an interruption before
                    # the semantic presentation request is committed/emitted.
                    items = copy.deepcopy(self._items)
                    requested = []
                    for item in items:
                        original = next((row for row in due if row['id'] == item['id']), None)
                        if (original and item['revision'] == original['revision']
                                and item['occurrence'] == original['occurrence']
                                and not item['completed']):
                            item['notificationOutcome'] = 'presentation_requested'
                            requested.append(item)
                    if requested:
                        self._commit(items)
                        if self.running:
                            snapshots = {row['id']: row for row in requested}
                            requested = [self._view(row, now) for row in self._ordered(now)
                                         if row['id'] in snapshots and row == snapshots[row['id']]]
                            if requested:
                                self.due.emit(requested)
            except ValueError:
                self._paused = True
                self._cancel()
                return
        if not self.running or self._paused:
            return
        future = [_utc(item['dueAt']) for item in self._items if self._pending(item)]
        if future:
            milliseconds = max(1, min(60000, math.ceil((min(future) - self._now()).total_seconds() * 1000)))
            generation = self._generation

            def timeout():
                if self.running and not self.closed and generation == self._generation:
                    self.check()

            self._handle = (self.timer.call_later(milliseconds, timeout) if self.timer is not None
                            else _QtHandle(self, milliseconds, timeout))

    def _ordered(self, now):
        def key(item):
            due = _utc(item['dueAt']) if item['dueAt'] else None
            group = 0 if due is not None and due <= now else 1 if due is not None else 2
            return group, due or datetime.max.replace(tzinfo=timezone.utc), _utc(item['createdAt']), item['id']
        return sorted(self._items, key=key)

    @staticmethod
    def _view(item, now):
        result = copy.deepcopy(item)
        result['overdue'] = not item['completed'] and item['dueAt'] is not None and _utc(item['dueAt']) <= now
        return result

    def summary(self):
        now = self._now()
        open_items = [item for item in self._items if not item['completed']]
        future = [_utc(item['dueAt']) for item in self._items if self._pending(item)]
        return {'openCount': len(open_items),
                'overdueCount': sum(item['dueAt'] is not None and _utc(item['dueAt']) <= now for item in open_items),
                'nextDueAt': _stamp(min(future)) if future else None, 'error': self.error}

    def handle(self, method, args):
        schemas = {'listItems': ({'status'}, set()), 'getItem': ({'id'}, {'id'}),
                   'createItem': ({'title', 'notes', 'dueAt'}, {'title'}),
                   'updateItem': ({'id', 'title', 'notes', 'dueAt', 'clearDueAt'}, {'id'}),
                   'completeItem': ({'id'}, {'id'}), 'deleteItem': ({'id'}, {'id'})}
        if not isinstance(method, str) or method not in schemas:
            raise ValueError('Unknown reminder method')
        allowed, required = schemas[method]
        if not isinstance(args, dict) or args.keys() - allowed or required - args.keys():
            raise ValueError('Unknown or missing reminder arguments')
        if self.closed:
            raise ValueError('Reminder service is closed')
        if self._invalid:
            raise ValueError(self.error)
        now = self._now()
        if method == 'listItems':
            status = args.get('status', 'open')
            if not isinstance(status, str) or status not in ('open', 'completed', 'all'):
                raise ValueError('status must be open, completed or all')
            return {'items': [self._view(item, now) for item in self._ordered(now)
                              if status == 'all' or item['completed'] == (status == 'completed')], **self.time_info()}
        if method == 'updateItem' and not args.keys() - {'id'}:
            raise ValueError('updateItem requires title, notes or dueAt')
        patch = {}
        if 'clearDueAt' in args:
            if type(args['clearDueAt']) is not bool:
                raise ValueError('clearDueAt must be a boolean')
            if args['clearDueAt']:
                if args.get('dueAt') is not None:
                    raise ValueError('clearDueAt cannot be combined with a non-null dueAt')
                patch['dueAt'] = None
            elif not args.keys() - {'id', 'clearDueAt'}:
                raise ValueError('updateItem requires an actual editable field')
        if 'title' in args:
            patch['title'] = _text(args['title'], 'title', 200, True)
        if 'notes' in args:
            patch['notes'] = _text(args['notes'], 'notes', 2000)
        if 'dueAt' in args:
            patch['dueAt'] = None if args['dueAt'] is None else _stamp(_utc(args['dueAt']))
        items = copy.deepcopy(self._items)
        if method == 'createItem':
            item = {'id': str(uuid.uuid4()), 'title': patch['title'], 'notes': patch.get('notes', ''),
                    'dueAt': patch.get('dueAt'), 'completed': False, 'createdAt': _stamp(now),
                    'updatedAt': _stamp(now), 'revision': 1, 'occurrence': int(patch.get('dueAt') is not None),
                    'firedOccurrence': None, 'processedAt': None, 'notificationOutcome': None}
            items.append(item)
        else:
            identifier = _id(args['id'])
            item = next((row for row in items if row['id'] == identifier), None)
            if item is None:
                raise ValueError('Reminder id does not exist')
            if method == 'getItem':
                return {'item': self._view(item, now), **self.time_info()}
            if method == 'completeItem':
                patch['completed'] = True
            if method == 'deleteItem':
                items.remove(item)
            elif all(item[key] == value for key, value in patch.items()):
                return {'item': self._view(item, now)}
            else:
                if 'dueAt' in patch and patch['dueAt'] != item['dueAt']:
                    item.update(occurrence=item['occurrence'] + 1, firedOccurrence=None,
                                processedAt=None, notificationOutcome=None)
                item.update(patch)
                item.update(revision=item['revision'] + 1, updatedAt=_stamp(now))
        self._commit(items)
        self.check()
        if method == 'deleteItem':
            return {'deletedId': item['id']}
        current = next(row for row in self._items if row['id'] == item['id'])
        return {'item': self._view(current, self._now())}
