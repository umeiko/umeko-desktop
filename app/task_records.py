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
            elif version not in (1, 2):
                raise sqlite3.DatabaseError("Unsupported task record schema")
            if version < 2:
                # Historical rows stay undated. Never infer observation time from migration.
                db.execute("ALTER TABLE steps ADD COLUMN observed TEXT")
                db.execute("ALTER TABLE steps ADD COLUMN updated TEXT")
                db.execute("ALTER TABLE files ADD COLUMN observed TEXT")
                db.execute("PRAGMA user_version = 2")

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
                    ELSE attempts.state END, 'draft') AS state
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
        with self.connection() as db:
            return db.execute("SELECT 1 FROM attempts WHERE task_id = ? AND state = 'running'", (task_id,)).fetchone() is not None

    def details(self, task_id, attempt_id, offset=0, limit=-1, *, deliveries_only=False):
        with self.connection() as db:
            db.execute("BEGIN")
            attempt = db.execute("SELECT * FROM attempts WHERE task_id = ? AND id = ?", (task_id, attempt_id)).fetchone()
            if not attempt:
                return {}
            steps = [dict(row) for row in db.execute(
                "SELECT * FROM steps WHERE attempt_id = ? ORDER BY rowid LIMIT ? OFFSET ?", (attempt_id, limit, offset))] if not deliveries_only else []
            files = [dict(row) for row in db.execute(
                "SELECT * FROM files WHERE attempt_id = ?" + (" AND source != 'input'" if deliveries_only else "") + " ORDER BY id LIMIT ? OFFSET ?", (attempt_id, limit, offset))]
            has_deliveries = db.execute("SELECT 1 FROM files WHERE attempt_id = ? AND source != 'input' LIMIT 1",
                                        (attempt_id,)).fetchone() is not None
        for step in steps:
            if step["kind"] == "session":
                step["state"] = current_session_state(step["key"], step["detail"])
        return {**dict(attempt), "session_state": current_session_state(attempt["session_id"], attempt["session_file"]),
                "hasDeliveries": has_deliveries, "steps": steps, "files": [{**row, "state": current_file_state(row)} for row in files]}

    def recover(self, reason):
        now = timestamp()
        with self.connection() as db:
            db.execute("UPDATE tasks SET updated = ? WHERE id IN (SELECT task_id FROM attempts WHERE state = 'running')", (now,))
            db.execute("UPDATE attempts SET state = 'pending', reason = ?, ended = ? WHERE state = 'running'", (reason, now))

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
        with self.connection() as db:
            return bool(db.execute("""
                DELETE FROM tasks WHERE id = ? AND NOT EXISTS (
                    SELECT 1 FROM attempts WHERE task_id = ? AND state = 'running'
                )
            """, (task_id, task_id)).rowcount)
