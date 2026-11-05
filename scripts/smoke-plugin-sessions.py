"""Offline application plugin -> host service -> real Pi -> native session smoke.

Uses a temporary profile, an actual SDK worker and a loopback SSE provider. There
is no window, external model, account, credential or desktop input interaction.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_QUICK_BACKEND'] = 'software'

from PySide6.QtCore import QCoreApplication
from test_plugin_sessions import controller, isolated_settings, pump_until

PLUGIN = r'''
import json, threading
from umeko_plugin_sdk import Plugin

class Channel(Plugin):
    def __init__(self, context):
        super().__init__(context)
        self.events = []
        self.approval_decision = None
        self.approval_answers = []
    def handle(self, method, args):
        if method == 'events': return list(self.events)
        if method == 'approvalAnswers': return list(self.approval_answers)
        if method == 'approvalPolicy':
            self.approval_decision = args['decision']
            return {'decision': self.approval_decision}
        job = args['job']
        def invoke():
            try:
                api = self.context.sessions
                result = getattr(api, args['action'])(*args.get('positional', []), **args.get('keywords', {}))
                value = {'ok': True, 'result': result}
            except Exception as error:
                value = {'ok': False, 'error': str(error)}
            path = self.context.state_dir / (job + '.json')
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(value), encoding='utf-8')
            temporary.replace(path)
        threading.Thread(target=invoke, daemon=True).start()
        return {'job': job}
    def on_event(self, name, data):
        if name != 'sessions.event': return
        self.events.append(data)
        if data.get('type') == 'approval_request' and self.approval_decision:
            decision = self.approval_decision
            def answer():
                try:
                    response = self.context.sessions.respond_approval(data['handle'], data['requestId'], decision)
                    self.approval_answers.append({'requestId': data['requestId'], 'decision': decision, **response})
                except Exception as error:
                    self.approval_answers.append({'error': str(error), 'decision': decision})
            threading.Thread(target=answer, daemon=True).start()

def create_plugin(context): return Channel(context)
'''


def install_channel(manager):
    identifier = 'fixture-channel'
    folder = manager.root / 'packages' / identifier / '1.0.0'
    (folder / 'scripts').mkdir(parents=True, exist_ok=True)
    manifest = {'kind': 'umeko-plugin', 'apiVersion': 1, 'id': identifier,
        'name': 'Test channel', 'version': '1.0.0', 'summary': 'Offline channel',
        'description': 'Temporary offline channel fixture', 'lifecycle': 'application',
        'entrypoint': 'scripts/plugin.py:create_plugin', 'permissions': ['sessions.manage'],
        'agent': {'document': 'AGENT.md', 'methods': {}}}
    for name, content in {'manifest.json': json.dumps(manifest), 'config.json': '{}',
            'config.schema.json': '{"type":"object","properties":{},"additionalProperties":false}',
            'README.md': '# Offline channel fixture\n', 'AGENT.md': '# Temporary test interface\n',
            'scripts/plugin.py': PLUGIN}.items():
        (folder / name).write_text(content, encoding='utf-8')
    manager.entries[identifier] = {**manifest, 'builtin': False}
    manager.settings.setdefault('installed', {})[identifier] = manifest
    manager.settings.setdefault('enabled', {})[identifier] = True
    manager.save()
    manager.start(identifier)
    return identifier


def main():
    app = QCoreApplication.instance() or QCoreApplication([])
    temporary = tempfile.TemporaryDirectory(prefix='umeko-plugin-sessions-smoke-')
    base = Path(temporary.name).resolve()
    profile, workspace = isolated_settings(base)
    os.environ['UMEKO_DATA_DIR'] = str(profile)
    gates = {name: threading.Event() for name in ('hold-first', 'cancel-me')}
    received, advertised = [], []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            users = [message.get('content', '') for message in body['messages'] if message['role'] == 'user']
            content = users[-1]
            if isinstance(content, list):
                content = ''.join(part.get('text', '') for part in content)
            received.append(content)
            advertised.append({tool['function']['name'] for tool in body.get('tools', [])})
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()

            def chunk(delta, finish=None):
                value = {'id': 'fixture', 'object': 'chat.completion.chunk', 'created': 1,
                    'model': 'test-model', 'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}
                self.wfile.write(('data: ' + json.dumps(value) + '\n\n').encode())
                self.wfile.flush()

            try:
                chunk({'role': 'assistant'})
                if content in gates:
                    assert gates[content].wait(60), 'Fixture gate was never released'
                last_user = max(index for index, message in enumerate(body['messages']) if message['role'] == 'user')
                has_tool_result = any(message['role'] == 'tool' for message in body['messages'][last_user + 1:])
                if content in ('approve-plugin', 'approve-desktop') and not has_tool_result:
                    filename = 'plugin-approved.txt' if content == 'approve-plugin' else 'desktop-denied.txt'
                    chunk({'tool_calls': [{'index': 0, 'id': 'fixture-write-' + content, 'type': 'function',
                        'function': {'name': 'write', 'arguments': json.dumps({
                            'path': filename, 'content': 'plugin approval worked\n'})}}]})
                    chunk({}, 'tool_calls')
                else:
                    chunk({'content': 'reply:' + content})
                    chunk({}, 'stop')
                self.wfile.write(b'data: [DONE]\n\n')
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass  # Cancellation deliberately closes an in-flight stream.

    upstream = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    backend = None
    try:
        backend = controller()
        configured = {'id': 'test-provider', 'name': 'Test provider',
            'api': 'openai', 'baseUrl': f'http://127.0.0.1:{upstream.server_port}/v1',
            'key': 'offline-fixture-key', 'models': [{'upstream': 'test-model', 'alias': 'test-model'}]}
        backend.store.data.update(providers=[configured],
            selectedProvider='test-provider', selectedModel='test-model')
        backend.store.data['pluginSessionProfiles'] = {'fixture-channel': {'tasks': {
            'workspace': str(workspace), 'provider': 'test-provider', 'model': 'test-model',
            'tools': ['read'], 'permissionMode': 'ask'}}}
        manager = backend.desktopPlugins
        owner = install_channel(manager)
        replies = {}
        manager.response.connect(lambda key, value: replies.__setitem__(key, value))

        def call(method, args):
            key = manager.call_for(owner, method, json.dumps(args), timeout_ms=60000)
            assert key, 'Plugin worker call was rejected'
            answer = pump_until(app, lambda: replies.get(key), 'Plugin call did not reply', 60)
            assert answer['ok'], answer
            return answer['result']

        def invoke(action, *positional, **keywords):
            job = uuid.uuid4().hex
            call('invoke', {'job': job, 'action': action, 'positional': positional, 'keywords': keywords})
            path = manager.root / 'state' / owner / 'application' / (job + '.json')
            pump_until(app, path.is_file, action + ' SDK helper did not finish', 60)
            answer = json.loads(path.read_text(encoding='utf-8'))
            assert answer['ok'], answer
            return answer['result']

        selected = backend._view
        foreground_workspace = base / 'foreground-workspace'
        foreground_workspace.mkdir()
        selected.workspace, selected.model, selected.provider = str(foreground_workspace), 'foreground-model', 'foreground-provider'
        one = invoke('acquire', 'channel-one', profile='tasks')
        two = invoke('acquire', 'channel-two', profile='tasks')
        assert one['created'] and two['created']
        assert one['sessionId'] != two['sessionId']
        ids = {one['sessionId'], two['sessionId']}
        assert ids.issubset({row['id'] for row in backend.sessions})
        record = backend._pool.find(one['sessionId'])
        assert (record.workspace, record.model, record.provider) == (str(workspace), 'test-model', 'test-provider')
        invoke('subscribe', one['handle'])
        invoke('subscribe', two['handle'])
        first = invoke('submit', one['handle'], 'request-one', 'hold-first')
        pump_until(app, lambda: 'hold-first' in received, 'Real Pi never called local provider', 60)
        queued = invoke('submit', one['handle'], 'request-two', 'queued-second')
        separate = invoke('submit', two['handle'], 'request-other', 'independent')
        assert (first['disposition'], queued['disposition']) == ('started', 'queued')
        assert first['runId'] != queued['runId']
        other_done = invoke('wait', two['handle'], separate['runId'])
        assert other_done['status'] == 'completed' and 'reply:independent' in json.dumps(other_done)
        gates['hold-first'].set()
        first_done = invoke('wait', one['handle'], first['runId'])
        second_done = invoke('wait', one['handle'], queued['runId'])
        for result, text in ((first_done, 'reply:hold-first'), (second_done, 'reply:queued-second')):
            assert result['status'] == 'completed' and text in json.dumps(result), result
        events = call('events', {})
        endings = {event['runId']: event for event in events if event['type'] == 'turn_end'}
        for acquired, run in ((one, first), (one, queued), (two, separate)):
            assert endings[run['runId']]['sessionId'] == acquired['sessionId']
            assert endings[run['runId']]['handle'] == acquired['handle']
        assert 'reply:queued-second' not in json.dumps(endings[first['runId']])
        assert 'reply:hold-first' not in json.dumps(endings[queued['runId']])
        assert backend._view is selected, 'Background session stole desktop selection'
        assert all('write' not in tools and 'bash' not in tools for tools in advertised), advertised
        history = invoke('history', one['handle'])
        assert 'reply:queued-second' in json.dumps(history)
        backend._pool.retire(record)
        resumed = invoke('submit', one['handle'], 'request-resume', 'after-eviction')
        resumed_done = invoke('wait', one['handle'], resumed['runId'])
        assert resumed_done['status'] == 'completed' and 'reply:after-eviction' in json.dumps(resumed_done)
        assert record.id == one['sessionId'], 'Eviction created a replacement native chat'
        cancelled = invoke('submit', one['handle'], 'request-cancel', 'cancel-me')
        pump_until(app, lambda: 'cancel-me' in received, 'Cancellation run never reached provider', 60)
        invoke('cancel', one['handle'], cancelled['runId'])
        assert invoke('wait', one['handle'], cancelled['runId'])['status'] == 'cancelled'
        gates['cancel-me'].set()
        # Exercise actual Pi tool permission prompts through the same SDK worker.
        # The profile is host-owned; the channel chooses only a registered name.
        backend.store.data['pluginSessionProfiles'][owner]['approvals'] = {
            'workspace': str(workspace), 'provider': 'test-provider', 'model': 'test-model',
            'tools': ['read', 'write'], 'permissionMode': 'ask', 'allowApprovals': True}
        approval_session = invoke('acquire', 'approval-channel', profile='approvals')
        approval_record = backend._pool.find(approval_session['sessionId'])
        invoke('subscribe', approval_session['handle'])
        invoke('register_approval_handler', approval_session['handle'])
        call('approvalPolicy', {'decision': 'allow'})
        approved = invoke('submit', approval_session['handle'], 'request-approve', 'approve-plugin')
        approved_done = invoke('wait', approval_session['handle'], approved['runId'])
        assert approved_done['status'] == 'completed', approved_done
        assert (workspace / 'plugin-approved.txt').read_text(encoding='utf-8') == 'plugin approval worked\n'
        assert backend._view is selected, 'Plugin approval changed desktop selection'
        call('approvalPolicy', {'decision': 'unhandled'})
        desktop = invoke('submit', approval_session['handle'], 'request-desktop', 'approve-desktop')
        pending = pump_until(app, lambda: approval_record.approval, 'Unhandled approval did not reach normal desktop state', 60)
        assert backend._view is selected, 'Approval fallback changed desktop selection'
        backend._view = approval_record  # Simulate explicit user selection, no input injection.
        try:
            assert backend.pendingApproval == pending and pending['method'] == 'confirm'
            backend.respondApproval(False)
        finally:
            backend._view = selected
        desktop_done = invoke('wait', approval_session['handle'], desktop['runId'])
        assert desktop_done['status'] == 'completed', desktop_done
        assert not (workspace / 'desktop-denied.txt').exists(), 'Desktop denial still executed write'
        answers = call('approvalAnswers', {})
        assert any(row.get('decision') == 'allow' and row.get('accepted') is True for row in answers), answers
        assert any(row.get('decision') == 'unhandled' and row.get('accepted') is True for row in answers), answers
        backend.store.save()
        backend.store.data['providers'] = []
        backend.close()
        app.processEvents()
        backend = controller()
        backend.store.data.update(providers=[configured], selectedProvider='test-provider', selectedModel='test-model')
        manager = backend.desktopPlugins
        replies.clear()
        manager.response.connect(lambda key, value: replies.__setitem__(key, value))
        manager.start(owner)
        restored = invoke('acquire', 'channel-one', profile='tasks')
        assert restored['sessionId'] == one['sessionId'] and restored['created'] is False
        restored_two = invoke('acquire', 'channel-two', profile='tasks')
        assert restored_two['sessionId'] == two['sessionId'] and restored_two['created'] is False
        print('PLUGIN_SESSIONS_OK: actual SDK worker, real Pi, distinct native sessions, separate queued runs, scoped replies, cancellation, read-only ceiling, eviction resume, both restart mappings, SDK approval allow and unhandled desktop denial', flush=True)
    finally:
        for gate in gates.values():
            gate.set()
        if backend is not None:
            backend.store.data['providers'] = []
            backend.close()
            app.processEvents()
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=2)
        temporary.cleanup()


if __name__ == '__main__':
    main()
