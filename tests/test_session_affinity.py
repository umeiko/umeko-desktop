"""Observe conversation routing headers at a disposable HTTP upstream."""
import copy
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')

from PySide6.QtCore import QCoreApplication
from app.gateway import Gateway, LocalServer
from app.integration import UnconfiguredAdapter
from app.pi_runtime import RELEASE_NAME, node_executable
from app.request_headers import DEFAULTS
from app.storage import Store

ROOT = Path(__file__).resolve().parents[1]


def affinity_for(session_id):
    return hashlib.sha256(session_id.encode('utf-8')).hexdigest()[:32]


class SessionAffinityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='conversation-routing-')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.calls = []
        self.delegate = False
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                headers = {key.lower(): value for key, value in self.headers.items()}
                fixture.calls.append((self.path, headers, body))
                messages = body.get('messages', [])
                child = any('notify_parent' in str(message.get('content', ''))
                            for message in messages if message.get('role') in ('system', 'developer'))
                already_delegated = any(message.get('tool_calls') for message in messages)
                message = {'role': 'assistant', 'content': 'fixture answer'}
                finish = 'stop'
                if fixture.delegate and not child and not already_delegated:
                    message = {'role': 'assistant', 'content': None, 'tool_calls': [{
                        'id': 'fixture-child', 'type': 'function', 'function': {
                            'name': 'subagent', 'arguments': json.dumps({
                                'prompt': 'fixture child task', 'description': 'Fixture child',
                                'subagent_type': 'general-purpose', 'run_in_background': False})}}]}
                    finish = 'tool_calls'
                if self.path.endswith('/messages'):
                    data = {'id': 'fixture', 'type': 'message', 'role': 'assistant',
                            'content': [{'type': 'text', 'text': 'fixture answer'}],
                            'stop_reason': 'end_turn', 'usage': {}}
                elif self.path.endswith('/responses'):
                    data = {'id': 'fixture', 'object': 'response', 'status': 'completed',
                            'output': [{'type': 'message', 'role': 'assistant', 'content': [
                                {'type': 'output_text', 'text': 'fixture answer'}]}], 'usage': {}}
                else:
                    data = {'id': 'fixture', 'object': 'chat.completion', 'model': 'fixture-model',
                            'choices': [{'index': 0, 'message': message, 'finish_reason': finish}],
                            'usage': {'prompt_tokens': 1, 'completion_tokens': 1}}
                encoded = json.dumps(data).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        self.upstream = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.upstream.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_upstream)
        self.store = Store(self.path / 'profile')
        self.provider = {'id': 'fixture-provider', 'name': 'Fixture', 'api': 'openai',
                         'baseUrl': f'http://127.0.0.1:{self.upstream.server_port}/v1',
                         'key': 'fixture-key', 'proxy': {'mode': 'direct'},
                         'models': [{'upstream': 'fixture-model', 'alias': 'fixture-model'}]}
        self.store.data.update(providers=[self.provider], selectedProvider='fixture-provider',
                               selectedModel='fixture-model')
        self.store.data['requestHeaders'] = copy.deepcopy(DEFAULTS) + [
            {'id': 'fixture-project', 'name': 'X-Fixture-Project', 'value': 'fixture-value', 'enabled': True}]
        self.gateway = Gateway(self.store, UnconfiguredAdapter())
        self.private = LocalServer(self.gateway, 0, 'fixture-token', private=True)
        self.addCleanup(self.private.close)

    def close_upstream(self):
        self.upstream.shutdown()
        self.upstream.server_close()
        self.thread.join(timeout=3)

    def assert_call(self, call, affinity):
        _, headers, body = call
        if affinity is None:
            self.assertNotIn('x-session-affinity', headers)
        else:
            self.assertEqual(headers.get('x-session-affinity'), affinity)
        self.assertEqual(headers.get('x-fixture-project'), 'fixture-value')
        self.assertNotIn('_umeko_session_affinity', json.dumps(body))
        self.assertNotIn('x-session-affinity', json.dumps(body))

    def test_protocols_stable_sessions_and_unscoped_requests_on_wire(self):
        for protocol in ('chat', 'responses'):
            with self.subTest(protocol=protocol):
                self.provider['wireApi'] = 'responses' if protocol == 'responses' else ''
                for affinity in ('a' * 32, 'a' * 32, 'b' * 32, None):
                    parameters = {} if affinity is None else {'_umeko_session_affinity': affinity}
                    list(self.gateway.events('fixture-model', [{'role': 'user', 'content': 'fixture'}],
                                             parameters=parameters))
                    self.assert_call(self.calls[-1], affinity)
                    suffix = '/responses' if protocol == 'responses' else '/chat/completions'
                    self.assertTrue(self.calls[-1][0].endswith(suffix))

    def test_anthropic_omits_affinity_and_preserves_user_headers(self):
        self.provider['api'] = 'anthropic'
        list(self.gateway.events('fixture-model', [{'role': 'user', 'content': 'fixture'}],
                                 parameters={'_umeko_session_affinity': 'a' * 32}))
        self.assert_call(self.calls[-1], None)
        self.assertTrue(self.calls[-1][0].endswith('/messages'))

    def private_call(self, affinity):
        headers = {'Authorization': 'Bearer fixture-token', 'Content-Type': 'application/json'}
        if affinity is not None:
            headers['x-session-affinity'] = affinity
        body = {'model': 'fixture-model', 'messages': [{'role': 'user', 'content': 'fixture'}]}
        request = Request(f'http://127.0.0.1:{self.private.port}/v1/chat/completions',
                          data=json.dumps(body).encode(), headers=headers)
        with urlopen(request, timeout=10) as response:
            response.read()

    def test_private_ingress_accepts_only_lowercase_32_hex(self):
        for value in ('c' * 32, None):
            with self.subTest(value=value):
                self.private_call(value)
                self.assert_call(self.calls[-1], value)
        for value in ('C' * 32, 'z' * 32, 'c' * 31):
            with self.subTest(value=value):
                before = len(self.calls)
                with self.assertRaises(HTTPError) as caught:
                    self.private_call(value)
                self.assertEqual(caught.exception.code, 400)
                self.assertEqual(len(self.calls), before)

    def bridge(self, directory):
        directory.mkdir(parents=True)
        process = subprocess.Popen(
            [node_executable(), str(ROOT / 'runtime/releases' / RELEASE_NAME / 'bridge.mjs')],
            cwd=directory, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8',
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        events, errors = queue.Queue(), []
        threading.Thread(target=lambda: [events.put(json.loads(line)) for line in process.stdout
                                        if line.startswith('{')], daemon=True).start()
        threading.Thread(target=lambda: errors.extend(process.stderr.readlines()), daemon=True).start()

        def send(payload):
            process.stdin.write(json.dumps(payload) + '\n')
            process.stdin.flush()

        def stop():
            if process.poll() is None:
                send({'type': 'shutdown'})
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
        self.addCleanup(stop)

        def command(payload):
            send(payload)
            output = []
            while True:
                try:
                    event = events.get(timeout=30)
                except queue.Empty:
                    self.fail('Fixture bridge timed out: ' + ''.join(errors))
                output.append(event)
                if event.get('type') == 'ui_request':
                    send({'type': 'ui_response', 'id': event['id'], 'value': True})
                if event.get('type') == 'done':
                    self.assertFalse([entry for entry in output if entry.get('type') == 'error'], output)
                    return output
        payload = {'type': 'prompt', 'text': 'fixture prompt',
                   'gateway': f'http://127.0.0.1:{self.private.port}/', 'token': 'fixture-token',
                   'model': 'fixture-model', 'models': self.gateway.models(), 'workspace': str(directory),
                   'defaultCwd': str(directory), 'agentDir': str(directory / 'agent'),
                   'sessionDir': str(directory / 'sessions'), 'agent': {'safeMode': True}}
        return command, payload

    def test_real_bridge_two_turns_and_separate_conversation(self):
        command, payload = self.bridge(self.path / 'first')
        events = command(payload)
        session_id = next(event['session']['id'] for event in events if event.get('type') == 'ready')
        first = self.calls[-1][1].get('x-session-affinity')
        self.assertEqual(first, affinity_for(session_id))
        command({'type': 'prompt', 'text': 'fixture follow-up'})
        self.assert_call(self.calls[-1], first)
        other, payload = self.bridge(self.path / 'second')
        events = other(payload)
        session_id = next(event['session']['id'] for event in events if event.get('type') == 'ready')
        second = self.calls[-1][1].get('x-session-affinity')
        self.assertEqual(second, affinity_for(session_id))
        self.assertNotEqual(first, second)

    def test_real_subagent_owns_distinct_conversation(self):
        self.delegate = True
        command, payload = self.bridge(self.path / 'delegation')
        events = command(payload)
        parent_id = next(event['session']['id'] for event in events if event.get('type') == 'ready')
        child_calls, parent_calls = [], []
        for call in self.calls:
            messages = call[2].get('messages', [])
            child = any('notify_parent' in str(message.get('content', '')) for message in messages
                        if message.get('role') in ('system', 'developer'))
            (child_calls if child else parent_calls).append(call)
        self.assertTrue(child_calls, 'Fixture must reach a real child model request')
        self.assertGreaterEqual(len(parent_calls), 2)
        parent = parent_calls[0][1].get('x-session-affinity')
        child = child_calls[0][1].get('x-session-affinity')
        self.assertEqual(parent, affinity_for(parent_id))
        child_ids = []
        for path in (self.path / 'delegation').rglob('*.jsonl'):
            with path.open(encoding='utf-8') as stream:
                header = json.loads(stream.readline())
            if header.get('type') == 'session' and header.get('id') != parent_id:
                child_ids.append(header['id'])
        self.assertIn(child, [affinity_for(value) for value in child_ids])
        self.assertNotEqual(parent, child)
        for call in parent_calls:
            self.assert_call(call, parent)
        for call in child_calls:
            self.assert_call(call, child)

    def test_plugin_acquired_conversations_use_real_native_requests(self):
        from tests import test_plugin_sessions as fixtures
        helper = fixtures.PluginSessionTests('runTest')
        helper.app = self.app
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        helper.command_patch.stop()
        helper.b.store.data.update(providers=[copy.deepcopy(self.provider)],
                                  selectedProvider='fixture-provider', selectedModel='fixture-model',
                                  requestHeaders=copy.deepcopy(self.store.data['requestHeaders']))
        helper.b.store.data['pluginSessionProfiles']['fixture-channel']['tasks'].update(
            model='fixture-model', provider='fixture-provider')
        one = helper.acquire('fixture-first')
        two = helper.acquire('fixture-second')
        values = []
        for index, owned in enumerate((one, one, two)):
            before = len(self.calls)
            run = helper.result('sessions.submit', {'handle': owned['handle'],
                                'requestId': f'fixture-{index}', 'content': 'fixture prompt'})
            terminal = helper.result('sessions.wait', {'handle': owned['handle'], 'runId': run['runId']})
            self.assertEqual(terminal['status'], 'completed', terminal)
            self.assertGreater(len(self.calls), before)
            value = self.calls[-1][1].get('x-session-affinity')
            self.assertEqual(value, affinity_for(owned['sessionId']))
            self.assert_call(self.calls[-1], value)
            values.append(value)
        self.assertEqual(values[0], values[1])
        self.assertNotEqual(values[0], values[2])


if __name__ == '__main__':
    unittest.main()
