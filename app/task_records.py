"""A local ledger for task attempts and references to Pi history and files."""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import uuid

SCHEMA = """
CREATE TABLE tasks (
    id TEXT PRIMARY KEY, objective TEXT NOT NULL, scope TEXT NOT NULL,
    project TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL
);
CREATE TABLE attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    cwd TEXT NOT NULL, session_id TEXT NOT NULL DEFAULT '', session_file TEXT NOT NULL DEFAULT '',
    started TEXT NOT NULL, ended TEXT, state TEXT NOT NULL DEFAULT 'running',
    reason TEXT NOT NULL DEFAULT '', accepted TEXT
);
CREATE INDEX task_attempts ON attempts(task_id, id DESC);
CREATE UNIQUE INDEX one_running_attempt ON attempts(task_id) WHERE state = 'running';
CREATE TABLE steps (
    attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    kind TEXT NOT NULL, key TEXT NOT NULL, detail TEXT NOT NULL,
    PRIMARY KEY (attempt_id, kind, key)
);
CREATE TABLE files (
    id INTEGER PRIMARY KEY, attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    source TEXT NOT NULL, event_id TEXT NOT NULL, path TEXT NOT NULL, version TEXT NOT NULL,
    recorded_state TEXT NOT NULL, checked TEXT, check_result TEXT,
    UNIQUE (attempt_id, source, event_id, path)
);
"""


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def file_version(path):
    try:
        target = Path(path).resolve(strict=True)
        info = target.stat()
    except (FileNotFoundError, NotADirectoryError):
        return "missing", ""
    except (OSError, ValueError, RuntimeError):
        return "unavailable", ""
    if not stat.S_ISREG(info.st_mode):
        return "unsupported", ""
    if not info.st_ino:
        return "unavailable", ""
    identity = (str(target), info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    return "available", hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def current_file_state(row):
    state, version = file_version(row["path"])
    if state == "available":
        if not row["version"]:
            return "unverified"
        if version != row["version"]:
            return "changed"
    return state


def current_session_state(session_id, session_file):
    if not session_id or not session_file:
        return "unavailable"
    try:
        path = Path(session_file)
        if not path.is_file():
            return "missing"
        with path.open("rb") as source:
            header = json.loads(source.readline(65536))
        if isinstance(header, dict) and header.get("type") == "session" and header.get("id") == session_id:
            return "available"
        return "changed"
    except FileNotFoundError:
        return "missing"
    except (OSError, ValueError):
        return "unavailable"


def versions_of(items):
    paths = dict.fromkeys(item.get("path") for item in items if isinstance(item, dict)
                          and item.get("kind") != "web" and isinstance(item.get("path"), str)
                          and Path(item["path"]).is_absolute())
    return [(path, *file_version(path)) for path in paths]


class TaskStore:
    def __init__(self, path):
        self.path = path
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        with self.connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + "\nPRAGMA user_version = 1;\nCOMMIT;")
            elif version not in (1, 2, 3):
                raise sqlite3.DatabaseError("Unsupported task record schema")
            if version < 2:
                # Historical rows stay undated. Never infer observation time from migration.
                db.execute("ALTER TABLE steps ADD COLUMN observed TEXT")
                db.execute("ALTER TABLE steps ADD COLUMN updated TEXT")
                db.execute("ALTER TABLE files ADD COLUMN observed TEXT")
                db.execute("PRAGMA user_version = 2")
            if version < 3:
                db.execute('''CREATE TABLE task_routes (
                    id TEXT PRIMARY KEY, request_key TEXT NOT NULL UNIQUE,
                    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
                    coordinator TEXT NOT NULL, status TEXT NOT NULL, updated TEXT NOT NULL, data TEXT NOT NULL)''')
                db.execute('CREATE INDEX task_route_history ON task_routes(task_id, updated DESC)')
                db.execute('CREATE INDEX coordinator_routes ON task_routes(coordinator, status)')
                db.execute("""CREATE INDEX active_task_routes ON task_routes(task_id,coordinator)
                    WHERE status = 'routing' OR status = 'accepted'
                    AND json_extract(data,'$.execution') IN ('queued','sending','running')""")
                db.execute('PRAGMA user_version = 3')

    @contextmanager
    def connection(self):
        with closing(sqlite3.connect(self.path, timeout=0.2)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            with db:
                yield db

    def create(self, objective, scope, project):
        task_id, now = uuid.uuid4().hex, timestamp()
        with self.connection() as db:
            db.execute("INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?)", (task_id, objective, scope, project, now, now))
        return task_id

    def tasks(self, offset=0, limit=-1):
        with self.connection() as db:
            return [dict(row) for row in db.execute("""
                SELECT tasks.*, COALESCE(CASE WHEN attempts.accepted IS NOT NULL THEN 'accepted'
                    ELSE attempts.state END, CASE WHEN EXISTS (
                    SELECT 1 FROM task_routes WHERE task_id = tasks.id AND status = 'accepted')
                    THEN 'routed' ELSE 'draft' END) AS state
                FROM tasks LEFT JOIN attempts ON attempts.id = (
                    SELECT id FROM attempts WHERE task_id = tasks.id ORDER BY id DESC LIMIT 1
                ) ORDER BY tasks.updated DESC, tasks.id LIMIT ? OFFSET ?
            """, (limit, offset))]

    def task(self, task_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return dict(row) if row else None

    def attempts(self, task_id, offset=0, limit=-1):
        with self.connection() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM attempts WHERE task_id = ? ORDER BY id DESC LIMIT ? OFFSET ?", (task_id, limit, offset))]

    def running(self, task_id):
        return self.chat_running(task_id) or bool(self.routes(task_id=task_id, active=True, limit=1))

    def chat_running(self, task_id):
        with self.connection() as db:
            return db.execute("SELECT 1 FROM attempts WHERE task_id = ? AND state = 'running'", (task_id,)).fetchone() is not None

    def details(self, task_id, attempt_id, offset=0, limit=-1, *, deliveries_only=False):
        with self.connection() as db:
            db.execute("BEGIN")
            attempt = db.execute("SELECT * FROM attempts WHERE task_id = ? AND id = ?", (task_id, attempt_id)).fetchone()
            if not attempt:
                return {}
            # Page one ordered event stream. Independently paging each table can
            # show a late delivery/end before the next page's earlier tool steps.
            sources = ["SELECT 'file' AS category, id AS row_id, observed AS time, 1 AS rank FROM files WHERE attempt_id = :attempt"
                       + (" AND source != 'input'" if deliveries_only else "")]
            if not deliveries_only:
                sources.extend((
                    "SELECT 'step', rowid, observed, 2 FROM steps WHERE attempt_id = :attempt",
                    "SELECT 'start', 0, :started, 0",
                    "SELECT 'end', 0, :ended, 3 WHERE :ended IS NOT NULL"))
            sources.append("SELECT 'accepted', 0, :accepted, 4 WHERE :accepted IS NOT NULL")
            events = db.execute("SELECT * FROM (" + " UNION ALL ".join(sources) + ") "
                "ORDER BY time IS NULL OR time = '', time, rank, row_id LIMIT :limit OFFSET :offset",
                {"attempt": attempt_id, "started": attempt['started'], "ended": attempt['ended'],
                 "accepted": attempt['accepted'], "limit": limit + 1 if limit >= 0 else -1, "offset": offset}).fetchall()
            has_more = limit >= 0 and len(events) > limit
            if limit >= 0:
                events = events[:limit]
            steps, files, timeline_keys = [], [], []
            for event in events:
                if event['category'] == 'step':
                    row = dict(db.execute('SELECT * FROM steps WHERE rowid = ?', (event['row_id'],)).fetchone())
                    steps.append(row)
                    timeline_keys.append(row['kind'] + '-' + row['key'])
                elif event['category'] == 'file':
                    row = dict(db.execute('SELECT * FROM files WHERE id = ?', (event['row_id'],)).fetchone())
                    files.append(row)
                    timeline_keys.append('file-' + str(row['id']))
                else:
                    timeline_keys.append(event['category'])
            has_deliveries = db.execute("SELECT 1 FROM files WHERE attempt_id = ? AND source != 'input' LIMIT 1",
                                        (attempt_id,)).fetchone() is not None
        for step in steps:
            if step["kind"] == "session":
                step["state"] = current_session_state(step["key"], step["detail"])
        return {**dict(attempt), "session_state": current_session_state(attempt["session_id"], attempt["session_file"]),
                "hasMore": has_more, "timelineKeys": timeline_keys, "hasDeliveries": has_deliveries,
                "steps": steps, "files": [{**row, "state": current_file_state(row)} for row in files]}

    def recover(self, reason):
        now = timestamp()
        with self.connection() as db:
            db.execute("UPDATE tasks SET updated = ? WHERE id IN (SELECT task_id FROM attempts WHERE state = 'running')", (now,))
            db.execute("UPDATE attempts SET state = 'pending', reason = ?, ended = ? WHERE state = 'running'", (reason, now))
            for saved in db.execute("""SELECT data FROM task_routes WHERE status = 'routing' OR
                    status = 'accepted' AND json_extract(data,'$.execution') IN ('queued','sending','running')""").fetchall():
                row = json.loads(saved[0])
                if row['status'] == 'routing':
                    row.update(status='interrupted', reason=reason + '；未自动重新路由')
                elif row['execution'] in ('queued', 'sending', 'running'):
                    row.update(execution='interrupted', result=reason + '；请检查执行会话，未自动重发')
                else:
                    continue
                self._save_route(db, row)

    def route(self, identifier='', *, request_key=''):
        with self.connection() as db:
            row = db.execute('SELECT data FROM task_routes WHERE ' +
                             ('request_key = ?' if request_key else 'id = ?'),
                             (request_key or identifier,)).fetchone()
            return json.loads(row[0]) if row else None

    def routes(self, *, task_id='', coordinator='', active=False, offset=0, limit=50):
        clauses, values = [], []
        for name, value in (('task_id', task_id), ('coordinator', coordinator)):
            if value:
                clauses.append(name + ' = ?')
                values.append(value)
        if active:
            clauses.append("(status = 'routing' OR status = 'accepted' AND json_extract(data,'$.execution') IN ('queued','sending','running'))")
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        with self.connection() as db:
            return [json.loads(row[0]) for row in db.execute(
                'SELECT data FROM task_routes' + where + ' ORDER BY updated DESC,id LIMIT ? OFFSET ?',
                (*values, limit, offset))]

    @staticmethod
    def _save_route(db, row):
        row['updated'] = timestamp()
        task_id = row.get('taskId') or None
        if task_id and not db.execute('SELECT 1 FROM tasks WHERE id = ?', (task_id,)).fetchone():
            task_id = None  # Retain the historical ID in JSON for durable deduplication.
        db.execute('''INSERT INTO task_routes VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET task_id=excluded.task_id,status=excluded.status,
            updated=excluded.updated,data=excluded.data''', (row['id'], row['requestKey'], task_id,
            row['coordinator'], row['status'], row['updated'], json.dumps(row, ensure_ascii=False)))
        if task_id:
            db.execute('UPDATE tasks SET updated = ? WHERE id = ?', (row['updated'], task_id))

    def save_route(self, row):
        with self.connection() as db:
            self._save_route(db, row)

    def accept_route(self, row, task_id=''):
        with self.connection() as db:
            if not task_id:
                task_id, now = uuid.uuid4().hex, timestamp()
                db.execute('INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?)',
                           (task_id, row['objective'], row['scope'], row['cwd'], now, now))
            row.update(taskId=task_id, status='accepted', execution='queued')
            self._save_route(db, row)

    def revise_scope(self, task_id, scope):
        with self.connection() as db:
            db.execute('UPDATE tasks SET scope = ?,updated = ? WHERE id = ?', (scope, timestamp(), task_id))

    def begin(self, task_id, cwd, session_id, session_file, inputs):
        now = timestamp()
        with self.connection() as db:
            attempt_id = db.execute("""
                INSERT INTO attempts (task_id, cwd, session_id, session_file, started)
                VALUES (?, ?, ?, ?, ?)
            """, (task_id, cwd, session_id, session_file, now)).lastrowid
            if session_id and session_file:
                self._step(db, attempt_id, "session", session_id, session_file)
            self._files(db, attempt_id, "input", "prompt", inputs)
            self._touch(db, attempt_id, now)
        return attempt_id

    def session(self, attempt_id, cwd, session_id, session_file):
        with self.connection() as db:
            db.execute("""
                UPDATE attempts SET cwd = ?, session_file = CASE
                    WHEN session_id = ? AND ? = '' THEN session_file ELSE ? END,
                    session_id = ? WHERE id = ? AND state = 'running'
            """, (cwd, session_id, session_file, session_file, session_id, attempt_id))
            if session_file:
                self._step(db, attempt_id, "session", session_id, session_file)

    def step(self, attempt_id, kind, key, detail):
        with self.connection() as db:
            self._step(db, attempt_id, kind, key, detail)
            self._touch(db, attempt_id, timestamp())

    @staticmethod
    def _step(db, attempt_id, kind, key, detail):
        db.execute("""
            INSERT INTO steps (attempt_id, kind, key, detail, observed, updated) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (attempt_id, kind, key) DO UPDATE SET detail = excluded.detail, updated = excluded.updated
        """, (attempt_id, kind, key, detail, timestamp(), timestamp()))

    def files(self, attempt_id, source, event_id, versions, failed=0):
        with self.connection() as db:
            self._files(db, attempt_id, source, event_id, versions)
            if failed:
                self._step(db, attempt_id, "delivery_error", event_id, str(failed))
            self._touch(db, attempt_id, timestamp())

    @staticmethod
    def _files(db, attempt_id, source, event_id, versions):
        db.executemany("""
            INSERT INTO files (attempt_id, source, event_id, path, version, recorded_state, observed)
            VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (attempt_id, source, event_id, path) DO NOTHING
        """, ((attempt_id, source, event_id, path, version, state, timestamp()) for path, state, version in versions))

    @staticmethod
    def _touch(db, attempt_id, now):
        db.execute("UPDATE tasks SET updated = ? WHERE id = (SELECT task_id FROM attempts WHERE id = ?)", (now, attempt_id))

    def finish(self, attempt_id, state, reason):
        now = timestamp()
        with self.connection() as db:
            if state == "finished" and db.execute("""
                SELECT 1 FROM steps WHERE attempt_id = ? AND kind = 'delivery_error'
            """, (attempt_id,)).fetchone():
                state, reason = "failed", "部分交付失败"
            db.execute("UPDATE attempts SET ended = ?, state = ?, reason = ? WHERE id = ? AND state = 'running'",
                       (now, state, reason, attempt_id))
            self._touch(db, attempt_id, now)

    def check_files(self, task_id, attempt_id):
        with self.connection() as db:
            files = [dict(row) for row in db.execute("""
                SELECT files.* FROM files JOIN attempts ON files.attempt_id = attempts.id
                WHERE task_id = ? AND attempt_id = ? AND source != 'input'
            """, (task_id, attempt_id))]
        return [{**row, "state": current_file_state(row)} for row in files]

    def save_checks(self, attempt_id, files):
        now = timestamp()
        with self.connection() as db:
            db.executemany("UPDATE files SET checked = ?, check_result = ? WHERE id = ? AND attempt_id = ? AND source != 'input'",
                           ((now, row["state"], row["id"], attempt_id) for row in files))
            self._touch(db, attempt_id, now)
        return now

    def accept(self, task_id, attempt_id):
        now = timestamp()
        with self.connection() as db:
            cursor = db.execute("""
                UPDATE attempts SET accepted = ?
                WHERE id = ? AND task_id = ? AND state = 'finished' AND accepted IS NULL
                    AND id = (SELECT MAX(id) FROM attempts WHERE task_id = ?)
            """, (now, attempt_id, task_id, task_id))
            if cursor.rowcount:
                self._touch(db, attempt_id, now)

    def delete(self, task_id):
        if self.routes(task_id=task_id, active=True, limit=1):
            return False
        with self.connection() as db:
            return bool(db.execute("""
                DELETE FROM tasks WHERE id = ? AND NOT EXISTS (
                    SELECT 1 FROM attempts WHERE task_id = ? AND state = 'running'
                )
            """, (task_id, task_id)).rowcount)
