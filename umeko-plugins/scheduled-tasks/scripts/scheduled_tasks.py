"""Persistent calendar and run history for the scheduled tasks Widget."""
from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import json
import sqlite3
from uuid import uuid4
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Schedule:
    frequency: str
    first_date: date
    local_time: time
    zone: str

    def __post_init__(self):
        if self.frequency not in {'once', 'daily', 'weekly', 'weekdays'}:
            raise ValueError('Unknown schedule frequency')
        if self.local_time.tzinfo is not None:
            raise ValueError('Specify the time zone separately')
        ZoneInfo(self.zone)

    def next_after(self, timestamp: int) -> int | None:
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
        return {'frequency': self.frequency, 'first_date': self.first_date.isoformat(),
                'local_time': self.local_time.isoformat(), 'zone': self.zone}

    @classmethod
    def from_dict(cls, values: dict) -> Schedule:
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

    def _connect(self):
        db = sqlite3.connect(self.database)
        db.row_factory = sqlite3.Row
        return db

    @contextmanager
    def _write(self):
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            yield db

    def save(self, *, name, message, profile, schedule, enabled, now, task_id=None):
        if not all(isinstance(value, str) and value.strip() for value in (name, message, profile)):
            raise ValueError('Name, message and session profile are required')
        next_at = schedule.next_after(now) if enabled else None
        if enabled and next_at is None:
            raise ValueError('Schedule has no future occurrence')
        task_id = task_id or uuid4().hex
        with self._write() as db:
            db.execute('''INSERT INTO schedules VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name, message=excluded.message,
                profile=excluded.profile, schedule=excluded.schedule, enabled=excluded.enabled,
                next_at=excluded.next_at''', (task_id, name.strip(), message, profile,
                                              json.dumps(schedule.serialize()), enabled, next_at))
        return task_id

    def set_enabled(self, task_id, enabled, now):
        with self._write() as db:
            task = self._task(db, task_id)
            if task['enabled'] == enabled:
                return
            schedule = Schedule.from_dict(json.loads(task['schedule']))
            next_at = schedule.next_after(now) if enabled else None
            if enabled and next_at is None:
                raise ValueError('Schedule has no future occurrence')
            db.execute('UPDATE schedules SET enabled=?, next_at=? WHERE id=?', (enabled, next_at, task_id))

    def tasks(self):
        with closing(self._connect()) as db:
            # The insertion slot stays with the task when its name or schedule changes.
            rows = db.execute('SELECT *, rowid - 1 AS color_index FROM schedules ORDER BY name, id').fetchall()
        return [{**dict(row), 'schedule': json.loads(row['schedule'])} for row in rows]

    def history(self, task_id, *, limit=50):
        with closing(self._connect()) as db:
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
                db.execute('UPDATE schedules SET enabled=?, next_at=? WHERE id=?',
                           (scheduled_at is not None, scheduled_at, task['id']))
        return claimed

    def claim_manual(self, task_id, now):
        with self._write() as db:
            task = self._task(db, task_id)
            if self._active(db, task_id):
                raise ValueError('Task already running')
            return self._insert_run(db, task, None, now, 'running')

    def set_session(self, run_id, session_id):
        with self._write() as db:
            db.execute("UPDATE runs SET session_id=? WHERE id=? AND state='running'", (session_id, run_id))

    def finish(self, run_id, state, now, *, detail=None):
        if state not in {'completed', 'failed', 'cancelled', 'interrupted'}:
            raise ValueError('Invalid terminal state')
        with self._write() as db:
            return bool(db.execute('''UPDATE runs SET state=?, finished_at=?, detail=?
                WHERE id=? AND state='running' ''', (state, now, detail, run_id)).rowcount)

    @staticmethod
    def _task(db, task_id):
        task = db.execute('SELECT * FROM schedules WHERE id=?', (task_id,)).fetchone()
        if task is None:
            raise KeyError(task_id)
        return task

    @staticmethod
    def _active(db, task_id):
        return db.execute("SELECT 1 FROM runs WHERE task_id=? AND state='running'", (task_id,)).fetchone()

    @staticmethod
    def _insert_run(db, task, scheduled_at, now, state):
        run_id = uuid4().hex
        snapshot = {key: task[key] for key in ('name', 'message', 'profile')}
        snapshot['schedule'] = json.loads(task['schedule'])
        detail = {'skipped': 'previous_run_active', 'missed': 'outside_dispatch_window'}.get(state)
        inserted = db.execute('''INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(task_id, scheduled_at) DO NOTHING''', (run_id, task['id'], scheduled_at, now,
            None if state == 'running' else now, state, json.dumps(snapshot, ensure_ascii=False), detail))
        if inserted.rowcount:
            return {'id': run_id, 'task_id': task['id'], 'scheduled_at': scheduled_at, 'snapshot': snapshot}
        return None
