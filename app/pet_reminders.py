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
from datetime import datetime, timezone, timedelta, time as wall_time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal, QTimeZone


_TIME = re.compile(r'^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:[Zz]|[+-]\d{2}:\d{2})$')
_LEGACY_FIELDS = {'id', 'title', 'notes', 'dueAt', 'completed', 'createdAt', 'updatedAt',
           'revision', 'occurrence', 'firedOccurrence', 'processedAt', 'notificationOutcome'}
_FIELDS = _LEGACY_FIELDS | {'repeat', 'timeZone', 'dailyTime', 'agentId'}
_OUTCOMES = {'claimed', 'suppressed_hidden', 'suppressed_preference', 'presentation_requested', 'restored_overdue'}


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


def _zone(value):
    if not isinstance(value,str) or len(value)>128:raise ValueError('Invalid IANA time zone')
    try:return ZoneInfo(value)
    except (ValueError,ZoneInfoNotFoundError) as error:raise ValueError('Invalid IANA time zone') from error


def _normalize_repeat(item, patch):
    if item['dueAt'] is None:item['repeat']='once'
    if item['repeat']=='once':item.update(timeZone='',dailyTime='');return
    if item['dueAt'] is None:raise ValueError('Daily reminder requires dueAt')
    item['timeZone']=item['timeZone'] or bytes(QTimeZone.systemTimeZoneId()).decode() or 'UTC'
    zone=_zone(item['timeZone'])
    if not item['dailyTime'] or any(key in patch for key in ('dueAt','timeZone')):
        item['dailyTime']=_utc(item['dueAt']).astimezone(zone).strftime('%H:%M:%S')


def _next_daily(item, now):
    zone=_zone(item['timeZone']);previous=_utc(item['dueAt']).astimezone(zone)
    day=max(previous.date()+timedelta(days=1),now.astimezone(zone).date())
    hour=wall_time.fromisoformat(item['dailyTime'])
    for _ in range(4):
        nominal=datetime.combine(day,hour)
        for minute in range(181):
            wall=nominal+timedelta(minutes=minute)
            candidates=[]
            for fold in (0,1):
                candidate=wall.replace(tzinfo=zone,fold=fold).astimezone(timezone.utc)
                if candidate.astimezone(zone).replace(tzinfo=None)==wall:candidates.append(candidate)
            if candidates:
                future=[value for value in candidates if value>now]
                if future:return min(future)
                break
        day+=timedelta(days=1)
    raise ValueError('Cannot find next daily reminder time')


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
                 visible=lambda: False, notifications=lambda: True, assistant=lambda: ''):
        super().__init__(parent)
        self.directory = Path(directory)
        self.path = self.directory / 'reminders.json'
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.timer = timer
        self.visible = visible
        self.notifications = notifications
        self.assistant = assistant
        self._notifications = []
        self._alerts = []
        self.running = False
        self.closed = False
        self.error = ''
        self._items = []
        self._invalid = False
        self._paused = False
        self._generation = 0
        self._handle = None
        self._checking=False
        self._load()

    def _now(self):
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('Reminder clock must return an aware datetime')
        return value.astimezone(timezone.utc)

    def time_info(self):
        now = self._now()
        return {'now': _stamp(now), 'localNow': now.astimezone().isoformat(),'timeZone':bytes(QTimeZone.systemTimeZoneId()).decode() or 'UTC'}

    def _load(self):
        try:
            raw = self.path.read_text(encoding='utf-8')
        except FileNotFoundError:
            return
        except (OSError, UnicodeError) as exc:
            self._load_error(exc)
            return
        try:
            if len(raw.encode('utf-8')) > 8*1024*1024:raise ValueError('Reminders file exceeds 8 MiB')
            value = json.loads(raw)
            if not isinstance(value, dict) or type(value.get('schemaVersion')) is not int or value['schemaVersion'] not in (1,2):
                raise ValueError('Unsupported reminders file schema')
            version = value['schemaVersion']
            if set(value) not in ([{'schemaVersion','items'}] if version == 1 else [{'schemaVersion','items','notifications'},{'schemaVersion','items','notifications','alerts'}]) or not isinstance(value['items'],list) or len(value['items'])>10000:
                raise ValueError('Invalid reminders file')
            if version == 1:
                for item in value['items']:
                    if not isinstance(item,dict) or set(item) != _LEGACY_FIELDS:raise ValueError('Invalid legacy reminder fields')
                    item.update(repeat='once',timeZone='',dailyTime='',agentId='')
            alerts=value.get('alerts',[])
            if not isinstance(alerts,list) or len(alerts)>10000:raise ValueError('Invalid unread reminders')
            for item in alerts:self._validate_stored(item)
            notifications = value.get('notifications',[])
            if not isinstance(notifications,list) or len(notifications)>10000:raise ValueError('Invalid notification outbox')
            for event in notifications:
                if not isinstance(event,dict) or set(event) != {'id','reminderId','occurrence','revision','agentId','title','notes','dueAt','repeat'}:raise ValueError('Invalid reminder notification')
                _id(event['id']);_id(event['reminderId']);_utc(event['dueAt'])
                if type(event['occurrence']) is not int or event['occurrence']<1 or type(event['revision']) is not int or event['revision']<1:raise ValueError('Invalid notification occurrence')
                if not isinstance(event['agentId'],str) or event['agentId'] and not re.fullmatch('[a-f0-9]{32}',event['agentId']):raise ValueError('Invalid reminder Agent')
                _text(event['title'],'title',200,True);_text(event['notes'],'notes',500)
                if event['repeat'] not in ('once','daily'):raise ValueError('Invalid reminder repeat')
            seen = set()
            for item in value['items']:
                self._validate_stored(item)
                if item['id'] in seen:
                    raise ValueError('Duplicate reminder id')
                seen.add(item['id'])
            self._items = value['items']
            self._notifications = notifications
            self._alerts = alerts
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            self._load_error(exc)

    def _load_error(self, exc):
        self._invalid = True
        self.error = 'Cannot load reminders.json: ' + str(exc)

    @staticmethod
    def _validate_stored(item):
        if not isinstance(item, dict) or set(item) != _FIELDS:
            raise ValueError('Invalid reminder fields')
        if item['repeat'] not in ('once','daily') or not isinstance(item['agentId'],str) or item['agentId'] and not re.fullmatch('[a-f0-9]{32}',item['agentId']):
            raise ValueError('Invalid reminder recurrence or Agent')
        if item['repeat']=='daily':
            _zone(item['timeZone'])
            if not item['dueAt'] or not isinstance(item['dailyTime'],str) or not re.fullmatch(r'\d{2}:\d{2}:\d{2}',item['dailyTime']):raise ValueError('Daily reminder requires time')
            wall_time.fromisoformat(item['dailyTime'])
        elif item['timeZone'] or item['dailyTime']:raise ValueError('Unexpected daily reminder fields')
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

    def _write(self, items, notifications=None, alerts=None):
        """Replace one complete snapshot, leaving the old file intact on failure."""
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.directory,
                                             prefix='.reminders-', suffix='.tmp', delete=False) as stream:
                temporary = stream.name
                document={'schemaVersion':2,'items':items,'notifications':self._notifications if notifications is None else notifications,'alerts':self._alerts if alerts is None else alerts}
                raw=json.dumps(document,ensure_ascii=False,indent=2)+'\n'
                if any(len(document[key])>10000 for key in ('items','notifications','alerts')) or len(raw.encode('utf-8'))>8*1024*1024:raise OSError('Reminder storage limit exceeded')
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass

    def _commit(self, items, notifications=None, alerts=None):
        try:
            if notifications is None and alerts is None:self._write(items)
            else:self._write(items,notifications,alerts)
        except OSError as exc:
            self.error = 'Cannot save reminders.json: ' + str(exc)
            self.changed.emit()
            raise ValueError(self.error) from exc
        self._items = items
        if notifications is not None:self._notifications = notifications
        if alerts is not None:self._alerts = alerts
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
        if self._checking:return
        self._checking=True
        try:self._check()
        finally:self._checking=False

    def _check(self):
        if not self.running or self.closed or self._invalid or self._paused:
            return
        self._cancel()
        now = self._now()
        recovered=copy.deepcopy(self._items);changed=False
        for item in recovered:
            if item['repeat']=='daily' and not item['completed'] and item['firedOccurrence']==item['occurrence']:
                item['dueAt']=_stamp(_next_daily(item,now));item['occurrence']+=1;changed=True
        if changed:
            try:self._commit(recovered)
            except ValueError:self._paused=True;return
        due = [item for item in self._ordered(now) if self._pending(item) and _utc(item['dueAt']) <= now]
        if due:
            enabled = bool(self.notifications())
            show = enabled and bool(self.visible())
            outcome = ('claimed' if show else 'suppressed_preference' if not enabled
                       else 'suppressed_hidden')
            items = copy.deepcopy(self._items)
            notifications = copy.deepcopy(self._notifications)
            alerts=copy.deepcopy(self._alerts)
            identifiers = {item['id'] for item in due}
            for item in items:
                if item['id'] in identifiers:
                    if not item['agentId']:item['agentId']=self.assistant()
                    event={'id':str(uuid.uuid5(uuid.NAMESPACE_URL,'umeko-reminder:'+item['id']+':'+str(item['occurrence']))),
                           'reminderId':item['id'],'occurrence':item['occurrence'],'revision':item['revision'],
                           'agentId':item['agentId'],'title':item['title'],'notes':item['notes'][:500],
                           'dueAt':item['dueAt'],'repeat':item['repeat']}
                    # Keep one pending occurrence per reminder after long sleeps/offline periods.
                    notifications=[row for row in notifications if row['reminderId']!=item['id']]
                    notifications.append(event)
                    item.update(firedOccurrence=item['occurrence'], processedAt=_stamp(now),
                                notificationOutcome=outcome)
                    alerts=[row for row in alerts if row['id']!=item['id']]
                    alerts.append(copy.deepcopy(item))
            try:
                self._commit(items, notifications, alerts)
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
                advanced=copy.deepcopy(self._items)
                changed=False
                for item in advanced:
                    if item['id'] in identifiers and item['repeat']=='daily' and not item['completed'] and item['firedOccurrence']==item['occurrence']:
                        item['dueAt']=_stamp(_next_daily(item,now));item['occurrence']+=1;changed=True
                if changed:self._commit(advanced)
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

    def unread_alerts(self):
        return copy.deepcopy(self._alerts)

    def mark_viewed(self, identifier=''):
        alerts=[item for item in self._alerts if identifier and item['id']!=identifier]
        if len(alerts)!=len(self._alerts):self._commit(self._items,alerts=alerts)

    def pending_notifications(self, limit=16, agent=''):
        from itertools import islice
        return copy.deepcopy(list(islice((row for row in self._notifications
            if not agent or row['agentId'] in ('',agent)),limit)))

    def acknowledge_notifications(self, identifiers):
        remaining=[row for row in self._notifications if row['id'] not in identifiers]
        if len(remaining)!=len(self._notifications):self._commit(self._items,remaining)

    def _ordered(self, now):
        def key(item):
            due = _utc(item['dueAt']) if item['dueAt'] else None
            group = 0 if due is not None and due <= now else 1 if due is not None else 2
            return group, due or datetime.max.replace(tzinfo=timezone.utc), _utc(item['createdAt']), item['id']
        return sorted(self._items, key=key)

    def resolve_local_time(self, args):
        if set(args)!={'date','time','timeZone'}:raise ValueError('Expected date, time and timeZone')
        zone=_zone(args['timeZone'])
        if not isinstance(args['date'],str) or not isinstance(args['time'],str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',args['date']) or not re.fullmatch(r'\d{2}:\d{2}',args['time']):return {'candidates':[]}
        try:wall=datetime.fromisoformat(args['date']+'T'+args['time'])
        except ValueError:return {'candidates':[]}
        candidates={}
        for fold in (0,1):
            local=wall.replace(tzinfo=zone,fold=fold);instant=local.astimezone(timezone.utc)
            if instant.astimezone(zone).replace(tzinfo=None)!=wall:continue
            offset=int(local.utcoffset().total_seconds()/60)
            candidates[int(instant.timestamp()*1000)]={'epoch':int(instant.timestamp()*1000),'label':'UTC'+('+' if offset>=0 else '-')+f'{abs(offset)//60:02}:{abs(offset)%60:02}'}
        return {'candidates':[candidates[key] for key in sorted(candidates)]}

    @staticmethod
    def _view(item, now):
        result = copy.deepcopy(item)
        if item['dueAt']:
            local=_utc(item['dueAt']).astimezone(_zone(item['timeZone'])) if item['repeat']=='daily' else _utc(item['dueAt']).astimezone()
            result.update(localDate=local.strftime('%Y-%m-%d'),localTime=local.strftime('%H:%M'))
        result['overdue'] = not item['completed'] and item['dueAt'] is not None and _utc(item['dueAt']) <= now
        return result

    def summary(self):
        now = self._now()
        open_items = [item for item in self._items if not item['completed']]
        future = [_utc(item['dueAt']) for item in self._items if self._pending(item)]
        return {'openCount': len(open_items),
                'overdueCount': sum(item['dueAt'] is not None and _utc(item['dueAt']) <= now for item in open_items),
                'nextDueAt': _stamp(min(future)) if future else None, 'unreadCount':len(self._alerts), 'error': self.error}

    def handle(self, method, args):
        schemas = {'listItems': ({'status'}, set()), 'getItem': ({'id'}, {'id'}),
                   'createItem': ({'title', 'notes', 'dueAt','repeat','timeZone'}, {'title'}),
                   'updateItem': ({'id', 'title', 'notes', 'dueAt', 'clearDueAt','repeat','timeZone'}, {'id'}),
                   'completeItem': ({'id','completed'}, {'id'}), 'deleteItem': ({'id'}, {'id'}), 'clearCompleted': (set(),set())}
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
        if method == 'clearCompleted':
            removed={item['id'] for item in self._items if item['completed']}
            if removed:self._commit([item for item in self._items if item['id'] not in removed],
                                    [row for row in self._notifications if row['reminderId'] not in removed])
            return {'deletedCount':len(removed)}
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
        for field in ('repeat','timeZone'):
            if field in args:patch[field]=args[field]
        if 'repeat' in patch and patch['repeat'] not in ('once','daily'):raise ValueError('repeat must be once or daily')
        if 'timeZone' in patch:_zone(patch['timeZone'])
        items = copy.deepcopy(self._items)
        if method == 'createItem':
            if patch.get('repeat')=='daily' and not patch.get('dueAt'):raise ValueError('Daily reminder requires dueAt')
            item = {'id': str(uuid.uuid4()), 'title': patch['title'], 'notes': patch.get('notes', ''),
                    'dueAt': patch.get('dueAt'), 'completed': False, 'createdAt': _stamp(now),
                    'updatedAt': _stamp(now), 'revision': 1, 'occurrence': int(patch.get('dueAt') is not None),
                    'firedOccurrence': None, 'processedAt': None, 'notificationOutcome': None,
                    'repeat':patch.get('repeat','once'),'timeZone':patch.get('timeZone',''),'dailyTime':'','agentId':self.assistant()}
            _normalize_repeat(item,patch)
            items.append(item)
        else:
            identifier = _id(args['id'])
            item = next((row for row in items if row['id'] == identifier), None)
            if item is None:
                raise ValueError('Reminder id does not exist')
            if method == 'getItem':
                return {'item': self._view(item, now), **self.time_info()}
            if method == 'completeItem':
                completed=args.get('completed',True)
                if type(completed) is not bool:raise ValueError('completed must be a boolean')
                patch['completed'] = completed
                # Restoring an overdue item shows it in red without replaying
                # missed notifications. Future occurrences retain their schedule.
                if not completed and item['completed'] and item['dueAt'] and _utc(item['dueAt'])<=now and item['firedOccurrence']!=item['occurrence']:
                    patch.update(firedOccurrence=item['occurrence'],processedAt=_stamp(now),notificationOutcome='restored_overdue')
            if method == 'deleteItem':
                items.remove(item)
            elif all(item[key] == value for key, value in patch.items()):
                return {'item': self._view(item, now)}
            else:
                updated={**item,**patch};_normalize_repeat(updated,patch)
                patch.update({key:updated[key] for key in ('repeat','timeZone','dailyTime')})
                if any(key in patch and patch[key]!=item[key] for key in ('dueAt','repeat','timeZone','dailyTime')):
                    # A new schedule starts a fresh reminder, including for a
                    # completed item. Content-only edits preserve completion.
                    if updated['dueAt'] is not None:
                        patch['completed'] = False
                    item.update(occurrence=item['occurrence'] + 1, firedOccurrence=None,
                                processedAt=None, notificationOutcome=None)
                item.update(patch)
                item.update(revision=item['revision'] + 1, updatedAt=_stamp(now))
        notifications=[row for row in self._notifications if row['reminderId']!=item['id']]
        self._commit(items,notifications)
        self.check()
        if method == 'deleteItem':
            return {'deletedId': item['id']}
        current = next(row for row in self._items if row['id'] == item['id'])
        return {'item': self._view(current, self._now())}
