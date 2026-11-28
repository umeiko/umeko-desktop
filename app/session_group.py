"""One group conversation for ordinary Pi sessions."""
from collections import OrderedDict, deque
from contextlib import closing, contextmanager
from contextvars import ContextVar
import json
import shutil
import sqlite3
import time
import uuid

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot

from .group_chat import GroupChat


_WRITE_METHODS = frozenset({
    'groupChatSend', 'groupChatPoke', 'groupChatClear',
    'groupChatAddMember', 'groupChatRenameMember', 'groupChatRemoveMember',
})
_LOCK_TIMEOUT = 1
_NONBLOCKING_WRITE = ContextVar('workspace_group_nonblocking_write', default=False)


def _database_busy(error):
    # Clear-history errors wrap the SQLite failure for display to the user.
    cause = error.__cause__ or error
    if not isinstance(cause, sqlite3.OperationalError):
        return False
    code = getattr(cause, 'sqlite_errorcode', None)
    return str(cause) == 'database is locked' if code is None else (code & 0xff) == sqlite3.SQLITE_BUSY


class WorkspaceGroupChat(GroupChat):
    def append(self, store, author, recipient, text, files=(), **options):
        name = self.bus.agents.get(author[6:], {}).get('name', '') if author.startswith('agent:') else ''
        return super().append(store, author, recipient, text, files, author_name=name,
                              exclusive=_NONBLOCKING_WRITE.get(), **options)

    def enqueue(self, member, message, chain):
        self.bus.enqueue(member['targetId'][6:], message, chain)

    def clear_history(self, store):
        result = super().clear_history(store, exclusive=_NONBLOCKING_WRITE.get())
        self.bus.outbox.clear()
        self.bus.turns.clear()
        self.bus.generation += 1
        return result


class SessionGroup(QObject):
    membersChanged = Signal()
    response = Signal(str, 'QVariantMap')

    def __init__(self, backend):
        super().__init__(backend)
        self.b = backend
        self.root = backend.store.directory / 'session-group'
        self.database = self.root / 'group.sqlite3'
        self.aliases = {}
        self.outbox = OrderedDict()
        self._ui_writes = deque()
        self.turns = {}
        self.reload_pending = set()
        self.generation = 0
        self.initialized = False
        self.team_board = self  # GroupChat uses the host for persistence and delivery.
        self.enabled = True
        self.chat = WorkspaceGroupChat(self)
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.drain)
        self.b._pool.event.connect(self.observe)
        if self.database.is_file():
            try:
                self.storage()
                with self.connection() as db:
                    self.aliases = dict(db.execute('SELECT session_id, alias FROM members').fetchall())
            except sqlite3.Error:
                pass  # Surface the unavailable database when the group is opened.

    @contextmanager
    def connection(self):
        timeout = 0 if _NONBLOCKING_WRITE.get() else _LOCK_TIMEOUT
        with closing(sqlite3.connect(self.database, timeout=timeout)) as db:
            db.row_factory = sqlite3.Row
            with db:
                yield db

    def storage(self):
        if not self.initialized:
            if not self.database.is_file():
                self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            with self.connection() as db:
                db.execute('CREATE TABLE IF NOT EXISTS global_chat_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, message TEXT NOT NULL)')
                db.execute('CREATE TABLE IF NOT EXISTS members (session_id TEXT PRIMARY KEY, alias TEXT NOT NULL)')
            self.initialized = True
        return self

    @staticmethod
    def text(args, name, maximum, required=True):
        value = args.get(name, '')
        if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
            raise ValueError(name + ' 无效或过长')
        return value.strip()

    @staticmethod
    def eligible(row):
        return bool(row.get('id') and row.get('file') and not row.get('cowork') and
                    not row.get('globalAgent') and row.get('backend', 'pi') in ('pi', ''))

    def sessions(self):
        meta = self.b.store.data['sessionMeta']
        terminal = {record.id for record in self.b._pool.records.values() if record.terminal_owned}
        return {row['id']: row for row in self.b._sessions if self.eligible(row)
                and row['id'] not in self.b._session_files.pending
                and row['id'] not in self.b._session_files.deleted
                and row['id'] not in terminal
                and not meta.get(row['id'], {}).get('pluginSession')}

    @property
    def agents(self):
        return {row['id']: {'name': row['name']} for row in self.memberRows}

    def changed(self, *, persist=False):
        pass  # History is refreshed through the shared group-chat request protocol.

    @Property('QVariantList', notify=membersChanged)
    def memberRows(self):
        sessions = self.sessions()
        return [{'id': sid, 'name': alias or sessions[sid]['title'], 'alias': alias}
                for sid, alias in self.aliases.items() if sid in sessions]

    @Property('QVariantList', notify=membersChanged)
    def candidates(self):
        return [dict(id=sid, name=row['title'], workspace=row.get('workspace', ''))
                for sid, row in self.sessions().items() if sid not in self.aliases]

    def active_for(self, record):
        return bool(record and record.id in self.aliases and not record.global_agent and not record.cowork
                    and not record.terminal_owned and not self.b.store.data['sessionMeta'].get(record.id, {}).get('pluginSession'))

    def runtime_config(self, record):
        if not self.active_for(record):
            return {}
        return {'sessionGroup': [{'id': 'agent:' + row['id'], 'name': row['name']}
                                 for row in self.memberRows if row['id'] != record.id]}

    def reload_member(self, identifier):
        record = self.b._pool.find(identifier)
        if not record or not record.process:
            return
        if self.b._pool.protected(record):
            record.stale = True
            self.reload_pending.add(record.key)
        else:
            self.b._pool.retire(record)
            if record is self.b._view:
                self.b._pi_warmup.start()

    def set_member(self, identifier, alias=None, *, remove=False):
        changed_membership = remove or identifier not in self.aliases
        self.storage()
        with self.connection() as db:
            if remove:
                db.execute('DELETE FROM members WHERE session_id=?', (identifier,))
            else:
                db.execute('INSERT OR REPLACE INTO members VALUES (?, ?)', (identifier, alias))
        if remove:
            self.aliases.pop(identifier, None)
            self.outbox = OrderedDict((key, item) for key, item in self.outbox.items()
                                      if item['target'] != identifier and item['message']['author'] != 'agent:' + identifier)
        else:
            self.aliases[identifier] = alias
        if changed_membership:
            self.reload_member(identifier)
        self.membersChanged.emit()

    def remove_deleted(self, identifiers):
        for identifier in self.aliases.keys() & identifiers:
            try:
                self.set_member(identifier, remove=True)
            except (OSError, sqlite3.Error):
                self.membersChanged.emit()

    @Slot()
    def refreshMembers(self):
        self.membersChanged.emit()

    @Slot(str, result='QVariantList')
    def attachments(self, raw):
        try:
            return self.chat.stage_files(json.loads(raw)) if raw else self.chat.paste_files()
        except (OSError, ValueError):
            return []

    @Slot(str, str, result=str)
    def call(self, method, raw):
        identifier = uuid.uuid4().hex
        write = method in _WRITE_METHODS
        deadline = None

        def respond(value):
            self.response.emit(identifier, value)

        def invoke():
            nonlocal deadline
            if self.b._closing:
                return
            if write and deadline is None:
                deadline = time.monotonic() + _LOCK_TIMEOUT
            token = _NONBLOCKING_WRITE.set(True) if write else None
            result = None
            try:
                args = json.loads(raw)
                if not isinstance(args, dict):
                    raise ValueError('无效的群聊参数')
                if method == 'groupChatSend' and args.get('files'):
                    # Avoid copying files into the archive on each retry.
                    with self.storage().connection() as db:
                        db.execute('BEGIN EXCLUSIVE')
                        db.rollback()
                value = self.handle(method, args, respond)
                if value is not None:
                    result = {'ok': True, 'result': value}
            except (OSError, ValueError, sqlite3.Error) as error:
                if write and _database_busy(error) and time.monotonic() < deadline:
                    QTimer.singleShot(25, self, invoke)
                    return
                result = {'ok': False, 'error': str(error)}
            finally:
                if token is not None:
                    _NONBLOCKING_WRITE.reset(token)
            if write:
                self._ui_writes.popleft()
                if self._ui_writes:
                    QTimer.singleShot(0, self, self._ui_writes[0])
            if result is not None:
                respond(result)

        if write:
            # Keep user writes ordered while the current request retries.
            self._ui_writes.append(invoke)
        if not write or len(self._ui_writes) == 1:
            QTimer.singleShot(0, self, invoke)
        return identifier

    def handle(self, method, args, respond):
        if method in ('groupChatAddMember', 'groupChatRenameMember', 'groupChatRemoveMember'):
            identifier = self.text(args, 'id', 128)
            if identifier not in self.sessions():
                raise ValueError('该会话不可加入群聊')
            adding = method == 'groupChatAddMember'
            if adding == (identifier in self.aliases):
                raise ValueError('群聊成员状态已变更')
            self.set_member(identifier, self.text(args, 'alias', 80, False),
                            remove=method == 'groupChatRemoveMember')
            return {'updated': True}
        if method == 'groupChatOpenFile':
            path = self.chat.attachment_path(self.storage(), args)
            info = self.b.chatboxFileInfo(str(path))
            if path.suffix.lower() == '.xlsx':
                return {'preview': {**info, 'kind': 'xlsx'}}
            if info.get('kind') in ('text', 'markdown', 'code'):
                return {'preview': info}
        return self.chat.handle(method, args, respond)

    def enqueue(self, identifier, message, chain):
        self.outbox[uuid.uuid4().hex] = {
            'target': identifier, 'message': message, 'chain': chain, 'groupChat': True,
            'expires': time.monotonic() + 300,
        }
        if not self.timer.isActive():
            self.timer.start()

    def drain(self):
        if self.b._closing:
            self.outbox.clear()
        sessions = self.sessions() if self.outbox else {}
        started_turn = False
        for key, item in list(self.outbox.items()):
            identifier = item['target']
            row = sessions.get(identifier)
            if identifier not in self.aliases or not row or item['expires'] <= time.monotonic():
                self.outbox.pop(key, None)
                continue
            record = self.b._pool.find(identifier)
            # Starting several Pi turns in one timer callback blocks the GUI.
            # Active turns can still receive steering while other turns wait.
            if started_turn and (record is None or not record.busy):
                continue
            if record and (record.approval or (record.busy and (not record.ready or record.stale))):
                continue
            if record is None:
                record = self.b._saved_pi_record(row, read_transcript=False)
                self.b._pool.touch(record, dirty=False)
            if not self.active_for(record):
                self.outbox.pop(key, None)
                continue
            if record.busy and (not record.process or record.cancelled or record.action not in ('prompt', 'widget-notify', 'resume-model', 'staged-continue')):
                continue
            message = item['message']
            data = {'source': 'user' if message['author'] == 'user' else 'agent', 'groupChat': True,
                    'author': message['author'], 'text': message['text'], 'sequence': message['id'],
                    'files': [{'name': file['name'], 'path': file['path']} for file in message['files']],
                    'members': self.runtime_config(record)['sessionGroup']}
            if 'quote' in message:
                data['quote'] = message['quote']
            update = {'id': key, 'widgetId': 'session-group', 'name': 'Workspace group chat',
                      'message': '(from group chat) Read the structured data. Post visible updates with submit_to_chatgroup. A poke is a brief steering signal.',
                      'data': data}
            if record.busy:
                self.b._pool.write(record, {'type': 'widget-notify', 'notification': update})
                accepted = True
            else:
                accepted = self.b._command_pi('widget-notify', record, notification=update)
                started_turn = accepted
            if accepted:
                self.outbox.pop(key, None)
                turn = self.turns.setdefault(record.key, {'chain': item['chain'], 'files': set()})
                turn['chain'] = item['chain']
                turn['files'].update(file['path'] for file in message['files'])
        if not self.outbox:
            self.timer.stop()

    def observe(self, record, event):
        if event.get('type') not in ('done', 'exit'):
            return
        self.turns.pop(record.key, None)
        if record.key not in self.reload_pending:
            return
        self.reload_pending.discard(record.key)
        if record.stale and not self.b._pool.protected(record):
            self.b._pool.retire(record)
        if record is self.b._view and not record.process and not self.b._pool.protected(record):
            self.b._pi_warmup.start()

    def report(self, record, args, reply=None):
        if not self.active_for(record):
            raise ValueError('此会话不在群聊中')
        message = self.text(args, 'text', 4000, False)
        recipient = self.text(args, 'recipient', 128, False) or 'user'
        items = args.get('items', [])
        if not isinstance(items, list) or len(items) > 8 or not (message or items):
            raise ValueError('请输入消息或添加最多 8 个文件')
        if recipient != 'user' and recipient not in {member['targetId'] for member in self.chat.members()}:
            raise ValueError('请选择用户或指定的群聊成员')
        author = 'agent:' + record.id
        if recipient == author:
            raise ValueError('请选择其他群聊成员')
        store = self.storage()
        generation = self.generation
        turn = self.turns.setdefault(record.key, {'chain': {'invited': {author}, 'forwarded': False}, 'files': set()})

        def post(files, folder):
            if generation != self.generation or not self.active_for(record) or (recipient != 'user' and recipient[6:] not in self.agents):
                if folder:
                    shutil.rmtree(folder, ignore_errors=True)
                raise ValueError('群聊成员已变更')
            row = self.chat.append_archived(store, author, recipient, message, files, folder)
            chain = turn['chain']
            forward = (recipient != 'user' and not chain['forwarded'] and recipient not in chain['invited']
                       and len(self.outbox) < 256 and self.turns.get(record.key) is turn)
            if forward:
                chain['forwarded'] = True
                chain['invited'].add(recipient)
                self.enqueue(recipient[6:], row, chain)
            return {'messageId': row['id'], 'deliveredToMember': forward}

        if not items:
            return post([], None)
        workspace, delivered = record.workspace, tuple(turn['files'])

        def archive():
            return self.chat.archive_files(self.chat.reply_sources(items, workspace, delivered))

        if reply is None:
            return post(*archive())

        def finish(result):
            try:
                if not result['ok']:
                    raise ValueError(str(result['value']))
                reply({'ok': True, **post(*result['value'])})
            except (OSError, ValueError, sqlite3.Error) as error:
                reply({'ok': False, 'error': str(error)})

        self.chat.start_job(archive, finish)
