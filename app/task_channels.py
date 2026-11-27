"""Task Channels scoped to host-assigned human coordinator turns and delivered requests.

Native Pi entries bind each child launch to an exact delivered request.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import uuid
import re
import time

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot



REQUEST_ID = re.compile(r'[a-f0-9]{32}')
NATIVE_ID = re.compile(r'[a-f0-9-]{8,64}')
CHANNEL_ACTION_SUMMARIES = {
    'revise': ('修改已有交付内容。', 'Revise an existing deliverable.'),
    'produce': ('新增一项交付内容。', 'Produce an additional deliverable.'),
    'check': ('执行一项检查。', 'Perform a check.'),
}
STATUSES = {'queued', 'running', 'completed', 'error', 'stopped', 'aborted', 'failed'}
ENTRY_LIMIT = 64_000_000
LINE_LIMIT = 4_000_000
ARTIFACT_LIMIT = 512_000
TEXT_ARTIFACTS = {'.txt', '.md', '.json'}


def dict_value(value):
    return value if isinstance(value, dict) else {}


def native_entries(path):
    """Read a bounded local JSONL snapshot on the worker, not on the GUI."""
    with path.open('rb') as handle:
        total = 0
        while raw := handle.readline(LINE_LIMIT + 1):
            total += len(raw)
            if total > ENTRY_LIMIT or len(raw) > LINE_LIMIT:
                raise ValueError('Channel 会话超出首版读取上限')
            if not raw.endswith(b'\n'):
                break  # Native Pi may still be writing the final entry.
            try:
                entry = json.loads(raw)
            except (ValueError, UnicodeError):
                continue
            if isinstance(entry, dict):
                yield entry


def local_file(raw, root):
    if not isinstance(raw, (str, Path)) or not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    try:
        resolved = path.resolve(strict=True)
        if resolved.is_relative_to(root) and not path.is_symlink() and resolved.is_file():
            return resolved
    except (OSError, RuntimeError, ValueError):
        pass
    return None


def path_digest(path):
    try:
        with path.open('rb') as handle:
            content = handle.read(ARTIFACT_LIMIT + 1)
        if len(content) <= ARTIFACT_LIMIT:
            return sha256(content).hexdigest()
    except OSError:
        pass
    return None


def widget_request(entry):
    details = dict_value(entry.get('details'))
    data = dict_value(details.get('data'))
    request, delivery = details.get('requestId'), details.get('widgetEventId')
    if (entry.get('customType') == 'umeko-widget-update' and details.get('widgetId') == 'global-agents'
            and isinstance(request, str) and REQUEST_ID.fullmatch(request)
            and isinstance(delivery, str) and REQUEST_ID.fullmatch(delivery)
            and data.get('bridgeRequestId') == request and not data.get('groupChat')
            and data.get('status') == 'queued'):
        return request, data.get('source'), data.get('target')
    return None


def assistant_calls(entry, name):
    message = dict_value(entry.get('message'))
    content = message.get('content')
    if entry.get('type') == 'message' and message.get('role') == 'assistant' and isinstance(content, list):
        return {block['id']: dict_value(block.get('arguments')) for block in content
                if isinstance(block, dict) and block.get('type') == 'toolCall'
                and block.get('name') == name and isinstance(block.get('id'), str)}
    return {}


def child_details(path, session_id, workspace):
    entries = native_entries(path)
    header = next(entries, {})
    if (header.get('type') != 'session' or header.get('parentSession') != session_id
            or not isinstance(header.get('id'), str) or not NATIVE_ID.fullmatch(header['id'])):
        return '', []
    try:
        cwd = Path(header['cwd']).resolve(strict=True)
        if cwd != workspace:
            return '', []
    except (KeyError, OSError, TypeError, RuntimeError, ValueError):
        return '', []

    pending, artifacts = {}, {}
    for entry in entries:
        for call_id, args in assistant_calls(entry, 'write').items():
            content = args.get('content')
            target = local_file(args.get('path'), workspace)
            if target is None or target.suffix.lower() not in TEXT_ARTIFACTS or not isinstance(content, str):
                continue
            if any(part.startswith('.') for part in target.relative_to(workspace).parts):
                continue
            content = content.encode('utf-8', errors='replace')
            if len(content) <= ARTIFACT_LIMIT:
                pending[call_id] = (target, sha256(content).hexdigest())
        message = dict_value(entry.get('message'))
        if entry.get('type') != 'message' or message.get('role') != 'toolResult':
            continue
        candidate = pending.pop(message.get('toolCallId'), None)
        if candidate is not None and message.get('toolName') == 'write' and message.get('isError') is False:
            target, digest = candidate
            if path_digest(target) == digest:
                artifact_id = sha256((header['id'] + '\0' + str(target)).encode()).hexdigest()[:24]
                artifacts[artifact_id] = {'id': artifact_id, 'name': target.name, 'path': str(target),
                                          'digest': digest}
    return header['id'], list(artifacts.values())[:12]



def child_message_time(message, entry):
    stamp = message.get('timestamp')
    if type(stamp) in (int, float) and 0 < stamp < 8_640_000_000_000_000:
        return int(stamp)
    try:
        native = datetime.fromisoformat(entry['timestamp'])
        if native.tzinfo is not None:
            return max(0, int(native.timestamp() * 1000))
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        pass
    return 0


def read_child_history(path, signature, parent_id, workspace):
    """Text-only view of the selected native Pi branch; never load media."""
    entries = native_entries(path)
    header = next(entries, {})
    if (header.get('type') != 'session' or header.get('id') != signature[2]
            or header.get('parentSession') != parent_id
            or Path(header.get('cwd', '')).resolve() != workspace):
        raise ValueError('原生子执行身份或目录已变化')
    rows = {}
    leaf = None
    for entry in entries:
        entry_id = entry.get('id')
        if not isinstance(entry_id, str):
            continue
        message = dict_value(entry.get('message'))
        role = message.get('role')
        row = None
        if entry.get('type') == 'message' and role in ('user', 'assistant'):
            content = message.get('content')
            text = content if isinstance(content, str) else ''
            if isinstance(content, list):
                text = '\n'.join(block['text'] for block in content if isinstance(block, dict)
                                 and block.get('type') == 'text' and isinstance(block.get('text'), str))
            if text:
                row = {'role': role, 'text': text[:12000], 'time': child_message_time(message, entry)}
        rows[entry_id] = (entry.get('parentId'), row)
        leaf = entry_id
    messages, visited = [], set()
    while isinstance(leaf, str) and leaf not in visited and leaf in rows and len(messages) < 200:
        visited.add(leaf)
        leaf, row = rows[leaf]
        if row is not None:
            messages.append(row)
    return list(reversed(messages))

def project_request(parent, identity, workspace):
    """Only link launches whose structured owner belongs to this request.

    The native history is a tree. A sibling fork or next user/widget turn does
    not inherit a request merely because it follows one on disk. Background
    follow-up turns without an explicit request link are not claimed here.
    """
    entries = native_entries(parent)
    header = next(entries, {})
    session_id = identity[2].removeprefix('session:')
    if header.get('type') != 'session' or header.get('id') != session_id:
        raise ValueError('原生会话身份已变化')
    if Path(header.get('cwd', '')).resolve() != workspace:
        raise ValueError('原生会话工作目录已变化')

    branches, owners, references, native_records = {}, {}, [], {}
    objective = ''
    for entry in entries:
        entry_id = entry.get('id')
        if not isinstance(entry_id, str):
            continue
        if entry_id in branches:
            raise ValueError('原生会话记录含重复身份')
        parent_id = entry.get('parentId')
        belongs = isinstance(parent_id, str) and branches.get(parent_id, False)
        kind = entry.get('type')
        if kind == 'custom_message':
            if widget_request(entry) == identity:
                belongs = True
                objective = str(dict_value(dict_value(entry.get('details')).get('data')).get('task', ''))[:8000]
            else:
                belongs = False
        if kind == 'message':
            message = dict_value(entry.get('message'))
            if message.get('role') == 'user':
                belongs = False
            elif belongs and message.get('role') == 'assistant':
                calls = assistant_calls(entry, 'subagent')
                if calls:
                    owners[entry_id] = set(calls)
                if message.get('stopReason') != 'toolUse':
                    belongs = False
        branches[entry_id] = belongs
        if kind != 'custom':
            continue
        data = dict_value(entry.get('data'))
        if entry.get('customType') == 'umeko-subagent' and data.get('version') == 1:
            references.append(data)
        if entry.get('customType') == 'subagents:record' and isinstance(data.get('id'), str):
            if data.get('outputFile'):
                native_records[data['id']] = data['outputFile']

    children = {}
    for data in references:
        owner, call = data.get('ownerEntryId'), data.get('toolCallId')
        if not isinstance(owner, str) or not isinstance(call, str) or call not in owners.get(owner, ()):
            continue
        tool = dict_value(data.get('tool'))
        row = dict_value(tool.get('subagent'))
        child_id = row.get('id')
        if tool.get('name') == 'subagent' and isinstance(child_id, str) and tool.get('id') == 'subagent:' + child_id:
            children[child_id] = row

    tasks = {}
    child_root = parent.parent / parent.stem / 'tasks'
    # The package's native child directory is derived from this exact parent.
    if child_root.resolve() != child_root:
        raise ValueError('原生子执行目录不可验证')
    for child_id, row in list(children.items())[:100]:
        reported = row.get('outputFile')
        persisted = native_records.get(child_id)
        path = local_file(persisted, child_root)
        if reported and local_file(reported, child_root) != path:
            path = None
        child_session, artifacts = '', []
        if path is not None and path.suffix == '.jsonl':
            try:
                child_session, artifacts = child_details(path, session_id, workspace)
            except (OSError, ValueError):
                pass
        status = row.get('status', '')
        tasks[child_id] = {
            'id': child_id, 'title': str(row.get('task') or '子任务')[:2000],
            'role': str(row.get('profileName') or row.get('type') or '子智能体')[:100],
            'status': status if status in STATUSES else 'unavailable',
            'summary': str(row.get('result') or row.get('error') or '')[:1000],
            'time': row.get('completedAt') or row.get('startedAt'),
            'artifactCount': len(artifacts), 'artifacts': artifacts, 'ready': bool(child_session),
            'path': str(path) if child_session else '', 'sessionId': child_session,
        }
    return objective, tasks


class TaskChannels(QObject):
    changed = Signal()
    loaded = Signal(object)
    historyLoaded = Signal(object)
    reworkScanned = Signal(object)

    def __init__(self, backend):
        super().__init__(backend)
        self.b, self.store = backend, backend.store
        records = self.store.data.get('taskChannels', [])
        self._channels = {}
        if isinstance(records, list):
            for row in records[:64]:
                if (isinstance(row, dict) and isinstance(row.get('id'), str) and REQUEST_ID.fullmatch(row['id'])
                        and isinstance(row.get('coordinator'), str) and REQUEST_ID.fullmatch(row['coordinator'])
                        and isinstance(row.get('requests'), list)):
                    row = dict(row, requests=[dict(r) for r in row['requests'][:32] if self._valid_request(r)])
                    row.pop('privatePending', None)
                    if token := row.pop('reworkPending', None):
                        row['reworkInterrupted'] = True
                        for update in row.get('syncUpdates', []):
                            if update.get('updateId') == token:
                                update['status'] = 'interrupted'
                    if row.get('phase') == 'running':
                        row['phase'] = 'interrupted'
                    for request in row['requests']:
                        if request.get('status') not in ('completed', 'failed', 'cancelled', 'interrupted'):
                            request['status'] = 'interrupted'
                    self._channels[row['id']] = row
        self._tokens = {}
        self._rework = {}
        self._availability = None
        backend._pool.event.connect(self.observe_child)
        self.reworkScanned.connect(self._rework_scanned)
        self._selected = next(iter(self._channels), '')
        self._task_id, self._error, self._execution_error = '', '', ''
        self._loading = self._execution_loading = self._busy = self._closed = False
        self._visible = False
        self._generation = self._execution_generation = 0
        self._signature = None
        self._execution_signature = None
        self._tasks = {}
        self._scanned = set()
        self._messages = []
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='channel-projection')
        self._history_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='channel-execution')
        self.loaded.connect(self._loaded)
        self.historyLoaded.connect(self._history_loaded)
        self._timer = QTimer(self, interval=1200)
        self._timer.timeout.connect(self.refresh)

    @staticmethod
    def _valid_request(row):
        return (isinstance(row, dict) and isinstance(row.get('id'), str) and REQUEST_ID.fullmatch(row['id'])
                and isinstance(row.get('source'), str) and row['source'].startswith('agent:')
                and REQUEST_ID.fullmatch(row['source'][6:])
                and isinstance(row.get('target'), str) and row['target'].startswith('session:')
                and NATIVE_ID.fullmatch(row['target'][8:]))

    @property
    def bus(self):
        return self.b.desktopPlugins.global_agents

    def _persist(self):
        self.store.data['taskChannels'] = list(self._channels.values())
        try:
            self.store.save()
        except (OSError, RuntimeError):
            self._error = '无法保存任务 Channel'
            return False
        return True

    def start_human_turn(self, record, objective):
        # Called only by an explicit ordinary user prompt accepted by the host.
        self.invalidate(record)
        self._tokens[record.key] = {'id': uuid.uuid4().hex, 'record': record, 'objective': objective[:8000],
                                    'session': record.id, 'prompt': objective, 'delivery': '', 'active': False, 'reply': '',
                                    'created': int(time.time() * 1000)}

    def invalidate(self, record):
        token = self._tokens.pop(record.key, None)
        if token and (channel := self._channels.get(token['id'])) and channel['phase'] == 'running':
            channel['phase'] = 'interrupted'
            self._persist()
        if token and self._visible:
            self.changed.emit()

    def before_notification(self, record, item):
        # This is a read of the host's own outbox ticket, not model content.
        token = self._tokens.get(record.key)
        if not token:
            return
        channel = self._channels.get(token['id'])
        if (not channel or channel.get('closed') or item['target'] != 'agent:' + record.global_agent
                or item.get('groupChat') is not None or 'teamId' in item['data']
                or not any(r['id'] == item['requestId'] for r in channel['requests'])):
            self.invalidate(record)
            return
        if item['wake'] and not record.busy:
            token['delivery'] = item['id']

    def _activate(self, token):
        token.update(prompt='', delivery='', active=True, reply='')
        if (channel := self._channels.get(token['id'])) and not channel['closed']:
            channel['phase'] = 'running'
            self._persist()
            if self._visible:
                self.changed.emit()

    def observe_coordinator(self, record, event):
        token = self._tokens.get(record.key)
        if token is None or token['record'] is not record:
            return
        kind = event.get('type')
        if kind == 'exit' or (token['session'] and record.id and token['session'] != record.id):
            self.invalidate(record)
            return
        if kind == 'user_start':
            # The pending host command supplied the token; text only guards its
            # acknowledgement and cannot opt an arbitrary transcript into a task.
            if token['prompt'] and event.get('text') == token['prompt']:
                self._activate(token)
            else:
                self.invalidate(record)
        elif kind == 'widget_delivery' and token['delivery'] and event.get('id') == token['delivery']:
            if event.get('status') == 'delivered':
                self._activate(token)
            elif event.get('status') in ('failed', 'cancelled'):
                self.invalidate(record)
        elif kind == 'agent_run' and not (token['active'] or token['delivery']):
            self.invalidate(record)
        elif (kind == 'message' and token['active'] and event.get('role') == 'assistant'
              and event.get('stopReason') not in ('toolUse', 'error', 'aborted') and event.get('text')):
            token['reply'] = event['text'][:8000]
        elif kind == 'done':
            if not token['active']:
                if token['prompt'] or token['delivery']:
                    self.invalidate(record)
                return
            token['active'] = False
            if (channel := self._channels.get(token['id'])) and not channel['closed']:
                channel['phase'] = 'interrupted' if record.cancelled or record.failed else 'idle'
                if token['reply']:
                    channel['notes'] = (channel.get('notes', []) + [{'role': 'assistant', 'text': token['reply'],
                                                               'time': int(time.time() * 1000)}])[-50:]
                self._persist()
                if self._visible:
                    self.changed.emit()

    def capture_dispatch(self, record, request):
        token = self._tokens.get(record.key)
        # The ordinary local target must have an exact native session ID.
        # Shared global-member conversation histories are never attached.
        if (not token or token['record'] is not record or not token['active'] or record.bus_task
                or not record.id or not self._valid_request(request)
                or request['source'] != 'agent:' + record.global_agent):
            return
        if token['session'] and token['session'] != record.id:
            self.invalidate(record)
            return
        token['session'] = record.id
        channel = self._channels.get(token['id'])
        if channel is None:
            if len(self._channels) >= 64:
                return
            channel = self._channels[token['id']] = {
                'id': token['id'], 'coordinator': record.global_agent, 'session': record.id,
                'name': request['sourceTitle'], 'objective': token['objective'], 'created': token['created'],
                'phase': 'running', 'closed': False, 'requests': [], 'notes': [], 'draft': '',
            }
            if not self._selected:
                self._selected = channel['id']
                self._generation += 1
        if channel['closed'] or len(channel['requests']) >= 32:
            if not channel['closed']:
                channel['incomplete'] = True
                self._persist()
            return
        if not any(row['id'] == request['id'] for row in channel['requests']):
            request['channelTaskId'] = token['id']
            channel['requests'].append({key: request.get(key) for key in ('id', 'source', 'target', 'text', 'status', 'result', 'created')})
            self._persist()
            self.changed.emit()

    def observe_request(self, request):
        channel = self._channels.get(request.get('channelTaskId'))
        if not channel or channel['closed']:
            return
        link = next((r for r in channel['requests'] if r['id'] == request['id']
                     and r['source'] == request['source'] and r['target'] == request['target']), None)
        if link and (link.get('status'), link.get('result')) != (request['status'], request.get('result')):
            link.update(status=request['status'], result=request.get('result') or '',
                        updated=int(time.time() * 1000))
            self._persist()
            self.changed.emit()

    def _status(self, row):
        if row.get('closed'):
            return 'closed'
        if row.get('reworkPending'):
            return 'running'
        if row.get('reworkInterrupted') or row.get('incomplete') or row.get('phase') == 'interrupted':
            return 'interrupted'
        statuses = [r.get('status') for r in row['requests']]
        if any(value in ('failed', 'cancelled', 'interrupted') for value in statuses):
            return 'interrupted'
        if row['id'] == self._selected and any(task['status'] in ('failed', 'error', 'stopped', 'aborted')
                                               for task in self._tasks.values()):
            return 'interrupted'
        if (row['id'] == self._selected and not self._busy and row['phase'] == 'idle'
                and statuses and all(value == 'completed' for value in statuses)
                and self._scanned == {r['id'] for r in row['requests']}
                and self._tasks and all(task['status'] == 'completed' and task['ready'] for task in self._tasks.values())):
            return 'review'
        return 'running'

    def _record_for(self, row):
        if not row or row['closed'] or not row.get('session') or row['phase'] != 'idle' or not self.bus.active:
            return None
        record = self.bus.records.get(row['coordinator'])
        token = self._tokens.get(record.key) if record else None
        if (not record or not token or token['record'] is not record or token['id'] != row['id']
                or token['prompt'] or token['delivery'] or token['active'] or token['session'] != row['session'] or record.id != row['session']
                or record.bus_task or record.busy or record.approval or record.stale or not record.process or not record.ready
                or self.bus.member_sessions.get(row['coordinator']) is not None
                or self.bus.agents.get(row['coordinator'], {}).get('quotaPaused')
                or any(item['target'] == 'agent:' + row['coordinator'] for item in self.bus.outbox.values())):
            return None
        if not all(self.bus.bridge_access(request['target'][8:])['bridgeAll']
                   or row['coordinator'] in self.bus.bridge_access(request['target'][8:])['bridgeAgents']
                   for request in row['requests']):
            return None
        return record

    channelRows = Property('QVariantList', lambda self: [
        {'id': row['id'], 'title': row['objective'], 'status': self._status(row)} for row in self._channels.values()
    ], notify=changed)
    loading = Property(bool, lambda self: self._loading, notify=changed)
    error = Property(str, lambda self: self._error, notify=changed)
    executionLoading = Property(bool, lambda self: self._execution_loading, notify=changed)
    executionError = Property(str, lambda self: self._execution_error, notify=changed)
    transcript = Property('QVariantList', lambda self: self._messages, notify=changed)

    @Property('QVariantMap', notify=changed)
    def channel(self):
        row = self._channels.get(self._selected)
        if not row:
            return {}
        return {'id': row['id'], 'title': row['objective'], 'coordinator': row['name'],
                'status': self._status(row), 'canSend': not row.get('reworkPending') and bool(self._record_for(row)),
                'draft': row.get('draft', ''), 'requests': row['requests'], 'notes': row.get('notes', []),
                'messages': self._chat_rows(row), 'participants': 1 + len(self._tasks),
                'tasks': [{k: t[k] for k in ('id', 'requestId', 'title', 'role', 'status', 'summary', 'ready')}
                          | {'artifacts': self._public_artifacts(t)} for t in self._tasks.values()]}

    def _chat_rows(self, row):
        result = [{'kind': 'message', 'actor': 'user', 'role': 'user',
                   'text': row['objective'], 'time': row.get('created') or 0}]
        for request in row['requests']:
            result.append({'kind': 'message', 'actor': 'coordinator', 'role': 'coordinator',
                           'text': request['text'], 'time': int((request.get('created') or 0) * 1000)})
            result.append({'kind': 'progress', 'actor': '', 'role': '', 'status': request['status'],
                           'text': request.get('result') or '', 'time': request.get('updated') or 0})
        for position, task in enumerate(self._tasks.values(), 1):
            result.append({'kind': 'message', 'actor': task['id'], 'role': 'worker',
                           'workerRole': task['role'], 'ordinal': position,
                           'text': task['summary'] or task['title'], 'title': task['title'], 'status': task['status'],
                           'taskId': task['id'], 'ready': task['ready'], 'time': task['time'] or 0,
                           'artifacts': self._public_artifacts(task)})
        for update in row.get('syncUpdates', []):
            mention = dict_value(update.get('mention'))
            if (mention.get('coordinatorId') == 'agent:' + row['coordinator']
                    and mention.get('sessionId') == row.get('session') and update.get('summary')):
                key = update.get('taskId')
                child = self._tasks.get(key, {})
                ordinal = next((i for i, task_id in enumerate(self._tasks, 1) if task_id == key), 1)
                result.append({'kind': 'message', 'actor': key, 'role': 'worker',
                               'workerRole': child.get('role') or update.get('workerRole'),
                               'ordinal': ordinal, 'mentionId': mention['coordinatorId'],
                               'mentionName': row['name'], 'text': update['summary'],
                               'status': update['status'], 'time': update['time'],
                               'artifactCount': update.get('artifactCount', len(update['artifacts']))})
                continue
            result.append({'kind': 'progress', 'actor': '', 'role': '', 'status': update['status'],
                           'rework': True, 'artifactNames': update['artifacts'], 'text': '', 'time': update['time']})
        for note in row.get('notes', []):
            role = 'user' if note['role'] == 'user' else 'coordinator'
            result.append({'kind':'message', 'actor': role, 'role': role,
                           'text': note['text'], 'time': note.get('time') or 0})
        # Old profiles do not contain all timestamps. Preserve the real source
        # order for unknown values rather than assigning a fabricated timestamp.
        if all(message['time'] for message in result):
            result.sort(key=lambda message: message['time'])
        return result

    @staticmethod
    def _public_artifacts(task):
        return [{k: a[k] for k in ('id', 'name')} for a in task['artifacts']]

    @Property('QVariantMap', notify=changed)
    def execution(self):
        row = self._tasks.get(self._task_id)
        channel = self._channels.get(self._selected, {})
        if not row:
            return {}
        return {k: row[k] for k in ('id', 'title', 'role', 'status', 'sessionId')} | {
            'canSend': bool(self._child_route(channel, row)),
            'draft': channel.get('childDrafts', {}).get(self._task_id, ''),
            'pending': bool(channel.get('reworkPending') or channel.get('privatePending')),
        }

    def _child_route(self, channel, task, own=None):
        pending = (channel.get('reworkPending') or channel.get('privatePending')) if channel else None
        signature = own['signature'] if own else self._signature
        if (not channel or channel.get('closed') or (pending and (not own or pending != own['token']))
                or not task or not task['ready'] or task['status'] != 'completed' or (self._busy and not own)
                or signature != self._inputs(channel)):
            return None
        request = next((r for r in channel['requests'] if r['id'] == task['requestId'] and r['target'] == 'session:' + task['parentId']
                        and r['status'] == 'completed'), None)
        coordinator = self._record_for(channel)
        parent = self.b._pool.find(task['parentId'])
        if (not request or request['source'] != 'agent:' + channel['coordinator'] or not coordinator
                or not parent or parent is not self.b._view or parent.global_agent or parent.cowork
                or parent.terminal_owned or (parent.busy and not (own and parent is own['parent']
                    and parent.operation and parent.phase == 'idle')) or parent.approval or not parent.process or not parent.ready
                or parent.stale or parent.cancelled or parent.id != task['parentId']
                or self.store.data['sessionMeta'].get(parent.id, {}).get('pluginSession')
                or not self.bus.connected(coordinator, parent) or self.b._remote_project_for_workspace(parent.workspace)):
            return None
        path = local_file(parent.file, (self.store.directory / 'pi' / 'sessions').resolve())
        if path != task['parent'] or not local_file(task['path'], path.parent / path.stem / 'tasks'):
            return None
        if Path(parent.workspace or self.store.default_workspace).resolve() != task['workspace']:
            return None
        return parent, coordinator

    @Slot(str, str, str)
    def setChildDraft(self, channel_id, task_id, text):
        channel = self._channels.get(channel_id)
        if channel_id == self._selected and task_id == self._task_id and channel and not channel.get('closed'):
            channel.setdefault('childDrafts', {})[task_id] = text[:16000]

    @Slot(str, str, str, result=bool)
    def sendToChild(self, channel_id, task_id, text):
        if channel_id != self._selected or task_id != self._task_id or not text.strip() or len(text) > 16000:
            return False
        self.setChildDraft(channel_id, task_id, text)
        channel, task = self._channels.get(channel_id), self._tasks.get(task_id)
        route = self._child_route(channel, task)
        if not route:
            self._execution_error = '原子智能体、协调者或授权暂不可用；草稿已保留。'
            self._persist()
            self.changed.emit()
            return False
        parent, coordinator = route
        token = uuid.uuid4().hex
        pending = {'channel': channel, 'task': task, 'parent': parent, 'coordinator': coordinator,
                   'text': text, 'token': token, 'signature': self._signature,
                   'action': '', 'started': False, 'sync': '', 'finished': None}
        channel['privatePending'] = token
        if not self._persist():
            channel.pop('privatePending', None)
            self.changed.emit()
            return False
        self._rework[token] = pending
        parent.operation = True
        self._execution_error = ''
        self.b._write_pi({'type': 'channel-child', 'id': task_id.split(':', 1)[1], 'requestId': token,
                          'text': text, 'parentSessionId': parent.id, 'childSessionId': task['sessionId'],
                          'childFile': task['path'], 'workspace': str(task['workspace'])}, parent)
        self.changed.emit()
        return True

    def _settle_rework(self, token, ok, error='', artifacts=None):
        pending = self._rework.pop(token, None)
        if not pending:
            return
        channel, task = pending['channel'], pending['task']
        pending['parent'].operation = False
        shared = bool(pending['action'])
        channel.pop('reworkPending' if shared else 'privatePending', None)
        if shared and pending['started']:
            channel['reworkInterrupted'] = not ok
        for update in channel.get('syncUpdates', []):
            if update['updateId'] == token:
                update['status'] = 'completed' if ok else 'interrupted'
                if artifacts is not None:
                    before = {item['id']: item['digest'] for item in task['artifacts']}
                    update['artifactCount'] = sum(before.get(a['id']) != a['digest'] for a in artifacts)
        if ok:
            if shared and artifacts is not None and self._selected == channel['id'] and task['id'] in self._tasks:
                self._tasks[task['id']]['artifacts'] = artifacts
            drafts = channel.get('childDrafts', {})
            if drafts.get(task['id']) == pending['text']:
                drafts.pop(task['id'])
        if self._selected == channel['id']:
            self._execution_error = error
        self._persist()
        self.changed.emit()
        if self._task_id == task['id'] and self._selected == channel['id']:
            self._read_execution(self._task_id)

    def _check_pending_route(self, pending):
        parent, coordinator = pending['parent'], pending['coordinator']
        return self._child_route(pending['channel'], pending['task'], own=pending) == (parent, coordinator)

    def _started_task(self, token, pending):
        channel, task, coordinator = pending['channel'], pending['task'], pending['coordinator']
        pending['started'] = True
        if not self._check_pending_route(pending):
            pending['sync'] = 'failed'
            return
        summary = CHANNEL_ACTION_SUMMARIES[pending['action']][self.b.language == 'en']
        update = {'updateId': token, 'channelId': channel['id'], 'requestId': task['requestId'],
                  'childExecutionId': task['sessionId'], 'taskId': task['id'], 'status': 'accepted',
                  'workerRole': task['role'], 'summary': summary,
                  'mention': {'coordinatorId': 'agent:' + channel['coordinator'], 'sessionId': coordinator.id},
                  'artifacts': [], 'time': int(time.time() * 1000)}
        pending.update(sync='awaiting', update=update)
        self.b._write_pi({'type': 'channel-sync', 'requestId': token,
                          'coordinatorSessionId': coordinator.id, 'update': update}, coordinator)

    def _finish_started_task(self, token, pending):
        outcome = pending['finished']
        if outcome is not None and pending['sync'] != 'awaiting':
            ok, error, artifacts = outcome
            if pending['sync'] == 'failed' and not error:
                error = '子智能体已处理，但原协调者未收到受理同步；不要直接重发。'
            self._settle_rework(token, ok, error, artifacts)

    @Slot(object, object)
    def observe_child(self, record, event):
        kind = event.get('type')
        if kind == 'exit':
            for token, item in list(self._rework.items()):
                if record is item['parent']:
                    self._settle_rework(token, False, '会话已退出；未自动重发。')
                elif record is item['coordinator'] and item['sync'] == 'awaiting':
                    item['sync'] = 'failed'
                    self._finish_started_task(token, item)
            return
        token = event.get('requestId')
        pending = self._rework.get(token) if isinstance(token, str) else None
        if not pending:
            return
        if kind == 'channel_sync_result' and record is pending['coordinator'] and pending['sync'] == 'awaiting':
            if event.get('ok') is True:
                channel = pending['channel']
                updates = channel.setdefault('syncUpdates', [])
                if not any(update['updateId'] == token for update in updates):
                    updates.append(pending['update'])
                    channel['syncUpdates'] = updates[-50:]
                pending['sync'] = 'accepted'
                self._persist()
                self.changed.emit()
            else:
                pending['sync'] = 'failed'
            self._finish_started_task(token, pending)
            return
        if record is not pending['parent']:
            return
        if kind in ('channel_child_intent', 'channel_child_started'):
            task, channel = pending['task'], pending['channel']
            action = event.get('action')
            matches = event.get('childSessionId') == task['sessionId'] and event.get('parentSessionId') == task['parentId']
            if kind == 'channel_child_intent' and not pending['action']:
                allowed = matches and isinstance(action, str) and action in CHANNEL_ACTION_SUMMARIES and self._check_pending_route(pending)
                if allowed:
                    channel.pop('privatePending', None)
                    channel['reworkPending'] = token
                    allowed = self._persist()
                    if allowed:
                        pending['action'] = action
                    else:
                        channel.pop('reworkPending', None)
                        channel['privatePending'] = token
                    self.changed.emit()
                self.b._write_pi({'type': 'channel-child-grant', 'requestId': token, 'ok': bool(allowed),
                    'childSessionId': task['sessionId'], 'parentSessionId': task['parentId']}, record)
            elif kind == 'channel_child_started' and matches and pending['action'] and action == pending['action'] and not pending['started']:
                self._started_task(token, pending)
            return
        if kind != 'channel_child_result' or pending['finished'] is not None or pending.get('scanning'):
            return
        ok = event.get('ok') is True
        error = '' if ok else str(event.get('message') or '未能继续原子智能体')[:300]
        if not pending['action']:
            self._settle_rework(token, ok, error)
            return
        if not ok or not pending['started']:
            pending['finished'] = (False, error or '未收到原生执行的受理回执。', None)
            self._finish_started_task(token, pending)
            return
        pending['scanning'] = True
        task = pending['task']
        def work():
            try:
                path = local_file(task['path'], task['parent'].parent / task['parent'].stem / 'tasks')
                identity, artifacts = child_details(path, task['parentId'], task['workspace']) if path else ('', [])
                result = (identity == task['sessionId'], artifacts)
            except (OSError, RuntimeError, ValueError, TypeError):
                result = (False, [])
            if not self._closed:
                self.reworkScanned.emit((token, *result))
        self._worker.submit(work)

    @Slot(object)
    def _rework_scanned(self, value):
        token, ok, artifacts = value
        pending = self._rework.get(token)
        if not pending or not pending.get('scanning'):
            return
        pending['finished'] = (ok, '' if ok else '无法核验原子执行的记录。', artifacts if ok else None)
        self._finish_started_task(token, pending)


    @Slot(bool)
    def setVisible(self, visible):
        self._visible = visible
        if visible:
            self._timer.start()
            self.refresh()
        else:
            self._timer.stop()
            self.closeExecution()

    @Slot(str)
    def select(self, channel_id):
        if channel_id not in self._channels or channel_id == self._selected:
            return
        self._selected = channel_id
        self._generation += 1
        self._signature, self._error = None, ''
        self._tasks, self._scanned = {}, set()
        self.closeExecution()
        self.changed.emit()
        self.refresh()

    @Slot(str, str)
    def setDraft(self, channel_id, draft):
        row = self._channels.get(channel_id)
        if not row or row.get('closed') or row.get('draft') == draft:
            return
        row['draft'] = draft[:16000]

    @Slot(str, str, result=bool)
    def sendToCoordinator(self, channel_id, text):
        if channel_id != self._selected or not text.strip() or len(text) > 16000:
            return False
        self.setDraft(channel_id, text)
        row = self._channels[channel_id]
        record = self._record_for(row)
        if record is None or sum(r.busy for r in (*self.bus.records.values(), *self.bus.member_sessions.values())) >= 4:
            self._error = '协调者当前无法接收此任务的消息，草稿已保留。'
            self._persist()
            self.changed.emit()
            return False
        if row.get('reworkPending') or not self.b._command_pi('prompt', record, text=text.strip(), channelTaskId=channel_id):
            self._error = '协调者未接受消息，草稿已保留。'
            self._persist()
            self.changed.emit()
            return False
        self._tokens[record.key]['prompt'] = text.strip()
        row['phase'], row['draft'], self._error = 'running', '', ''
        row.setdefault('notes', []).append({'role': 'user', 'text': text.strip(), 'time': int(time.time() * 1000)})
        row['notes'] = row['notes'][-50:]
        self._persist()
        self.changed.emit()
        return True

    @Slot(str, result=bool)
    def accept(self, channel_id):
        row = self._channels.get(channel_id)
        if not row or channel_id != self._selected or row.get('privatePending') or self._status(row) != 'review':
            return False
        # Revalidate source fingerprints synchronously (stats only) before
        # freezing the board. A new turn, result, or native child invalidates it.
        if self._signature != self._inputs(row):
            self.refresh()
            return False
        if any(item['requestId'] in {r['id'] for r in row['requests']} for item in self.bus.outbox.values()):
            return False
        row['closed'] = True
        if not self._persist():
            row['closed'] = False
            self.changed.emit()
            return False
        self.changed.emit()
        return True

    def _inputs(self, channel):
        inputs = []
        root = (self.store.directory / 'pi' / 'sessions').resolve()
        for link in channel['requests']:
            session_id = link['target'][8:]
            live = self.b._pool.find(session_id)
            session = next((s for s in self.b._sessions if s['id'] == session_id), {})
            path = local_file((live.file if live else '') or session.get('file'), root)
            if path is None:
                continue
            try:
                workspace = Path((live.workspace if live else '') or session.get('workspace')
                                 or self.store.default_workspace).resolve(strict=True)
                stat = path.stat()
            except (OSError, RuntimeError, ValueError):
                continue
            inputs.append(((link['id'], link['source'], link['target']), path, workspace, stat.st_size, stat.st_mtime_ns))
        return tuple(inputs)

    @Slot()
    def refresh(self):
        channel = self._channels.get(self._selected)
        if self._closed or self._busy or not channel:
            return
        inputs = self._inputs(channel)
        if inputs == self._signature:
            availability = (self._selected, self._task_id,
                            not channel.get('reworkPending') and bool(self._record_for(channel)),
                            bool(self._child_route(channel, self._tasks.get(self._task_id))))
            if availability != self._availability:
                self._availability = availability
                self.changed.emit()
            if self._task_id and not self._execution_loading:
                self._read_execution(self._task_id)
            return
        self._signature, self._busy, self._loading = inputs, True, not self._tasks
        generation = self._generation

        def work():
            tasks, scanned = {}, set()
            for identity, path, workspace, *_ in inputs:
                try:
                    objective, children = project_request(path, identity, workspace)
                except (OSError, RuntimeError, ValueError, TypeError):
                    continue
                if objective:
                    scanned.add(identity[0])
                for child, task in children.items():
                    key = identity[0] + ':' + child
                    tasks[key] = dict(task, id=key, requestId=identity[0], parent=path, workspace=workspace,
                                      parentId=identity[2][8:])
            if not self._closed:
                self.loaded.emit((generation, tasks, scanned))

        self._worker.submit(work)

    @Slot(object)
    def _loaded(self, value):
        generation, tasks, scanned = value
        self._busy = self._loading = False
        if self._closed:
            return
        if generation != self._generation:
            self.refresh()
            return
        self._tasks, self._scanned = tasks, scanned
        if self._task_id and self._task_id not in tasks:
            self.closeExecution()
        elif self._task_id and not self._execution_loading:
            self._read_execution(self._task_id)
        self.changed.emit()

    @Slot(str)
    def openExecution(self, task_id):
        self._read_execution(task_id)

    def _read_execution(self, task_id):
        row = self._tasks.get(task_id)
        if not row or not row['ready']:
            return
        parent = row['parent']
        path = local_file(row['path'], parent.parent / parent.stem / 'tasks')
        if path is None:
            return
        try:
            stat = path.stat()
        except OSError:
            return
        signature = (self._selected, task_id, row['sessionId'], path, stat.st_size, stat.st_mtime_ns)
        if self._execution_signature == signature:
            return
        if (self._execution_signature and task_id == self._task_id
                and self._execution_signature[2] != row['sessionId']):
            self.closeExecution()
            return
        if task_id != self._task_id:
            self._messages = []
        self._execution_signature = signature
        self._task_id, self._execution_error = task_id, ''
        self._execution_loading = True
        self._execution_generation += 1
        generation = self._execution_generation
        self.changed.emit()

        def work():
            try:
                payload = (read_child_history(path, signature, row['parentId'], row['workspace']), '')
            except (OSError, RuntimeError, ValueError, TypeError) as error:
                payload = ([], str(error))
            if not self._closed:
                self.historyLoaded.emit((generation, *payload))

        self._history_worker.submit(work)

    @Slot(object)
    def _history_loaded(self, value):
        generation, messages, error = value
        if self._closed or generation != self._execution_generation:
            return
        self._messages, self._execution_error, self._execution_loading = messages, error, False
        self.changed.emit()

    @Slot()
    def closeExecution(self):
        if self._task_id:
            self._execution_generation += 1
            self._task_id, self._messages, self._execution_error = '', [], ''
            self._execution_signature = None
            self._execution_loading = False
            self.changed.emit()

    @Slot(str, str, result=bool)
    def openArtifact(self, task_id, artifact_id):
        row = self._tasks.get(task_id)
        artifact = next((a for a in row['artifacts'] if a['id'] == artifact_id), None) if row else None
        if not artifact:
            return False
        path = local_file(artifact['path'], row['workspace'])
        if path is None or path_digest(path) != artifact['digest']:
            return False
        self.b.openChatboxPath(str(path), False)
        return True

    def close(self):
        self._closed = True
        self._timer.stop()
        if self._channels:
            self._persist()
        self._worker.shutdown(wait=False, cancel_futures=True)
        self._history_worker.shutdown(wait=False, cancel_futures=True)
