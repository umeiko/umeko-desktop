"""Persistent calendar and run history for the scheduled tasks Widget."""
from __future__ import annotations

from collections import Counter
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP
import json
import sqlite3
import sys
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

# Windows/standalone Python may have no system IANA database. Keep the pinned
# fallback as an importable zip; avoid installation or extraction at startup.
sys.path.append(str(Path(__file__).resolve().parents[1] / "vendor/tzdata-2026.6-py2.py3-none-any.whl"))


@dataclass(frozen=True)
class Schedule:
    frequency: str
    first_date: date | None = None
    local_time: time | None = None
    zone: str = 'UTC'
    interval_value: str = '1'
    interval_unit: str = 'minutes'
    anchor_at: int | float | None = None

    def __post_init__(self):
        # Calendar recurrences are read-only compatibility for early PR builds.
        # The Widget and Agent creation API expose only once / interval.
        if self.frequency not in {'once', 'interval', 'daily', 'weekly', 'weekdays'}:
            raise ValueError('Unknown schedule frequency')
        if self.frequency == 'interval':
            self.interval_us()
            if self.anchor_at is not None:
                self.timestamp_us(self.anchor_at)
            return
        if not isinstance(self.first_date, date) or not isinstance(self.local_time, time):
            raise ValueError('Date and local time are required')
        if self.local_time.tzinfo is not None:
            raise ValueError('Specify the time zone separately')
        ZoneInfo(self.zone)

    @staticmethod
    def timestamp_us(value):
        try:
            number = Decimal(str(value))
            if isinstance(value, bool) or not number.is_finite() or not 0 <= number <= 253402300799:
                raise ValueError('Invalid schedule timestamp')
            return int((number * 1000000).to_integral_value(rounding=ROUND_HALF_UP))
        except (InvalidOperation, TypeError):
            raise ValueError('Invalid schedule timestamp') from None

    def interval_us(self):
        units = {'days': 86400, 'hours': 3600, 'minutes': 60}
        try:
            if self.interval_unit not in units or isinstance(self.interval_value, bool):
                raise ValueError('Interval units must be days, hours or minutes')
            seconds = Decimal(str(self.interval_value)) * units[self.interval_unit]
            if not seconds.is_finite() or seconds < 15:
                raise ValueError('触发间隔不能小于 15 秒 / Minimum interval is 15 seconds')
            if seconds > 253402300799:
                raise ValueError('Interval exceeds the supported date range')
            return int((seconds * 1000000).to_integral_value(rounding=ROUND_CEILING))
        except (InvalidOperation, TypeError):
            raise ValueError('Interval must be a finite decimal number') from None

    def next_after(self, timestamp: int) -> int | None:
        if self.frequency == 'interval':
            anchor = self.timestamp_us(self.anchor_at)
            period = self.interval_us()
            step = max(1, (self.timestamp_us(timestamp) - anchor) // period + 1)
            candidate = anchor + step * period
            self.timestamp_us(Decimal(candidate) / 1000000)
            return candidate / 1000000
        zone = ZoneInfo(self.zone)
        day = max(self.first_date, datetime.fromtimestamp(timestamp, zone).date())
        if self.frequency == 'once':
            if day != self.first_date:
                return None
            candidate = self._timestamp(day, zone)
            return candidate if candidate > timestamp else None
        while True:
            matches = (self.frequency == 'daily'
                       or self.frequency == 'weekdays' and day.weekday() < 5
                       or self.frequency == 'weekly' and day.weekday() == self.first_date.weekday())
            if matches:
                candidate = self._timestamp(day, zone)
                if candidate > timestamp:
                    return candidate
            day += timedelta(days=1)

    def _timestamp(self, day: date, zone: ZoneInfo) -> int:
        # In a fall-back overlap, use the earlier instant. In a spring-forward
        # gap, advance by the size of the offset change (02:30 becomes 03:30).
        local = datetime.combine(day, self.local_time, zone).replace(fold=0)
        return int(local.astimezone(timezone.utc).timestamp())

    def serialize(self) -> dict:
        if self.frequency == 'interval':
            return {'frequency': 'interval', 'interval_value': str(self.interval_value),
                    'interval_unit': self.interval_unit, 'anchor_at': self.anchor_at, 'zone': 'UTC'}
        return {'frequency': self.frequency, 'first_date': self.first_date.isoformat(),
                'local_time': self.local_time.isoformat(), 'zone': self.zone}

    @classmethod
    def from_dict(cls, values: dict, *, now=None) -> Schedule:
        if values.get('frequency') == 'interval':
            return cls('interval', interval_value=values['interval_value'], interval_unit=values['interval_unit'],
                       anchor_at=now if now is not None else values.get('anchor_at'))
        if values.get('frequency') == 'once' and {'delay_value', 'delay_unit'} & values.keys():
            if now is None or set(values) != {'frequency', 'delay_value', 'delay_unit'}:
                raise ValueError('Use either a countdown or a calendar date, not both')
            delay = cls('interval', interval_value=values['delay_value'], interval_unit=values['delay_unit'])
            # Round up to the next second so decimal countdowns never fire early.
            due = (cls.timestamp_us(now) + delay.interval_us() + 999999) // 1000000
            cls.timestamp_us(due)
            instant = datetime.fromtimestamp(due, timezone.utc)
            return cls('once', instant.date(), instant.time().replace(tzinfo=None), 'UTC')
        return cls(values['frequency'], date.fromisoformat(values['first_date']),
                   time.fromisoformat(values['local_time']), values['zone'])


class ScheduledTasks:
    def __init__(self, database):
        self.database = database
        with self._write() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS schedules (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, message TEXT NOT NULL,
                profile TEXT NOT NULL, schedule TEXT NOT NULL,
                enabled INTEGER NOT NULL, next_at INTEGER)''')
            db.execute('''CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, task_id TEXT NOT NULL,
                scheduled_at INTEGER, started_at INTEGER NOT NULL, finished_at INTEGER,
                state TEXT NOT NULL, snapshot TEXT NOT NULL, detail TEXT,
                session_id TEXT, UNIQUE (task_id, scheduled_at))''')
            db.execute('''CREATE UNIQUE INDEX IF NOT EXISTS one_active_run
                ON runs(task_id) WHERE state = 'running' ''')
            columns = {row['name'] for row in db.execute('PRAGMA table_info(schedules)')}
            for column, default in (('owner', ''), ('source', '{}'), ('target', 'main')):
                if column not in columns:
                    db.execute(f"ALTER TABLE schedules ADD COLUMN {column} TEXT NOT NULL DEFAULT '{default}'")
            if 'model_oneshot' not in columns:
                db.execute('ALTER TABLE schedules ADD COLUMN model_oneshot INTEGER NOT NULL DEFAULT 0')
            db.execute('CREATE INDEX IF NOT EXISTS due_schedules ON schedules(enabled, next_at)')
            db.execute('CREATE TABLE IF NOT EXISTS session_owners (token TEXT PRIMARY KEY, owner TEXT NOT NULL)')

    def _connect(self):
        db = sqlite3.connect(self.database)
        db.row_factory = sqlite3.Row
        return db

    @contextmanager
    def _write(self):
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            yield db

    def bind_session(self, session):
        token, identifier = session.get('token'), session.get('id')
        if not isinstance(token, str) or not token:
            raise ValueError('A real calling session is required')
        if not isinstance(identifier, str):raise ValueError('Invalid session identity')
        owner = 'session:' + identifier if identifier else 'draft:' + token
        source = {key: session.get(key, '') for key in ('token', 'id', 'workspace')}
        with self._write() as db:
            previous = db.execute('SELECT owner FROM session_owners WHERE token=?', (token,)).fetchone()
            if previous:
                if not identifier:owner = previous['owner']
                elif previous['owner'] != owner:
                    db.execute('UPDATE schedules SET owner=? WHERE owner=?', (owner, previous['owner']))
            if not identifier and owner.startswith('session:'):
                source['id'] = owner.removeprefix('session:')
            db.execute('INSERT INTO session_owners VALUES (?,?) ON CONFLICT(token) DO UPDATE SET owner=excluded.owner', (token, owner))
            # Persist promotion from a draft to a native ID for app restarts.
            if identifier or not previous:
                db.execute('UPDATE schedules SET source=? WHERE owner=?', (json.dumps(source), owner))
        return owner, source

    def save(self, *, name, message, schedule, enabled, now, task_id=None, profile='', owner='', source=None, target='main', model_oneshot=False):
        if not all(isinstance(value, str) and value.strip() for value in (name, message)):
            raise ValueError('Name and message are required')
        next_at = schedule.next_after(now) if enabled else None
        if enabled and next_at is None:
            raise ValueError('Schedule has no future occurrence')
        model_oneshot = bool(model_oneshot and enabled and schedule.frequency == 'once')
        with self._write() as db:
            if task_id is None and model_oneshot:
                # Reuse only a proven model-created, automatically expired slot.
                # The same transaction protects quota and concurrent create/claim.
                candidates = db.execute('''SELECT * FROM schedules s
                    WHERE owner=? AND model_oneshot=1 AND enabled=0 AND next_at IS NULL
                    AND NOT EXISTS (SELECT 1 FROM runs r WHERE r.task_id=s.id AND r.state='running')
                    ORDER BY s.rowid''', (owner,)).fetchall()
                for previous in candidates:
                    prior_schedule = Schedule.from_dict(json.loads(previous['schedule']))
                    if prior_schedule.frequency == 'once' and prior_schedule.next_after(now) is None:
                        task_id = previous['id']
                        break
            previous = self._task(db, task_id, owner) if task_id is not None else None
            self._quota(db, owner, target, previous)
            task_id = task_id or uuid4().hex
            db.execute('''INSERT INTO schedules (id,name,message,profile,schedule,enabled,next_at,owner,source,target,model_oneshot)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name, message=excluded.message,
                profile=excluded.profile, schedule=excluded.schedule, enabled=excluded.enabled,
                next_at=excluded.next_at, owner=excluded.owner, source=excluded.source, target=excluded.target,
                model_oneshot=excluded.model_oneshot''',
                (task_id, name.strip(), message, profile, json.dumps(schedule.serialize()), enabled,
                 next_at, owner, json.dumps(source or {}), target, model_oneshot))
        return task_id

    def set_enabled(self, task_id, enabled, now, *, owner=None):
        with self._write() as db:
            task = self._task(db, task_id, owner)
            # An explicit pause transfers control back to the user/ordinary API.
            if not enabled:db.execute('UPDATE schedules SET model_oneshot=0 WHERE id=?', (task_id,))
            if task['enabled'] == enabled:
                return
            schedule = Schedule.from_dict(json.loads(task['schedule']))
            if enabled and schedule.frequency == 'interval':
                schedule = Schedule.from_dict(schedule.serialize(), now=now)
            next_at = schedule.next_after(now) if enabled else None
            if enabled and next_at is None:
                raise ValueError('Schedule has no future occurrence')
            db.execute('UPDATE schedules SET enabled=?, next_at=?, schedule=? WHERE id=?',
                       (enabled, next_at, json.dumps(schedule.serialize()), task_id))

    def tasks(self, *, owner=None):
        with closing(self._connect()) as db:
            # The insertion slot stays with the task when its name or schedule changes.
            rows = db.execute('SELECT *, rowid - 1 AS color_index FROM schedules' +
                              (" WHERE owner=? OR target LIKE 'agent:%'" if owner is not None else '') + ' ORDER BY name, id',
                              (owner,) if owner is not None else ()).fetchall()
        return [{**dict(row), 'schedule': json.loads(row['schedule']), 'source': json.loads(row['source'])} for row in rows]

    def history(self, task_id, *, limit=50, owner=None):
        with closing(self._connect()) as db:
            if owner is not None:self._task(db, task_id, owner)
            rows = db.execute('''SELECT * FROM runs WHERE task_id=? ORDER BY rowid DESC LIMIT ?''',
                              (task_id, limit)).fetchall()
        return [{**dict(row), 'snapshot': json.loads(row['snapshot'])} for row in rows]

    def recover(self, now):
        """Call once when the sole scheduler owner starts, before dispatching work."""
        with self._write() as db:
            db.execute("UPDATE runs SET state='interrupted', finished_at=? WHERE state='running'", (now,))

    def claim_due(self, now, *, eligible_since):
        """Reserve eligible occurrences before callers start an external session.

        Older occurrences are marked missed. Bound the amount of backlog processed
        per task per poll so a long absence cannot block the dispatcher indefinitely.
        """
        claimed = []
        with self._write() as db:
            tasks = db.execute('''SELECT * FROM schedules WHERE enabled=1 AND next_at<=?
                                  ORDER BY next_at, id''', (now,)).fetchall()
            for task in tasks:
                schedule = Schedule.from_dict(json.loads(task['schedule']))
                scheduled_at = task['next_at']
                for _ in range(32):
                    if scheduled_at is None or scheduled_at > now:
                        break
                    state = 'missed' if scheduled_at < eligible_since else 'running'
                    if state == 'running' and self._active(db, task['id']):
                        state = 'skipped'
                    run = self._insert_run(db, task, scheduled_at, now, state)
                    if run is not None and state == 'running':
                        claimed.append(run)
                    scheduled_at = schedule.next_after(scheduled_at)
                if scheduled_at is not None and scheduled_at <= now:
                    scheduled_at = schedule.next_after(now)
                db.execute('UPDATE schedules SET enabled=?, next_at=? WHERE id=?',
                           (scheduled_at is not None, scheduled_at, task['id']))
        return claimed

    def delete(self, task_id, *, owner):
        with self._write() as db:
            self._task(db, task_id, owner)
            # Already submitted messages cannot be retracted. Keep their run
            # history and stop all future occurrences by removing the timer.
            db.execute('DELETE FROM schedules WHERE id=?', (task_id,))

    def running(self, run_id):
        with closing(self._connect()) as db:
            return bool(db.execute("SELECT 1 FROM runs WHERE id=? AND state='running'", (run_id,)).fetchone())

    def claim_manual(self, task_id, now, *, owner=None):
        with self._write() as db:
            task = self._task(db, task_id, owner)
            if self._active(db, task_id):
                raise ValueError('Task already running')
            return self._insert_run(db, task, None, now, 'running')

    def set_session(self, run_id, session_id):
        with self._write() as db:
            db.execute("UPDATE runs SET session_id=? WHERE id=? AND state='running'", (session_id, run_id))

    def finish(self, run_id, state, now, *, detail=None):
        if state not in {'completed', 'delivered', 'failed', 'cancelled', 'interrupted'}:
            raise ValueError('Invalid terminal state')
        with self._write() as db:
            return bool(db.execute('''UPDATE runs SET state=?, finished_at=?, detail=?
                WHERE id=? AND state='running' ''', (state, now, detail, run_id)).rowcount)

    @staticmethod
    def _task(db, task_id, owner=None):
        task = db.execute('SELECT * FROM schedules WHERE id=?', (task_id,)).fetchone()
        if task is None or owner is not None and task['owner'] != owner and not task['target'].startswith('agent:'):
            raise KeyError(task_id)
        return task

    @staticmethod
    def _quota(db, owner, target, previous):
        local, globals_count = Counter(), 0
        for row in db.execute('SELECT owner, target FROM schedules'):
            if row['target'].startswith('agent:'):globals_count += 1
            else:local[row['owner']] += 1
        owners = set(local) | {owner}
        if previous:owners.add(previous['owner'])
        for current in owners:
            before = globals_count + local[current]
            after = before + int(target.startswith('agent:') or current == owner)
            if previous:after -= int(previous['target'].startswith('agent:') or previous['owner'] == current)
            if after > 5 and after > before:
                raise ValueError('每个会话最多 5 个定时器（含全局及停用项） / Maximum 5 timers per conversation, including global and disabled timers')

    def reconcile_global_targets(self, targets):
        """A missing global Agent pauses its timers; identity and history survive."""
        with self._write() as db:
            missing = [row['id'] for row in db.execute(
                "SELECT id,target FROM schedules WHERE target LIKE 'agent:%' AND (enabled!=0 OR next_at IS NOT NULL OR model_oneshot!=0)")
                if row['target'] not in targets]
            db.executemany('UPDATE schedules SET enabled=0,next_at=NULL,model_oneshot=0 WHERE id=?', ((key,) for key in missing))

    @staticmethod
    def _active(db, task_id):
        return db.execute("SELECT 1 FROM runs WHERE task_id=? AND state='running'", (task_id,)).fetchone()

    @staticmethod
    def _insert_run(db, task, scheduled_at, now, state):
        run_id = uuid4().hex
        snapshot = {key: task[key] for key in ('name', 'message', 'profile', 'owner', 'target')}
        snapshot['source'] = json.loads(task['source'])
        snapshot['schedule'] = json.loads(task['schedule'])
        detail = {'skipped': 'previous_run_active', 'missed': 'outside_dispatch_window'}.get(state)
        inserted = db.execute('''INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(task_id, scheduled_at) DO NOTHING''', (run_id, task['id'], scheduled_at, now,
            None if state == 'running' else now, state, json.dumps(snapshot, ensure_ascii=False), detail))
        if inserted.rowcount:
            return {'id': run_id, 'task_id': task['id'], 'scheduled_at': scheduled_at, 'snapshot': snapshot}
        return None
