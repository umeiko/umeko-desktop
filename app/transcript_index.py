"""Disposable, incremental presentation index for Pi's append-only transcripts.

Only Pi writes the original JSONL. This index contains offsets, the selected
branch, and bounded display fragments. No live Qt objects enter the cache.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
import sqlite3
import sys
import threading
import zlib
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from .chat_model import ChatModel
from .message_attachments import split_attachments
from .transcripts import content_text, content_thinking, present

SCHEMA = 2
LARGE_FILE = 2 * 1024 * 1024
PAGE_ROWS = 24
GROUP_MESSAGES = 16
GROUP_BYTES = 512 * 1024
FRAGMENT_CHARS = 24000
CACHE_BYTES = 64 * 1024 * 1024


class Cancelled(Exception):
    pass


class StaleIndex(Exception):
    pass


def memory_weight(value, seen=None):
    seen = set() if seen is None else seen
    identity = id(value)
    if identity in seen:
        return 0
    seen.add(identity)
    size = sys.getsizeof(value)
    if isinstance(value, dict):
        size += sum(memory_weight(k, seen) + memory_weight(v, seen) for k, v in value.items())
    elif isinstance(value, (list, tuple)):
        size += sum(memory_weight(item, seen) for item in value)
    return size


class WeightedLRU:
    def __init__(self, limit=CACHE_BYTES):
        self.limit, self.weight = limit, 0
        self.items, self.pinned = OrderedDict(), set()
        self.lock = threading.RLock()

    def get(self, key):
        with self.lock:
            entry = self.items.get(key)
            if entry is not None:
                self.items.move_to_end(key)
                return entry[0]

    def put(self, key, value):
        weight = memory_weight(value)
        with self.lock:
            previous = self.items.pop(key, None)
            if previous:
                self.weight -= previous[1]
            # Oversized objects can be used by the caller without poisoning LRU.
            if weight <= self.limit:
                self.items[key] = value, weight
                self.weight += weight
            self._trim()
        return value

    def pin(self, keys):
        with self.lock:
            self.pinned = set(keys)
            self._trim()

    def discard(self, database):
        with self.lock:
            for key in list(self.items):
                if key[0] == database:
                    _, weight = self.items.pop(key)
                    self.weight -= weight
                    self.pinned.discard(key)

    def _trim(self):
        while self.weight > self.limit:
            key = next((key for key in self.items if key not in self.pinned), None)
            if key is None:
                break
            _, weight = self.items.pop(key)
            self.weight -= weight


def text_fragments(text, limit=FRAGMENT_CHARS, with_metadata=False):
    """Keep fences balanced and table headers available across large blocks."""
    if len(text) <= limit:
        yield (text, '', False) if with_metadata else text
        return
    pending, count, fence, table, previous = [], 0, '', (), ''
    fence_has_text = False
    copy_prefix, copy_join = '', False
    fence_pattern = re.compile(r'^ {0,3}(`{3,}|~{3,})([^\r\n]*)')
    separator = re.compile(r'^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)+\|?\s*$')
    for original in io.StringIO(text):
        # A single very long paragraph also has a finite rendering cost.
        for start in range(0, len(original), limit):
            line = original[start:start + limit]
            overhead = len(fence) + 1 if fence else sum(map(len, table))
            if count + len(line) > limit and pending and count > overhead:
                # Move an opening fence with its first code line, so a prose
                # preface never produces a separate empty code card.
                trailing_header = bool(fence and not fence_has_text)
                chunk = ''.join(pending[:-1] if trailing_header else pending)
                chunk += (('' if chunk.endswith('\n') else '\n') + fence.split(' ', 1)[0]) if fence and not trailing_header else ''
                yield (chunk, copy_prefix, copy_join) if with_metadata else chunk
                pending = [fence + '\n'] if fence else list(table)
                copy_prefix = ''.join(table) if not fence else ''
                copy_join = ''
                if not trailing_header and (fence or table or not previous.endswith('\n')):
                    copy_join = 'line' if previous.endswith('\n') else 'direct'
                count = sum(map(len, pending))
            match = fence_pattern.match(line)
            if match:
                marker = match[1]
                if not fence:
                    fence = marker + (' ' + match[2].strip() if match[2].strip() else '')
                    fence_has_text = False
                elif marker[0] == fence[0] and len(marker) >= len(fence.split(' ', 1)[0]) and not match[2].strip():
                    fence = ''
                else:
                    fence_has_text = True
            elif fence:
                fence_has_text = True
            if not fence:
                if separator.match(line) and '|' in previous:
                    table = (previous, line)
                elif not line.strip() or '|' not in line:
                    table = ()
            pending.append(line)
            count += len(line)
            previous = line
    if pending:
        chunk = ''.join(pending)
        yield (chunk, copy_prefix, copy_join) if with_metadata else chunk


def display_fragments(row):
    activity = row.get('activity', [])
    cost = sum(len(step.get('text', '')) + sum(len(tool.get('result', '')) for tool in step.get('tools', [])) for step in activity)
    if activity and cost <= FRAGMENT_CHARS and len(activity) <= 16 and all(len(step.get('tools', [])) <= 16 for step in activity):
        yield row
        return
    if not activity:
        text = row.get('text', '')
        user = row.get('role') == 'user'
        chunks = ((text[i:i + FRAGMENT_CHARS], '', 'direct' if i else '') for i in range(0, len(text), FRAGMENT_CHARS)) if user and len(text) > FRAGMENT_CHARS else text_fragments(text, with_metadata=True)
        for index, (fragment, prefix, join) in enumerate(chunks):
            value = {**row, 'text':fragment}
            if prefix or join:
                value.update(_copyPrefix=prefix, _copyJoin=join)
            if user and row.get('attachments') and (index + 1) * FRAGMENT_CHARS < len(text):
                value['attachments'] = []
            yield value
        return
    steps, weight = [], 0
    def fragment():
        result = {**row, 'activity': [{**step, 'blockOffset': i * 10000} for i, step in enumerate(steps)]}
        result['text'] = '\n\n'.join(step['text'] for step in steps if step['kind'] == 'text')
        result['thinking'] = '\n\n'.join(step['text'] for step in steps if step['kind'] == 'thinking')
        result['tools'] = [tool for step in steps if step['kind'] == 'tools' for tool in step['tools']]
        return result
    for step in activity:
        if step['kind'] in ('text', 'thinking'):
            pieces = ({**step, 'text': text, '_copyPrefix':prefix, '_copyJoin':join} for text, prefix, join in text_fragments(step.get('text', ''), with_metadata=True))
        elif step['kind'] == 'tools':
            pieces = ({**step, 'tools': step['tools'][i:i + 16]} for i in range(0, len(step['tools']), 16))
        else:
            pieces = iter([step])
        for piece in pieces:
            size = len(piece.get('text', '')) + sum(len(t.get('result', '')) for t in piece.get('tools', []))
            if steps and (weight + size > FRAGMENT_CHARS or len(steps) >= 16):
                yield fragment()
                steps, weight = [], 0
            steps.append(piece)
            weight += size
    if steps:
        yield fragment()


class Database(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect(path):
    db = sqlite3.connect(str(path), timeout=15, factory=Database)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=15000')
    db.execute('PRAGMA cache_size=-2048')
    return db


@dataclass(frozen=True)
class Snapshot:
    repository: object
    source: str
    database: str
    revision: int
    count: int
    native_count: int
    question_count: int
    leaf: str
    parsed_entries: int = 0
    size: int = 0
    mtime_ns: int = 0

    def matches_source(self):
        try:
            stat = Path(self.source).stat()
            return stat.st_size == self.size and stat.st_mtime_ns == self.mtime_ns
        except OSError:
            return False

    def key(self, row):
        return self.database, self.revision, row

    def cached(self, row):
        return self.repository.cache.get(self.key(row))

    def page(self, page):
        cached = {row:self.cached(row) for row in range(page * PAGE_ROWS, min(self.count, (page + 1) * PAGE_ROWS))}
        if all(value is not None for value in cached.values()):
            return cached
        with connect(self.database) as db:
            if int(db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]) != self.revision:
                raise StaleIndex('Transcript index has been refreshed')
            result = {}
            for row in db.execute('SELECT seq,body,logical,continuation,last FROM display WHERE seq>=? AND seq<?', (page * PAGE_ROWS, (page + 1) * PAGE_ROWS)):
                value = json.loads(zlib.decompress(row['body']))
                value.update(_logical=row['logical'], continuation=bool(row['continuation']), segmentLast=bool(row['last']))
                result[row['seq']] = value
                self.repository.cache.put(self.key(row['seq']), value)
        return result

    def row(self, row):
        return self.page(row // PAGE_ROWS).get(row, {})

    def metadata(self, row):
        with connect(self.database) as db:
            value = db.execute('SELECT role,hint,continuation FROM display WHERE seq=?', (row,)).fetchone()
            return dict(value) if value else {}

    def question(self, index):
        with connect(self.database) as db:
            value = db.execute('SELECT row,title FROM questions WHERE seq=?', (index,)).fetchone()
            return dict(value) if value else {}

    def question_index(self, row):
        with connect(self.database) as db:
            value = db.execute('SELECT seq FROM questions WHERE row<=? ORDER BY row DESC LIMIT 1', (row,)).fetchone()
            return value[0] if value else 0

    def contains(self, entry_id):
        with connect(self.database) as db:
            return bool(db.execute('SELECT 1 FROM native WHERE id=?', (entry_id,)).fetchone())

    def covered_ids(self, identifiers):
        identifiers = [value for value in identifiers if value]
        result = set()
        with connect(self.database) as db:
            for start in range(0, len(identifiers), 500):
                values = identifiers[start:start + 500]
                result.update(row[0] for row in db.execute('SELECT id FROM native WHERE id IN (' + ','.join('?' for _ in values) + ')', values))
        return result

    def copy_text(self, row):
        with connect(self.database) as db, Path(self.source).open('rb') as source:
            db.execute('BEGIN')
            if int(db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]) != self.revision:
                raise StaleIndex('聊天内容已更新，请重新复制')
            bounds = db.execute('''SELECT MIN(first_native),MAX(last_native) FROM display
                WHERE logical=(SELECT logical FROM display WHERE seq=?)''', (row,)).fetchone()
            if bounds[0] is None:
                return ''
            entries = db.execute('SELECT e.offset,e.length FROM native n JOIN entries e ON e.id=n.id WHERE n.pos>=? AND n.pos<=? ORDER BY n.pos', tuple(bounds))
            pieces, previous = [], ''
            for value in entries:
                source.seek(value['offset'])
                message = json.loads(source.read(value['length']))['message']
                text = content_text(message.get('content', ''))
                if message.get('role') == 'user':
                    text, attachments = split_attachments(text)
                    text = '\n'.join([text, *(item.get('name', '') for item in attachments)]).strip()
                if text:
                    if previous == 'length' and pieces:
                        pieces[-1] += text
                    else:
                        pieces.append(text)
                previous = message.get('stopReason', '')
            return '\n\n'.join(pieces)


class TranscriptRepository:
    def __init__(self, directory, cache_bytes=CACHE_BYTES):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.cache = WeightedLRU(cache_bytes)
        self._locks, self._lock = {}, threading.Lock()

    @staticmethod
    def large(file):
        try:
            return Path(file).stat().st_size >= LARGE_FILE
        except OSError:
            return False

    def open(self, file, leaf=None, cancelled=lambda: False, focus=-1):
        file = Path(file).resolve()
        key = hashlib.sha256(str(file).encode()).hexdigest()
        database = self.directory / (key + '.sqlite')
        with self._lock:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            snapshot = self._build(file, database, leaf, cancelled)
        # Warm the requested page before handing the model to the UI thread.
        if snapshot.count:
            target = min(snapshot.count - 1, focus) if focus >= 0 else snapshot.count - 1
            snapshot.page(target // PAGE_ROWS)
        return snapshot

    def discard(self, file):
        """Remove only derived data after its original session is deleted."""
        key = hashlib.sha256(str(Path(file).resolve()).encode()).hexdigest()
        database = self.directory / (key + '.sqlite')
        with self._lock:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            self.cache.discard(str(database))
            for suffix in ('', '-wal', '-shm'):
                Path(str(database) + suffix).unlink(missing_ok=True)

    def _build(self, file, database, target_leaf, cancelled):
        db = connect(database)
        try:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
                CREATE TABLE IF NOT EXISTS entries(num INTEGER PRIMARY KEY,id TEXT UNIQUE,parent TEXT,offset INTEGER,length INTEGER,kind TEXT,role TEXT,tool TEXT,omitted TEXT,eligible INTEGER,tools INTEGER,stop TEXT,error INTEGER,title TEXT);
                CREATE INDEX IF NOT EXISTS entries_tool ON entries(tool);
                CREATE TABLE IF NOT EXISTS branch(id TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS native(pos INTEGER PRIMARY KEY,id TEXT UNIQUE);
                CREATE TABLE IF NOT EXISTS display(seq INTEGER PRIMARY KEY,first_native INTEGER,last_native INTEGER,role TEXT,hint REAL,body BLOB,logical TEXT,continuation INTEGER,last INTEGER);
                CREATE INDEX IF NOT EXISTS display_logical ON display(logical);
                CREATE TABLE IF NOT EXISTS questions(seq INTEGER PRIMARY KEY,row INTEGER,title TEXT);
                CREATE INDEX IF NOT EXISTS questions_row ON questions(row);
            ''')
            meta = dict(db.execute('SELECT key,value FROM meta'))
            previous_revision = int(meta.get('revision', 0))
            stat = file.stat()
            signature = str(getattr(stat, 'st_ino', 0))
            offset = int(meta.get('offset', 0))
            reset = meta.get('schema') != str(SCHEMA) or meta.get('identity') != signature or stat.st_size < offset
            with file.open('rb') as source:
                if offset and not reset:
                    source.seek(max(0, offset - 4096))
                    reset = hashlib.sha256(source.read(min(offset, 4096))).hexdigest() != meta.get('tail')
                    if stat.st_size == int(meta.get('size', -1)) and str(stat.st_mtime_ns) != meta.get('mtime'):
                        reset = True
                if reset:
                    for table in ('entries', 'native', 'branch', 'display', 'questions', 'meta'):
                        db.execute('DELETE FROM ' + table)
                    meta, offset = {}, 0
                source.seek(offset)
                parsed, latest, cwd = 0, meta.get('latest', ''), meta.get('cwd', str(file.parent))
                subagent_owners = set()
                while True:
                    if cancelled():
                        raise Cancelled()
                    at = source.tell()
                    line = source.readline()
                    if not line:
                        break
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        # Retry a partial append the next time the file changes.
                        if not line.endswith(b'\n'):
                            source.seek(at)
                            break
                        continue
                    parsed += 1
                    if entry.get('type') == 'session':
                        cwd = entry.get('cwd') or cwd
                    elif entry.get('id'):
                        message = entry.get('message') or {}
                        content = message.get('content', '')
                        role = message.get('role', '')
                        text, thinking = content_text(content), content_thinking(content)
                        text = text or ('' if message.get('stopReason') == 'aborted' else message.get('errorMessage', ''))
                        tools = any(isinstance(c, dict) and c.get('type') == 'toolCall' for c in content) if isinstance(content, list) else False
                        title = ''
                        if role == 'user':
                            title, attachments = split_attachments(text)
                            title = re.sub(r'\s+', ' ', title.strip()[:500]) or '、'.join(a.get('name', '') for a in attachments) or '…'
                        data = entry.get('data') or {}
                        tool = message.get('toolCallId', '') if role == 'toolResult' else data.get('toolCallId', '') if entry.get('customType') in ('umeko-chatbox', 'umeko-subagent', 'umeko-subagent-link') and isinstance(data, dict) else ''
                        if entry.get('customType') == 'umeko-subagent' and isinstance(data, dict) and data.get('ownerEntryId'):
                            subagent_owners.add(data['ownerEntryId'])
                        omitted = entry.get('targetId', '') if entry.get('type') == 'context_edit' and entry.get('replacement') is None else ''
                        db.execute('INSERT OR REPLACE INTO entries(id,parent,offset,length,kind,role,tool,omitted,eligible,tools,stop,error,title) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                   (entry['id'], entry.get('parentId'), at, len(line), entry.get('type', ''), role, tool, omitted, int(role in ('user', 'assistant') and bool(text or thinking or tools)), int(tools), message.get('stopReason', ''), int(bool(message.get('errorMessage'))), title))
                        latest = entry['id']
                offset = source.tell()
                source.seek(max(0, offset - 4096))
                tail = hashlib.sha256(source.read(min(offset, 4096))).hexdigest()
            stat = file.stat()
            leaf = target_leaf or latest
            if meta and not parsed and meta.get('leaf') == leaf:
                return self._snapshot(file, database, meta, 0)
            old_leaf = meta.get('leaf')
            append = False
            if old_leaf and not reset:
                append = bool(db.execute('''WITH RECURSIVE path(id) AS (
                    SELECT ? UNION SELECT e.parent FROM entries e JOIN path p ON e.id=p.id WHERE e.id!=? AND e.parent IS NOT NULL)
                    SELECT 1 FROM path WHERE id=?''', (leaf, old_leaf, old_leaf)).fetchone())
            if append:
                new = list(db.execute('''WITH RECURSIVE path(id) AS (
                    SELECT ? UNION SELECT e.parent FROM entries e JOIN path p ON e.id=p.id WHERE e.id!=? AND e.parent IS NOT NULL)
                    SELECT e.id,e.omitted FROM entries e JOIN path p ON p.id=e.id WHERE e.id!=? ORDER BY e.num''', (leaf, old_leaf, old_leaf)))
                if any(row['omitted'] for row in new):
                    append = False
            if append:
                db.executemany('INSERT OR IGNORE INTO branch(id) VALUES(?)', ((row['id'],) for row in new))
                old_count = int(meta.get('native_count', 0))
                for first in range(0, len(new), 500):
                    identifiers = [row['id'] for row in new[first:first + 500]]
                    additions = db.execute('SELECT e.id FROM entries e LEFT JOIN native n ON n.id=e.id WHERE e.eligible=1 AND n.id IS NULL AND e.id IN (' + ','.join('?' for _ in identifiers) + ') ORDER BY e.num', identifiers).fetchall()
                    db.executemany('INSERT INTO native(pos,id) VALUES(?,?)', ((old_count + i, row[0]) for i, row in enumerate(additions)))
                    old_count += len(additions)
                last = db.execute('SELECT first_native FROM display ORDER BY seq DESC LIMIT 1').fetchone()
                rebuild = last[0] if last else 0
                # Rebuild every fragment of the last bounded message group.
                value = db.execute('SELECT MIN(first_native) FROM display WHERE last_native>=?', (rebuild,)).fetchone()[0]
                rebuild = value if value is not None else rebuild
                # Background completions and resumed children update their original
                # launch row, which may precede the most recent message group.
                for owner in subagent_owners:
                    native = db.execute('SELECT pos FROM native WHERE id=?', (owner,)).fetchone()
                    if native:
                        value = db.execute('SELECT MIN(first_native) FROM display WHERE last_native>=?', (native[0],)).fetchone()[0]
                        if value is not None:
                            rebuild = min(rebuild, value)
            else:
                db.execute('DELETE FROM branch')
                db.execute('''WITH RECURSIVE path(id) AS (
                    SELECT ? UNION SELECT e.parent FROM entries e JOIN path p ON e.id=p.id WHERE e.parent IS NOT NULL)
                    INSERT INTO branch SELECT e.id FROM entries e JOIN path p ON e.id=p.id''', (leaf,))
                db.execute('DELETE FROM native')
                cursor = db.execute('''SELECT e.id FROM entries e JOIN branch b ON e.id=b.id WHERE e.eligible=1
                    AND NOT(e.stop='error' AND EXISTS(SELECT 1 FROM entries edit JOIN branch eb ON edit.id=eb.id WHERE edit.omitted=e.id)) ORDER BY e.num''')
                db.executemany('INSERT INTO native(pos,id) VALUES(?,?)', enumerate(row[0] for row in cursor))
                rebuild = 0
            db.execute('DELETE FROM display WHERE last_native>=?', (rebuild,))
            db.execute('DELETE FROM questions WHERE row >= (SELECT COUNT(*) FROM display)')
            self._project(db, file, cwd, rebuild, cancelled)
            count = db.execute('SELECT COUNT(*) FROM display').fetchone()[0]
            native_count = db.execute('SELECT COUNT(*) FROM native').fetchone()[0]
            question_count = db.execute('SELECT COUNT(*) FROM questions').fetchone()[0]
            values = {'schema': SCHEMA, 'identity': signature, 'offset': offset, 'size': stat.st_size, 'mtime': stat.st_mtime_ns,
                      'tail': tail, 'latest': latest, 'leaf': leaf, 'cwd': cwd, 'count': count, 'native_count': native_count,
                      'question_count': question_count, 'revision': previous_revision + 1}
            db.executemany('INSERT OR REPLACE INTO meta VALUES(?,?)', ((k, str(v)) for k, v in values.items()))
            db.commit()
            return self._snapshot(file, database, values, parsed)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _snapshot(self, file, database, meta, parsed):
        return Snapshot(self, str(file), str(database), int(meta['revision']), int(meta['count']), int(meta['native_count']), int(meta['question_count']), meta.get('leaf', ''), parsed, int(meta['size']), int(meta['mtime']))

    def _project(self, db, file, cwd, start, cancelled):
        seq = db.execute('SELECT COUNT(*) FROM display').fetchone()[0]
        question = db.execute('SELECT COUNT(*) FROM questions').fetchone()[0]
        previous = db.execute('SELECT logical,role FROM display ORDER BY seq DESC LIMIT 1').fetchone()
        logical = previous['logical'] if previous else ''
        previous_role = previous['role'] if previous else ''
        prior = db.execute('SELECT e.tools,e.stop FROM native n JOIN entries e ON e.id=n.id WHERE n.pos=?', (start - 1,)).fetchone()
        has_tools = bool(prior and prior['tools'])
        if prior and previous_role == 'assistant':
            has_tools = bool(db.execute('''SELECT MAX(e.tools) FROM native n JOIN entries e ON n.id=e.id
                WHERE n.pos>=(SELECT MIN(first_native) FROM display WHERE logical=?) AND n.pos<?''', (logical, start)).fetchone()[0])
        group, weight, first, last, stop = [], 0, start, start, prior['stop'] if prior else ''
        group_continuation = False
        def read(source, value):
            source.seek(value['offset'])
            return json.loads(source.read(value['length']))
        with file.open('rb') as source:
            def flush():
                nonlocal seq, question, group, weight
                if not group:
                    return
                calls = []
                for entry in group:
                    content = entry.get('message', {}).get('content', [])
                    if isinstance(content, list):
                        calls.extend(c['id'] for c in content if isinstance(c, dict) and c.get('type') == 'toolCall')
                dependencies = []
                for call in calls:
                    results = db.execute("SELECT e.offset,e.length FROM entries e JOIN branch b ON e.id=b.id WHERE e.tool=? AND e.role='toolResult' ORDER BY e.num", (call,))
                    dependencies.extend(read(source, value) for value in results)
                    prefix = call + '/'
                    deliveries = db.execute("SELECT e.offset,e.length FROM entries e JOIN branch b ON e.id=b.id WHERE ((e.tool>=? AND e.tool<?) OR e.tool=?) AND e.kind='custom' ORDER BY e.num", (prefix, prefix + chr(0x10ffff), call))
                    dependencies.extend(read(source, value) for value in deliveries)
                messages, _ = present(group + dependencies, cwd)
                for row in ChatModel.project(messages):
                    row_start = seq
                    for part, value in enumerate(display_fragments(row)):
                        chars = len(value.get('text', '')) + len(value.get('thinking', ''))
                        lines = value.get('text', '').count('\n') + value.get('thinking', '').count('\n')
                        hint = max(80, min(50000, 70 + max(lines, chars / 70) * 22))
                        continuation = group_continuation or part > 0
                        body = zlib.compress(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode(), 1)
                        db.execute('INSERT INTO display VALUES(?,?,?,?,?,?,?,?,?)', (seq, first, last, row['role'], hint, body, logical, int(continuation), 1))
                        if seq and continuation:
                            db.execute('UPDATE display SET last=0 WHERE seq=? AND logical=?', (seq - 1, logical))
                        seq += 1
                    if row['role'] == 'user':
                        title = re.sub(r'\s+', ' ', row.get('text', '').strip()[:500]) or '、'.join(a.get('name', '') for a in row.get('attachments', [])) or '…'
                        db.execute('INSERT INTO questions VALUES(?,?,?)', (question, row_start, title))
                        question += 1
                group, weight = [], 0
            cursor = db.execute('SELECT n.pos,e.* FROM native n JOIN entries e ON n.id=e.id WHERE n.pos>=? ORDER BY n.pos', (start,))
            for value in cursor:
                if cancelled():
                    raise Cancelled()
                merge = bool(previous_role == value['role'] == 'assistant' and (has_tools or value['tools'] or stop == 'length') and not value['error'])
                bounded = len(group) >= GROUP_MESSAGES or weight + value['length'] > GROUP_BYTES
                if group and (not merge or bounded):
                    flush()
                if not group:
                    first = value['pos']
                    group_continuation = merge
                    # Adjacent plain assistant replies remain distinct logical messages.
                    if not merge:
                        logical = value['id']
                group.append(read(source, value))
                weight += value['length']
                last = value['pos']
                previous_role, has_tools, stop = value['role'], bool(value['tools']) if not merge else has_tools or bool(value['tools']), value['stop']
            flush()
