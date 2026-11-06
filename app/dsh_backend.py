"""Optional official dsh ACP process and local display history; Pi is unchanged."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from .message_attachments import attachment_prompt
from .model_reasoning import reasoning_levels
from .npm_config import npm_environment
from .pi_runtime import CREATE_NO_WINDOW, node_executable


INTERRUPTION_NOTICE = '[用户已停止上一条请求；请只处理新消息，除非用户明确要求继续。]'
# Shown in the chat; the model still receives INTERRUPTION_NOTICE with the next prompt.
INTERRUPTION_STATUS = '已停止上一条请求'


def is_dsh(record):
    return getattr(record, 'backend', 'pi') == 'dsh'


def profile_configuration(providers, selected_provider, selected_model, max_tokens,
                          permission_mode='auto', permission_plugin=None, *,
                          proxy_url='', proxy_token='', own_config=False, session_root=None):
    """Compose the official profile; only the ephemeral local proxy token leaves Umeko."""
    if permission_mode not in ('auto', 'ask'):
        raise ValueError('DeepSeek Harness 不支持当前权限模式，请选择自动或询问。')
    plugin = Path(permission_plugin or Path(__file__).resolve().parents[1] / 'runtime/dsh-permissions.mjs')
    patch, environment = [], {}
    if not own_config:
        if not proxy_url or not proxy_token:
            raise RuntimeError('Umeko 内部 API 代理不可用，请重新启动 Umeko 后重试。')
        configured = {}
        for provider in providers:
            models = []
            for model in provider.get('models', []):
                levels = reasoning_levels(model)
                models.append({'id': model['alias'], 'name': model['alias'],
                               'contextWindow': model.get('contextWindow', 128000), 'maxTokens': max_tokens,
                               'reasoningEfforts': {'off': None, **{level: level for level in levels}} if levels else False})
            configured[provider['id']] = {
                'api': 'openai-completions', 'baseURL': proxy_url, 'apiKeyEnv': 'UMEKO_DSH_PROXY_TOKEN',
                'models': models, 'defaultMaxTokens': max_tokens,
                'compat': {'supportsDeveloperRole': False, 'thinkingFormat': 'openai'},
            }
        provider = next((p for p in providers if p['id'] == selected_provider), {})
        if not any(model['alias'] == selected_model for model in provider.get('models', [])):
            raise ValueError('请选择一个已在 Umeko 配置的可用模型。')
        selection = {'provider': selected_provider, 'model': selected_model}
        patch.extend([{'id': 'llm-pi-ai', 'config': {'providers': configured}},
                      {'id': 'acp', 'config': selection}, {'id': 'agent-default-model', 'config': selection}])
        environment['UMEKO_DSH_PROXY_TOKEN'] = proxy_token
    patch.extend([{'id': 'sandbox-policy', 'config': {'mode': 'workspace-write', 'additionalWritableRoots': []}},
             {'id': 'approval', 'config': {'policy': 'ask'}},
             {'id': 'permission', 'config': {'defaultPreset': 'workspace-write', 'presets': {
                 'read-only': {'sandbox': 'read-only', 'approval': 'ask'},
                 'workspace-write': {'sandbox': 'workspace-write', 'approval': 'ask'},
                 'danger-full-access': {'sandbox': 'danger-full-access', 'approval': 'never'}}}},
             {'insert': [{'id': 'umeko-tool-permissions', 'name': plugin.resolve().as_uri(),
                          'inject': ['tools', 'approval', 'sandboxPolicy', 'permissionPresets'],
                          'config': {'mode': permission_mode}}]},
             {'id': 'session-telemetry-otel', 'disabled': True}])
    if session_root is not None:
        patch.append({'id': 'session-persistence-jsonl', 'config': {'root': str(session_root)}})
    if not own_config:
        patch.extend({'id': name, 'disabled': True} for name in ('llm-deepseek', 'llm-deepseek-account', 'deepseek-account'))
    return patch, environment


def dsh_environment(config, providers, *, own_config=False):
    """Keep native credential resolution opt-in; default dsh only calls loopback."""
    from .dsh_runtime import child_environment
    return child_environment(npm_environment(config), providers, own_config=own_config)


class DshProcess(QObject):
    """QProcess-shaped handle with an explicitly hidden Windows child."""
    received = Signal(object)
    ended = Signal()

    def __init__(self, pool, record, bridge, payload, environment):
        super().__init__(pool)
        self.received.connect(lambda event: pool.event.emit(record, event) if record.process is self and not pool.closing else None)
        self.ended.connect(lambda: self._ended(pool, record))
        self._lock = threading.Lock()
        self._process = subprocess.Popen([node_executable(), str(bridge)], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=environment,
            creationflags=CREATE_NO_WINDOW)
        record.process = self
        self.write((json.dumps(payload, ensure_ascii=False) + '\n').encode())
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            for line in self._process.stdout:
                try:
                    self.received.emit(json.loads(line))
                except (ValueError, UnicodeDecodeError):
                    continue
        finally:
            self._process.wait()
            self.ended.emit()

    def _ended(self, pool, record):
        if record.process is self:
            record.process, record.ready, record.crashed = None, False, True
            if not pool.closing:
                pool.event.emit(record, {'type': 'exit', 'message': 'DeepSeek Harness 运行时已退出，请在设置 → Agent 中检查运行时。'})
        pool.retiring.discard(self)
        self.deleteLater()

    def write(self, payload):
        with self._lock:
            try:
                self._process.stdin.write(payload)
                self._process.stdin.flush()
            except (OSError, ValueError):
                pass

    def state(self):
        return QProcess.Running if self._process.poll() is None else QProcess.NotRunning

    def waitForFinished(self, milliseconds):
        try:
            self._process.wait(timeout=milliseconds / 1000)
            return True
        except subprocess.TimeoutExpired:
            return False

    def kill(self):
        if self._process.poll() is None:
            self._process.kill()


class DisplayHistory:
    """One ordered writer, flushed before shutdown; ACP retains model context."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix='dsh-history')
        self.pending = []

    def path(self, session_id):
        if not session_id.startswith('dsh-') or not session_id[4:].isalnum():
            raise ValueError('会话编号无效')
        return self.directory / (session_id + '.json')

    def save(self, session_id, value):
        snapshot = copy.deepcopy(value)
        def write():
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.path(session_id)
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(snapshot, ensure_ascii=False), encoding='utf-8')
            temporary.replace(path)
        self.pending = [future for future in self.pending if not future.done()]
        self.pending.append(self.writer.submit(write))

    def read(self, session_id):
        # A just-closed process can be reopened while its last display save drains.
        for future in tuple(self.pending):
            future.result()
        return json.loads(self.path(session_id).read_text(encoding='utf-8'))

    def close(self):
        self.writer.shutdown(wait=True)
        for future in self.pending:
            future.result()


class DshControllerMixin:
    def _init_dsh(self):
        from .dsh_runtime import DshRuntimeService
        self._dsh_history = DisplayHistory(self.store.directory / 'dsh/transcripts')
        self._dsh_runtime = DshRuntimeService(self.store.directory / 'dsh/runtime',
            config=self.store.data.setdefault('dsh', {}), save_config=self.store.save,
            npm_config=self.store.data['agent'], parent=self)
        self._dsh_runtime.configChanged.connect(self.changed)
        self._dsh_runtime.configChanged.connect(self.chatChanged)

    def _dsh_own(self, record):
        saved = getattr(record, 'dsh_own_config', None)
        return saved if saved is not None else self._dsh_runtime.useOwnConfig

    def _dsh_model_option(self, record):
        return next((option for option in getattr(record, 'dsh_options', [])
                     if option.get('category') == 'model' or option.get('id') == 'model'), {})

    def _dsh_model_providers(self, record):
        rows = []
        for index, group in enumerate(self._dsh_model_option(record).get('options', [])):
            choices = group.get('options', [group])
            models = [{'alias': choice.get('name', ''), 'upstream': '', 'value': choice['value']}
                      for choice in choices if isinstance(choice.get('value'), str)]
            if models:
                rows.append({'id': f'dsh-native-{index}',
                             'name': group.get('name', 'DeepSeek Harness') if 'options' in group else 'DeepSeek Harness',
                             'models': models})
        return rows

    def _dsh_current_model(self, record):
        value = self._dsh_model_option(record).get('currentValue', '')
        return next(((group['name'], model['alias']) for group in self._dsh_model_providers(record)
                     for model in group['models'] if model['value'] == value), ('DeepSeek Harness', '默认模型'))

    def _select_dsh_model(self, value):
        record = self._view
        if not is_dsh(record) or not self._dsh_own(record) or record.busy or not record.ready:
            return False
        option = self._dsh_model_option(record)
        if not any(model['value'] == value for group in self._dsh_model_providers(record) for model in group['models']):
            return False
        if value != option.get('currentValue'):
            self._pool.write(record, {'type': 'set_config', 'configId': option['id'], 'value': value})
        return True

    def _choose_dsh_backend(self, value):
        record = self._view
        if value not in ('pi', 'dsh') or record.id or record.messages or record.busy:
            return False
        record.backend = value
        self.chatChanged.emit()
        self.reasoningChanged.emit()
        return True

    def _index_record(self, record):
        super()._index_record(record)
        if is_dsh(record):
            row = next(s for s in self._sessions if s['id'] == record.id)
            row.update(backend='dsh', acpSessionId=getattr(record, 'acp_session_id', ''),
                       dshHome=getattr(record, 'dsh_home', ''), file='',
                       dshOwnConfig=self._dsh_own(record),
                       dshSessionRoot=getattr(record, 'dsh_session_root', ''))

    def _save_dsh(self, record):
        if not record.id:
            return
        self._index_record(record)
        self._dsh_history.save(record.id, {'messages': record.messages,
            'contextUsage': record.context_usage, 'configOptions': getattr(record, 'dsh_options', []),
            'interruptionPending': getattr(record, 'dsh_interruption_pending', False)})
        self.store.save_sessions(self._sessions)

    def _open_dsh(self, session):
        record = self._pool.find(session['id'])
        if record:
            self._activate(record)
            return
        record = self._new_view(session.get('workspace', ''))
        record.backend, record.id, record.title = 'dsh', session['id'], session['title']
        record.model, record.provider = session.get('model', record.model), session.get('provider', record.provider)
        record.acp_session_id, record.dsh_home = session.get('acpSessionId', ''), session.get('dshHome', '')
        record.dsh_own_config = session.get('dshOwnConfig') is True
        record.dsh_session_root = session.get('dshSessionRoot', '')
        record.reasoning_effort = self.store.data['sessionMeta'].get(record.id, {}).get('reasoningEffort', 'off')
        record.phase = 'loading'
        self._activate(record)
        self._job('dsh-open:' + record.key, lambda: self._dsh_history.read(record.id))

    def _dsh_opened(self, key, result):
        record = self._pool.records.get(key)
        if record is None:
            return
        record.phase = 'idle'
        if result['ok']:
            value = result['value']
            record.messages = value.get('messages', [])
            record.context_usage = value.get('contextUsage', {})
            record.dsh_options = value.get('configOptions', [])
            record.dsh_interruption_pending = value.get('interruptionPending', False)
        else:
            record.messages = [{'role': 'assistant', 'text': 'DeepSeek Harness 显示历史暂时无法读取；请保留本地会话目录。', 'error': True}]
        self.chatChanged.emit()
        self.contextUsageChanged.emit()
        self.reasoningDetectionChanged.emit()
        if result['ok'] and record.acp_session_id:
            self._command_dsh('open', record)

    def _command_pi(self, action, record=None, **values):
        record = record or self._view
        if is_dsh(record):
            return self._command_dsh('open' if action == 'inspect' else action, record, **values)
        return super()._command_pi(action, record, **values)

    def _command_dsh(self, action, record, **values):
        if action not in ('prompt', 'open') or record.busy:
            return False
        record.action, record.failed, record.cancelled = action, False, False
        record.phase = 'running'
        record.tool_status = '正在连接 DeepSeek Harness' if not record.process else '正在生成'
        record.prompt_started = time.monotonic() if action == 'prompt' else None
        try:
            if record.process and record.ready and not record.stale:
                self._pool.write(record, {'type': action, **values, 'config': self._dsh_selection(record)})
            else:
                if record.process:
                    self._pool.retire(record)
                from .dsh_runtime import discover_dsh
                runtime = discover_dsh(self._dsh_runtime.path, self.store.directory / 'dsh/runtime')['path']
                if not runtime:
                    raise RuntimeError('未找到 DeepSeek Harness 运行时，请到设置 → Agent → DeepSeek Harness 选择路径或下载运行时。')
                own = self._dsh_own(record)
                record.dsh_own_config = own
                managed = self.store.directory / 'dsh/profiles' / record.key
                home = None if own else Path(getattr(record, 'dsh_home', '') or managed)
                session_root = Path(getattr(record, 'dsh_session_root', '') or (home or managed) / 'sessions')
                record.dsh_session_root = str(session_root)
                server = self.private_server
                if not own and (server is None or server.closed is True):
                    raise RuntimeError('Umeko 内部 API 代理不可用，请重新启动 Umeko 后重试。')
                patch, credentials = profile_configuration(self.store.data['providers'], record.provider, record.model,
                    self.store.data['agent']['maxTokens'], self.store.data['agent'].get('toolPermissionMode', 'auto'),
                    self.root / 'runtime/dsh-permissions.mjs', own_config=own, session_root=session_root,
                    proxy_url=f'http://127.0.0.1:{server.port}/v1' if not own else '',
                    proxy_token=self.private_token if not own else '')
                overlay = session_root.parent / 'umeko.patch.json' if own else home / 'profiles/acp/cordis.patch.yml'
                overlay.parent.mkdir(parents=True, exist_ok=True)
                overlay.write_text(json.dumps(patch, ensure_ascii=False), encoding='utf-8')
                workspace = Path(record.workspace) if record.workspace else self.store.directory / 'workspace'
                workspace.mkdir(parents=True, exist_ok=True)
                environment = dsh_environment(self.store.data['agent'], self.store.data['providers'], own_config=own)
                environment.update(credentials)
                payload = {'type': 'start', 'runtime': str(runtime), 'workspace': str(workspace),
                           'sessionId': getattr(record, 'acp_session_id', ''), 'action': action,
                           'config': [], 'useOwnConfig': own, **values}
                if own:
                    payload['patchFiles'] = [str(overlay)]
                else:
                    record.dsh_home = str(home)
                    payload.update(home=str(home), model={'provider': record.provider, 'id': record.model},
                                   reasoningEffort=record.reasoning_effort)
                payload['permissionMode'] = self.store.data['agent'].get('toolPermissionMode', 'auto')
                DshProcess(self._pool, record, self.root / 'runtime/dsh-acp-bridge.mjs', payload, environment)
                record.stale = False
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            self._handle_pi_event(record, {'type': 'error', 'message': str(error)})
            self._handle_pi_event(record, {'type': 'dsh_done', 'stopReason': 'error'})
            return False
        self.chatChanged.emit()
        return True

    def _send(self, text, steering=False):
        record = self._view
        if not is_dsh(record):
            return super()._send(text, steering)
        if steering:
            self.toast.emit('DeepSeek Harness 首版不支持引导；运行中请按 Enter 将消息加入队列。')
            return False
        text = attachment_prompt(text.strip(), record.attachments)
        if not text:
            return False
        record.attachments, record.draft = [], ''
        self.attachmentsChanged.emit()
        self.editorText.emit('')
        if record.busy:
            record.queue.append({'id': uuid.uuid4().hex, 'text': text, 'mode': 'followUp'})
            self.chatChanged.emit()
            return True
        return self._dsh_prompt(record, text)

    def _dsh_prompt(self, record, text):
        if not record.id:
            record.dsh_own_config = self._dsh_runtime.useOwnConfig
            record.id = 'dsh-' + record.key
        if not record.messages:
            record.title = ' '.join(text.split())[:28]
        interrupted = getattr(record, 'dsh_interruption_pending', False)
        record.dsh_prompt_has_interruption = interrupted
        if interrupted:
            self._dsh_interruption_notice(record)
        record.messages.extend([{'role': 'user', 'text': text, 'error': False},
                                {'role': 'assistant', 'text': '', 'error': False}])
        record.optimistic_user = True
        record.body_dirty = True
        self._save_dsh(record)
        return self._command_dsh('prompt', record, text=text,
                                 interruptionNotice=INTERRUPTION_NOTICE if interrupted else '')

    def _dsh_interruption_notice(self, record):
        if record.messages and record.messages[-1].get('customType') == 'umeko-dsh-interruption':
            return
        record.messages.append({'role': 'status', 'customType': 'umeko-dsh-interruption',
                                'text': INTERRUPTION_STATUS, 'error': False})
        record.body_dirty = True

    def _write_pi(self, payload, record=None):
        record = record or self._view
        if is_dsh(record) and payload.get('type') in ('edit-queue', 'delete-queue', 'steer-queued', 'promote-queue'):
            kind = payload['type']
            if kind in ('steer-queued', 'promote-queue'):
                self.toast.emit('DeepSeek Harness 的排队消息会在当前任务结束后发送。')
                return
            row = next((row for row in record.queue if row['id'] == payload['id']), None)
            if row:
                record.queue.remove(row)
                if kind == 'edit-queue':
                    self._restore_queued(record, [row['text']])
                self.chatChanged.emit()
            return
        return super()._write_pi(payload, record)

    def _stop(self):
        record = self._view
        if not is_dsh(record):
            return super()._stop()
        if record.busy:
            record.cancelled = True
            # Keep the host's Stop intent across a real application restart.
            record.dsh_interruption_pending = True
            self._save_dsh(record)
            self._pool.write(record, {'type': 'cancel'})
            record.approval = {}
            self.approvalChanged.emit()
            self.chatChanged.emit()

    def _dsh_selection(self, record):
        """Use opaque values advertised by ACP, rather than manufacturing them."""
        options = getattr(record, 'dsh_options', [])
        selected = []
        for option in options:
            target = (None if self._dsh_own(record) else record.model) if option.get('category') == 'model' or option.get('id') == 'model' else record.reasoning_effort if option.get('id') == 'reasoning_effort' else None
            if target is None:
                continue
            choices = option.get('options', [])
            choices = [child for choice in choices for child in choice.get('options', [choice])]
            for choice in choices:
                value = choice.get('value')
                try:
                    parsed = json.loads(value)
                except (ValueError, TypeError):
                    parsed = None
                if value == target or parsed == [record.provider, target]:
                    selected.append({'configId': option['id'], 'value': value})
                    break
        return selected

    def _dsh_efforts(self, record):
        option = next((o for o in getattr(record, 'dsh_options', []) if o['id'] == 'reasoning_effort'), {})
        return [o['value'] for o in option.get('options', []) if o['value'] != 'off']

    def _switch_dsh_config(self):
        record = self._view
        if record.process and record.ready and not record.busy:
            for option in self._dsh_selection(record):
                self._pool.write(record, {'type': 'set_config', **option})
        elif record.process:
            record.stale = True
        self._save_dsh(record)

    def _handle_pi_event(self, record, event):
        if not is_dsh(record):
            return super()._handle_pi_event(record, event)
        if self._closing:
            return
        kind = event.get('type')
        if kind in ('dsh_session', 'dsh_config'):
            if event.get('sessionId'):
                record.acp_session_id = event['sessionId']
            record.dsh_options = event.get('configOptions', getattr(record, 'dsh_options', []))
            self._index_record(record)
            self._save_dsh(record)
            self.reasoningDetectionChanged.emit()
            self.reasoningChanged.emit()
        elif kind == 'dsh_ready':
            record.ready = True
            record.tool_status = '正在生成' if record.action == 'prompt' else ''
        elif kind in ('dsh_done', 'exit'):
            if event.get('stopReason') == 'max_tokens':
                self._handle_pi_event(record, {'type': 'error',
                    'message': 'DeepSeek Harness 达到本轮输出上限，请缩短任务或调整输出上限后再发送。'})
                if record.messages and record.messages[-1].get('role') == 'assistant':
                    record.messages[-1]['stopReason'] = 'length'
            stopped = record.cancelled or event.get('stopReason') == 'cancelled'
            record.cancelled = stopped
            self._finish_turn(record, failed=record.failed or kind == 'exit')
            record.phase, record.prompt_started, record.tool_status, record.approval = 'idle', None, '', {}
            if kind == 'exit':
                record.ready = False
            if stopped and record.messages and record.messages[-1].get('role') == 'assistant':
                record.messages[-1]['stopReason'] = 'aborted'
                # The optimistic placeholder has no content to preserve. Keep
                # partial thinking and tools, but never render an empty reply.
                if not any(record.messages[-1].get(field) for field in ('text', 'thinking', 'tools')):
                    record.messages.pop()
            if stopped:
                record.dsh_interruption_pending = True
                self._dsh_interruption_notice(record)
            elif (record.action == 'prompt' and getattr(record, 'dsh_prompt_has_interruption', False)
                  and not record.failed and kind != 'exit'):
                record.dsh_interruption_pending = False
            self._save_dsh(record)
            self.approvalChanged.emit()
            if record.queue and not stopped and not record.failed and kind != 'exit':
                queued = record.queue.pop(0)
                QTimer.singleShot(0, lambda: self._dsh_prompt(record, queued['text']))
            elif record.queue:
                self._restore_queued(record, [row['text'] for row in record.queue])
                record.queue = []
        else:
            if kind == 'context_usage':
                name = self._dsh_current_model(record)[1] if self._dsh_own(record) else record.model
                event = {**event, 'usage': {**event.get('usage', {}), 'model': name}}
            elif kind == 'ui_request':
                event = {**event, 'backend': 'dsh'}
            super()._handle_pi_event(record, event)
            if kind == 'tool' and isinstance(event.get('args'), dict):
                from .transcripts import tool_view
                tool = next((tool for row in record.messages for tool in row.get('tools', [])
                             if tool['id'] == event['id']), None)
                if tool is not None:
                    view = tool_view(event['id'], event['name'], event['args'], record.workspace)
                    tool.update(arguments=view['arguments'], path=view['path'])
            if kind in ('delta', 'thinking_delta', 'tool', 'error'):
                self._save_dsh(record)
            return
        self.chatChanged.emit()
