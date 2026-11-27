"""User-directed group conversations on the existing global-agent inbox."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from tempfile import NamedTemporaryFile, TemporaryDirectory
import uuid

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QDesktopServices, QImageReader


IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'}


def open_attachment(path):
    url = QUrl.fromLocalFile(str(path))
    if sys.platform != 'win32':
        return QDesktopServices.openUrl(url)
    # Ask the Windows URL association for the browser executable. Opening a
    # file: URL through the shell instead would use that file type's app.
    import ctypes
    from ctypes import wintypes

    query = ctypes.WinDLL('shlwapi').AssocQueryStringW
    query.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR,
                      wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    query.restype = ctypes.c_long
    assocf_is_protocol, assocstr_executable = 0x1000, 2
    buffer = ctypes.create_unicode_buffer(32768)
    length = wintypes.DWORD(len(buffer))
    if query(assocf_is_protocol, assocstr_executable, 'https', 'open', buffer, ctypes.byref(length)) != 0:
        return False
    browser = Path(buffer.value)
    if not browser.is_absolute() or browser.suffix.lower() != '.exe':
        return False
    subprocess.Popen([str(browser), bytes(url.toEncoded()).decode('ascii')])
    return True


class GroupChat(QObject):
    def __init__(self, bus):
        super().__init__(bus)
        self.bus = bus
        self.active = {}
        self.jobs = {}
        self.clipboard_directory = None
        if hasattr(bus.b, 'jobDone'):
            bus.b.jobDone.connect(self.job_finished)

    def handle(self, method, args, reply=None):
        if not self.bus.team_board.enabled:
            raise ValueError('请先在 Umeko Desktop 设置中开启团队协作')
        store = self.bus.team_board.storage()
        if method in ('groupChatHistory', 'groupChatSearch'):
            query = self.bus.text(args, 'query', 256) if method == 'groupChatSearch' else ''
            after, before = args.get('after', 0), args.get('before', 0)
            if reply is None:
                return self.history(store, after, before, query)
            self.start_job(lambda: self.history(store, after, before, query), lambda result: reply(
                {'ok': True, 'result': result['value']} if result['ok']
                else {'ok': False, 'error': str(result['value'])}))
            return None
        if method == 'groupChatClear':
            if args.get('confirmed') is not True:
                raise ValueError('请确认清空聊天记录')
            return self.clear_history(store)
        if method in ('groupChatOpenFile', 'groupChatCopyFile', 'groupChatRevealFile', 'groupChatSaveFile'):
            return self.file_action(store, method, args, reply)
        if method in ('groupChatSend', 'groupChatPoke'):
            return self.send(store, args, poke=method == 'groupChatPoke')
        raise ValueError('未知群聊操作')

    def members(self):
        return [{'targetId': 'agent:' + identifier, 'name': 'agent-' + identifier}
                for identifier in self.bus.agents]

    def start_job(self, work, finished):
        name = f'group-chat:{uuid.uuid4().hex}'
        self.jobs[name] = finished
        self.bus.b._job(name, work)

    def job_finished(self, name, result):
        finished = self.jobs.pop(name, None)
        if finished:
            finished(result)

    def history(self, store, after, before, query=''):
        if any(type(value) is not int or not 0 <= value < 2**63 for value in (after, before)):
            raise ValueError('群聊消息位置无效')
        conditions = 'id > ? AND (? = 0 OR id < ?)'
        parameters = (after, before, before)
        if query:
            conditions += " AND instr(lower(json_extract(message, '$.text')), lower(?)) > 0"
            parameters += (query,)
        with store.connection() as db:
            rows = db.execute(
                f'SELECT id, message FROM global_chat_messages WHERE {conditions} ORDER BY id DESC LIMIT 81',
                parameters).fetchall()
        return {'hasOlder': len(rows) > 80,
                'messages': [{'id': row['id'], **json.loads(row['message'])} for row in reversed(rows[:80])]}

    def clear_history(self, store):
        try:
            with store.connection() as db:
                db.execute('DELETE FROM global_chat_messages')
        except sqlite3.Error as error:
            raise ValueError('无法清空群聊记录') from error
        self.active.clear()
        self.bus.outbox = {key: item for key, item in self.bus.outbox.items() if 'groupChat' not in item}
        self.bus.changed(persist=False)
        return {'cleared': True}

    def append(self, store, author, recipient, text, files=(), *, poke=False, quote=None, author_name=''):
        message = {'author': author, 'recipient': recipient, 'text': text, 'files': list(files),
                   'poke': poke, 'created': datetime.now(timezone.utc).isoformat(timespec='seconds')}
        if quote is not None:
            message['quote'] = quote
        if author_name:
            message['authorName'] = author_name
        with store.connection() as db:
            cursor = db.execute('INSERT INTO global_chat_messages (message) VALUES (?)',
                                (json.dumps(message, ensure_ascii=False),))
            return {'id': cursor.lastrowid, **message}

    @property
    def files_root(self):
        return self.bus.root / 'group-chat-files'

    @staticmethod
    def local_url_path(value):
        url = QUrl(value) if isinstance(value, str) else QUrl()
        path = Path(url.toLocalFile())
        if not url.isLocalFile() or url.host() not in ('', 'localhost') or not path.is_absolute():
            raise ValueError('请选择本地文件')
        return path

    @classmethod
    def local_file(cls, value):
        source = cls.local_url_path(value).resolve(strict=True)
        if not source.is_file():
            raise ValueError('请选择本地文件')
        return source

    def stage_files(self, urls):
        if not isinstance(urls, list):
            return []
        items = []
        for value in urls:
            try:
                path = self.local_file(value)
            except (OSError, ValueError):
                continue
            url = QUrl.fromLocalFile(str(path)).toString()
            items.append({'id': url, 'url': url, 'name': path.name,
                          'kind': 'image' if path.suffix.lower() in IMAGE_SUFFIXES else 'file'})
            if len(items) == 8:
                break
        return items

    def clipboard_folder(self):
        if self.clipboard_directory is None:
            self.clipboard_directory = TemporaryDirectory(prefix='umeko-group-chat-clipboard-')
        return Path(self.clipboard_directory.name)

    def paste_files(self):
        items = []

        def accept(urls):
            items.extend(self.stage_files(urls))
            return bool(items)

        self.bus.b._paste_attachments(accept, self.clipboard_folder)
        return items

    def copy_files(self, files):
        return self.archive_files(self.local_file(value) for value in files)

    def archive_files(self, sources):
        files = list(sources)
        if not files:
            return [], None
        folder = self.files_root / uuid.uuid4().hex
        result = []
        try:
            for index, source in enumerate(files):
                destination = folder / str(index) / source.name
                destination.parent.mkdir(parents=True)
                shutil.copyfile(source, destination)
                item = {'name': source.name, 'path': str(destination), 'bytes': destination.stat().st_size}
                if source.suffix.lower() in IMAGE_SUFFIXES and item['bytes'] <= 20 * 1024 * 1024:
                    size = QImageReader(str(destination)).size()
                    if size.isValid() and 0 < size.width() * size.height() <= 40_000_000:
                        item.update(preview=QUrl.fromLocalFile(str(destination)).toString(),
                                    pixelWidth=size.width(), pixelHeight=size.height())
                result.append(item)
        except (OSError, ValueError):
            shutil.rmtree(folder, ignore_errors=True)
            raise
        return result, folder

    def read_message(self, store, message_id):
        if type(message_id) is not int or not 0 < message_id < 2**63:
            return None
        with store.connection() as db:
            row = db.execute('SELECT message FROM global_chat_messages WHERE id = ?',
                             (message_id,)).fetchone()
        return json.loads(row['message']) if row else None

    def attachment_path(self, store, args):
        message = self.read_message(store, args.get('messageId'))
        files = message['files'] if message else []
        index = args.get('index')
        if type(index) is not int or not 0 <= index < len(files):
            raise ValueError('附件不存在')
        path = Path(files[index]['path']).resolve()
        if not path.is_relative_to(self.files_root.resolve()) or not path.is_file():
            raise ValueError('附件不存在')
        return path

    def file_action(self, store, method, args, reply):
        path = self.attachment_path(store, args)
        if method == 'groupChatOpenFile':
            if not open_attachment(path):
                raise ValueError('无法打开附件')
            return {'opened': True}
        if method == 'groupChatCopyFile':
            self.bus.b.copyChatboxFile(str(path))
            return {'copied': True}
        if method == 'groupChatRevealFile':
            self.bus.b.openChatboxPath(str(path), True)
            return {'revealed': True}
        target = self.local_url_path(args.get('destination')).resolve()
        if target.is_relative_to(self.files_root.resolve()):
            raise ValueError('请选择群聊附件存档以外的位置')
        if reply is None:
            return self.save_copy(path, target)
        self.start_job(lambda: self.save_copy(path, target), lambda result: reply(
            {'ok': True, 'result': result['value']} if result['ok']
            else {'ok': False, 'error': str(result['value'])}))
        return None

    @staticmethod
    def save_copy(path, target):
        temporary = None
        try:
            with path.open('rb') as source, NamedTemporaryFile(dir=target.parent, delete=False) as output:
                temporary = Path(output.name)
                shutil.copyfileobj(source, output)
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return {'saved': True}

    def append_archived(self, store, author, recipient, text, files, folder, **options):
        try:
            return self.append(store, author, recipient, text, files, **options)
        except Exception:
            if folder is not None:
                shutil.rmtree(folder, ignore_errors=True)
            raise

    def send(self, store, args, *, poke):
        recipient = self.bus.text(args, 'recipient', 80)
        members = self.members()
        targets = members if recipient == 'all' and not poke else [
            member for member in members if member['targetId'] == recipient]
        if not targets:
            raise ValueError('请点名群聊成员或所有人')
        if len(self.bus.outbox) + len(targets) > 256:
            raise ValueError('智能体总线投递队列已满')
        text = 'user 拍了拍你' if poke else self.bus.text(args, 'text', 4000, False)
        quote_id = None if poke else args.get('quoteId')
        quote = None
        if quote_id is not None:
            original = self.read_message(store, quote_id)
            if not original or original['poke']:
                raise ValueError('引用的消息不存在')
            author = original['author']
            file_index = args.get('quoteFileIndex')
            quoted_files = original['files']
            if file_index is not None:
                if type(file_index) is not int or not 0 <= file_index < len(quoted_files):
                    raise ValueError('引用的附件不存在')
                quoted_files = [quoted_files[file_index]]
            quote = {'messageId': quote_id, 'author': author, 'text': original['text'] if file_index is None else '',
                     'authorName': self.bus.agents.get(author.removeprefix('agent:'), {}).get('name', ''),
                     'files': [{'name': file['name']} for file in quoted_files]}
            if file_index is not None:
                quote['fileIndex'] = file_index
        selected = [] if poke else args.get('files', [])
        if not isinstance(selected, list) or len(selected) > 8:
            raise ValueError('每条消息最多附加 8 个文件')
        files, folder = self.copy_files(selected)
        if not text and not files:
            raise ValueError('请输入消息或添加文件')
        message = self.append_archived(store, 'user', recipient, text, files, folder, poke=poke, quote=quote)
        chain = {'invited': {member['targetId'] for member in targets}, 'forwarded': False}
        for member in targets:
            self.enqueue(member, message, chain)
        self.bus.changed(persist=False)
        return {'message': message}

    def enqueue(self, member, message, chain):
        author = message['author']
        sender = self.bus.agents.get(author[6:], {}).get('name', 'user') if author.startswith('agent:') else 'user'
        aliases = [{'id': row['targetId'], 'name': self.bus.agents[row['targetId'][6:]]['name'],
                    'alias': row['name']} for row in self.members()]
        instruction = (
            '(from group chat) Read data.text and data.files. To post a visible reply, use '
            'reply_to_groupchat with text, local file items, or both, and one recipient (default user). Use the member id '
            'to address a teammate only when a handoff is needed. A reply to the user ends delivery. '
            'Only one reply per delivery. Use messageId (data.sequence) when answering an earlier '
            'message during the same turn. A poke is a brief user steering signal.'
        )
        if 'quote' in message:
            instruction += ' The user is replying to the earlier message in data.quote.'
        self.bus.enqueue_team_message(
            'global-group-chat', {'targetId': author, 'name': sender}, member,
            {'sequence': message['id'], 'kind': 'group_chat', 'text': message['text'], 'task': None},
            group_chat={'instruction': instruction, 'chain': chain, 'members': aliases,
                        'poke': message['poke'], 'quote': message.get('quote'),
                        'files': [{'name': file['name'], 'path': file['path']} for file in message['files']]})

    def delivered(self, record, item):
        if item['target'] == 'agent:' + record.global_agent:
            entries = self.active.setdefault(record.key, {})
            entries.setdefault(item['data']['sequence'], {
                'chain': item['groupChat']['chain'], 'replied': False,
                'files': [file['path'] for file in item['data']['files']]})

    def reply_sources(self, items, workspace, delivered_files):
        workspace = Path(workspace).resolve(strict=True)
        attached = set(delivered_files)
        for item in items:
            if not isinstance(item, dict) or set(item) != {'path'}:
                raise ValueError('每个群聊附件需要一个 path')
            raw = self.bus.text(item, 'path', 4096)
            if any(symbol in raw for symbol in ('\0', '\r', '\n')) or ('://' in raw and not raw.lower().startswith('file:')):
                raise ValueError('群聊附件只支持本地文件')
            path = self.local_url_path(raw) if raw.lower().startswith('file:') else workspace / raw
            source = path.resolve(strict=True)
            if not source.is_relative_to(workspace) and str(source) not in attached:
                raise ValueError('群聊附件必须来自当前工作目录或本轮收到的附件')
            if not source.is_file():
                raise ValueError('群聊只支持发送普通文件')
            yield source

    def reply(self, args, record, respond=None):
        entries = self.active.get(record.key) or {}
        message_id = args.get('messageId', next(reversed(entries), None))
        context = entries.get(message_id) if type(message_id) is int else None
        if not self.bus.team_board.enabled or not context or record.global_agent not in self.bus.agents:
            raise ValueError('只有收到群聊消息的当前轮次可以回复群聊')
        if context['replied'] or context.get('posting'):
            raise ValueError('这条群聊消息已经回复')
        if set(args) - {'text', 'recipient', 'messageId', 'items'}:
            raise ValueError('群聊回复只接受 text、recipient、messageId 和 items')
        text = self.bus.text(args, 'text', 4000, False)
        items = args.get('items', [])
        if not isinstance(items, list) or len(items) > 8:
            raise ValueError('每条消息最多附加 8 个文件')
        if not text and not items:
            raise ValueError('请输入消息或添加文件')
        target = self.bus.text(args, 'recipient', 80, False) or 'user'
        target = target.removeprefix('@')
        store = self.bus.team_board.storage()
        identity = 'agent:' + record.global_agent
        members = self.members()
        member = next((row for row in members if target in (row['targetId'], row['name'])
                       and row['targetId'] != identity), None)
        if target == 'user':
            member = None
        elif member is None:
            raise ValueError('群聊回复只能点名 user 或另一位群聊成员')
        recipient = member['targetId'] if member else 'user'

        def post(files, folder):
            if (not self.bus.team_board.enabled or record.global_agent not in self.bus.agents
                    or self.active.get(record.key, {}).get(message_id) is not context
                    or (member and recipient.removeprefix('agent:') not in self.bus.agents)):
                if folder is not None:
                    shutil.rmtree(folder, ignore_errors=True)
                raise ValueError('群聊回复已失效')
            message = self.append_archived(store, identity, recipient, text, files, folder)
            return self.finish_reply(context, message, member)

        if not items:
            return post([], None)

        workspace, delivered = record.workspace, tuple(context['files'])

        def archive():
            return self.archive_files(self.reply_sources(items, workspace, delivered))

        if respond is None:
            return post(*archive())

        def finish(result):
            context.pop('posting', None)
            if not result['ok']:
                respond({'ok': False, 'error': str(result['value'])})
                return
            try:
                outcome = post(*result['value'])
            except (OSError, ValueError, sqlite3.Error) as error:
                respond({'ok': False, 'error': str(error)})
            else:
                respond({'ok': True, **outcome})

        self.start_job(archive, finish)
        context['posting'] = True
        return None

    def finish_reply(self, context, message, member):
        context['replied'] = True
        recipient = message['recipient']
        chain = context['chain']
        forwarded = (member is not None and recipient not in chain['invited']
                     and not chain['forwarded'] and len(self.bus.outbox) < 256)
        if forwarded:
            chain['invited'].add(recipient)
            chain['forwarded'] = True
            self.enqueue(member, message, chain)
        self.bus.changed(persist=False)
        return {'messageId': message['id'], 'recipient': recipient, 'forwarded': forwarded}
