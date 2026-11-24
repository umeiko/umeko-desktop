"""Opt-in real SSH acceptance, called only by --remote-environments-smoke.

The provider is a local scripted SSE server. Gateway, Pi, tools, transport,
remote exec-server, command processes, file transfer and QML remain real.
"""
from __future__ import annotations

import json
import os
import shlex
import signal
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class ScriptedModel:
    def __init__(self):
        self.current = None
        self.result = None
        self.requests = 0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests += 1
                call = owner.current
                assert self.path == '/v1/chat/completions', self.path
                last_user = next((message.get('content', '') for message in reversed(body['messages'])
                                  if message.get('role') == 'user'), '')
                active = call and f"Execute acceptance step {call['id']}" in str(last_user)
                results = [m for m in body['messages']
                           if active and m.get('role') == 'tool' and m.get('tool_call_id') == call['id']]
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()

                def emit(delta, finish=None):
                    chunk = {'id': 'chatcmpl-remote-fixture', 'object': 'chat.completion.chunk',
                             'created': 1, 'model': 'test-model',
                             'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}
                    self.wfile.write(('data: ' + json.dumps(chunk) + '\n\n').encode())
                    self.wfile.flush()

                emit({'role': 'assistant'})
                if not active:
                    emit({'content': 'LOCAL_FIXTURE_IDLE'})
                    emit({}, 'stop')
                elif results:
                    owner.result = results[-1].get('content')
                    emit({'content': 'REMOTE_ACCEPTANCE_STEP_COMPLETE'})
                    emit({}, 'stop')
                else:
                    tools = {t.get('function', {}).get('name') for t in body.get('tools', [])}
                    assert call['name'] in tools, ('Real Pi tool missing', call['name'], tools)
                    emit({'tool_calls': [{'index': 0, 'id': call['id'], 'type': 'function',
                                           'function': {'name': call['name'], 'arguments': ''}}]})
                    # Real streaming argument assembly rather than one complete JSON response.
                    arguments = json.dumps(call['arguments'])
                    for start in range(0, len(arguments), 97):
                        emit({'tool_calls': [{'index': 0, 'function': {'arguments': arguments[start:start + 97]}}]})
                    emit({}, 'tool_calls')
                self.wfile.write(b'data: [DONE]\n\n')
                self.wfile.flush()

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def decode_result(value):
    """Unwrap the text content returned by the real Pi tool protocol."""
    if isinstance(value, str):
        try:
            return decode_result(json.loads(value))
        except ValueError:
            return value
    if isinstance(value, list):
        text = '\n'.join(v.get('text', '') for v in value if isinstance(v, dict) and v.get('type') == 'text')
        return decode_result(text) if text else value
    if isinstance(value, dict) and isinstance(value.get('content'), list) and 'action' not in value:
        return decode_result(value['content'])
    return value


class Acceptance:
    def __init__(self, app, engine, backend, spec):
        self.app, self.engine, self.backend, self.spec = app, engine, backend, spec
        self.directory = Path(spec['runDir'])
        self.model = ScriptedModel()
        self.steps, self.states = [], []
        self.ui_states = []
        self.sequence = 0
        self.long_output = ''
        self.long_started = None
        self.tool_rows = []
        self.backend.remoteEnvironmentsChanged.connect(self.state_changed)

    def state_changed(self):
        from PySide6.QtCore import QTimer
        # Observe an actual state signal after its QML bindings have updated.
        QTimer.singleShot(0, self.observe_state)

    def note(self, event, **data):
        row = {'event': event, 'elapsed': round(time.monotonic() - self.started, 3), **data}
        with (self.directory / 'events.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
        print('REMOTE_REAL ' + json.dumps(row, ensure_ascii=False), flush=True)

    def wait(self, predicate, seconds, label):
        from PySide6.QtTest import QTest
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return
            QTest.qWait(40)
            time.sleep(.005)
        raise AssertionError('Timed out: ' + label)

    def observe_state(self):
        rows = self.backend.remoteEnvironments
        state = next((r.get('state') for r in rows if r.get('name') == 'acceptance'), None)
        if state and (not self.states or self.states[-1]['state'] != state):
            self.states.append({'state': state, 'at': time.monotonic()})
            self.note('remote-state', state=state)
        pending = [self.engine.rootObjects()[0].contentItem()]
        while pending:
            item = pending.pop()
            if item.objectName() == 'remoteEnvironmentState_acceptance':
                displayed = item.property('connectionState')
                if displayed and (not self.ui_states or self.ui_states[-1]['state'] != displayed):
                    self.ui_states.append({'state': displayed, 'text': item.property('text'), 'at': time.monotonic()})
                    self.note('qml-remote-state', state=displayed)
                break
            pending.extend(item.childItems())

    def call(self, name, arguments, timeout=240, label=None):
        self.sequence += 1
        identity = f'remote-real-{self.sequence}'
        self.model.current = {'id': identity, 'name': name, 'arguments': arguments}
        self.model.result = None
        self.note('tool-start', tool=name, label=label or arguments.get('action', arguments.get('operation')))
        assert self.backend.send('Execute acceptance step ' + identity), self.backend.lastSendError
        self.wait(lambda: self.model.result is not None and not self.backend.busy, timeout, identity)
        result = decode_result(self.model.result)
        assert isinstance(result, dict), (name, result)
        # These are the actual UI transcript rows created by controller Pi events.
        tool_rows = [tool for row in self.backend._view.messages for tool in row.get('tools', [])
                     if tool.get('id') == identity and tool.get('name') == name]
        assert tool_rows, ('No real chat tool row', name, identity)
        self.tool_rows.extend(tool_rows)
        self.steps.append({'id': identity, 'tool': name, 'label': label, 'result': result})
        self.note('tool-finish', tool=name, status=result.get('status'), exitCode=result.get('exitCode'))
        return result

    def command(self, command, **extra):
        return self.call('remote_command', {'action': 'run', 'environment': 'acceptance',
                         'command': command, 'yieldMs': 1000, **extra})

    def python(self, source):
        executable = self.spec.get('remotePython', 'python' if self.spec['platform'] == 'windows' else 'python3')
        # base64 is command quoting, not a checksum or payload proof.
        import base64
        preamble = "import sys\nsys.stdout.reconfigure(encoding='utf-8',newline='\\n')\nsys.stderr.reconfigure(encoding='utf-8',newline='\\n')\n"
        encoded = base64.b64encode((preamble + source).encode()).decode()
        script = f"import base64;exec(base64.b64decode('{encoded}'))"
        if self.spec['platform'] == 'windows':
            launcher = "& '" + executable.replace("'", "''") + "'" if ' ' in executable else executable
            return launcher + ' -u -c "' + script + '"'
        return shlex.quote(executable) + ' -u -c ' + shlex.quote(script)

    def read_until_complete(self, initial, timeout=240):
        result, output = initial, initial.get('output', '')
        deadline = time.monotonic() + timeout
        while result.get('status') == 'running':
            assert time.monotonic() < deadline, result
            result = self.call('remote_command', {'action': 'read', 'environment': 'acceptance',
                               'sessionId': initial['sessionId'], 'yieldMs': 10000, 'maxOutputBytes': 262144})
            output += result.get('output', '')
        return result, output

    def run(self):
        self.started = time.monotonic()
        b = self.backend
        self.note('begin', platform=self.spec['platform'], host=self.spec['host'])
        toasts = []
        capture_toast = toasts.append
        b.toast.connect(capture_toast)
        try:
            saved = b.saveProvider('', 'Test provider', 'openai',
                                   f'http://127.0.0.1:{self.model.server.server_port}/v1', 'fixture-only',
                                   json.dumps([{'upstream': 'test-model', 'alias': 'test-model',
                                                'reasoningLevelsAuto': False, 'reasoningFormatAuto': False,
                                                'reasoningLevels': [], 'reasoningFormat': 'openai'}]))
            assert saved, toasts
        finally:
            b.toast.disconnect(capture_toast)
        provider = next(p for p in b.store.data['providers'] if p['name'] == 'Test provider')
        b.selectModel(provider['id'], 'test-model')
        b.setToolPermissionMode('auto')
        self.wait(lambda: not b.busy, 90, 'Pi fixture startup')
        added = self.call('umeko_desktop', {'operation': 'remote-environments.add', 'arguments': {
            'name': 'acceptance', 'host': self.spec['host'], 'platform': self.spec['platform']}})
        assert added.get('ok'), added
        tested = self.call('umeko_desktop', {'operation': 'remote-environments.test', 'arguments': {'name': 'acceptance'}},
                           timeout=self.spec.get('bootstrapTimeout', 240))
        assert tested.get('ok'), tested
        ssh_client = Path(tested['sshClient']).resolve()
        if self.spec.get('expectedSshExecutable'):
            assert ssh_client == Path(self.spec['expectedSshExecutable']).resolve(), tested
        clients = self.directory / 'ssh-control/clients.jsonl'
        started_clients = [json.loads(line) for line in clients.read_text(encoding='utf-8').splitlines()]
        assert started_clients and all(Path(row['executable']).resolve() == ssh_client for row in started_clients)
        self.note('ssh-client-selected', executable=str(ssh_client))
        short, output = self.read_until_complete(self.command(self.python("print('REMOTE_SHORT_OK')")))
        assert short.get('exitCode') == 0 and output == 'REMOTE_SHORT_OK\n', (short, output)

        interactive = self.command(self.python("print('PROMPT',flush=True)\ns=input()\nprint('ECHO:'+s,flush=True)"))
        assert interactive.get('status') == 'running', interactive
        reply = self.call('remote_command', {'action': 'write', 'environment': 'acceptance',
                          'sessionId': interactive['sessionId'], 'input': 'acceptance-input\n', 'yieldMs': 1000})
        final, tail = self.read_until_complete(reply)
        assert final.get('exitCode') == 0 and interactive.get('output', '') + tail == 'PROMPT\nECHO:acceptance-input\n'

        remote = self.spec['remoteDirectory']
        upload = self.call('remote_files', {'action': 'upload', 'environment': 'acceptance',
                           'localPath': str(self.directory / 'payload'), 'path': remote},
                           timeout=self.spec.get('uploadTimeout', 900))
        assert not upload.get('error') and upload.get('ok', True), upload
        download = self.call('remote_files', {'action': 'download', 'environment': 'acceptance',
                             'path': remote, 'localPath': str(self.directory / 'download')},
                             timeout=self.spec.get('downloadTimeout', 900))
        assert not download.get('error') and download.get('ok', True), download
        self.compare_payload()

        text_path = remote + '/acceptance.txt'
        text = 'REMOTE_FILE_TEXT\nUnicode: \u4f60\u597d\n'
        self.call('remote_files', {'action': 'write', 'environment': 'acceptance', 'path': text_path, 'content': text})
        read = self.call('remote_files', {'action': 'read', 'environment': 'acceptance', 'path': text_path})
        assert read.get('content') == text, read
        listing = self.call('remote_files', {'action': 'list', 'environment': 'acceptance', 'path': remote})
        assert any(row.get('name') == 'acceptance.txt' for row in listing.get('entries', [])), listing
        found = self.call('remote_files', {'action': 'search', 'environment': 'acceptance', 'path': text_path,
                         'query': 'REMOTE_FILE_TEXT'})
        assert any(row.get('line') == 1 and row.get('text') == 'REMOTE_FILE_TEXT' for row in found.get('matches', [])), found

        # Start after transfer so even a slow lab link cannot consume the
        # twenty-minute producer before the deliberate disconnect happens.
        seconds = self.spec['longSeconds']
        source = ("import os,time\npid=os.getpid()\nprint('START:'+str(pid),flush=True)\n"
                  f"for i in range({seconds}):\n print('TICK:'+str(i).zfill(4),flush=True)\n time.sleep(1)\n"
                  "print('DONE:'+str(pid),flush=True)\n")
        self.long_started = time.monotonic()
        long = self.command(self.python(source))
        assert long.get('status') == 'running', long
        self.long_output += long.get('output', '')
        session = long['sessionId']

        # Drop only the SSH client owned by this test; exec-server and the long
        # detached command stay alive. The shim rejects reconnects for >2 minutes.
        control = self.directory / 'ssh-control'
        launches = [json.loads(line) for line in (control / 'clients.jsonl').read_text().splitlines()]
        candidates = [r for r in launches if r.get('tunnel') and self.pid_alive(r['pid'])]
        assert len(candidates) == 1, ('Expected one owned SSH tunnel', candidates)
        (control / 'blocked').write_text('acceptance fault injection\n')
        killed = candidates[0]['pid']
        os.kill(killed, signal.SIGTERM)
        self.note('ssh-client-killed', pid=killed)
        released = threading.Event()

        def restore():
            time.sleep(self.spec['outageSeconds'])
            (control / 'blocked').unlink(missing_ok=True)
            released.set()

        threading.Thread(target=restore, daemon=True).start()
        recovered = self.call('remote_command', {'action': 'read', 'environment': 'acceptance',
                              'sessionId': session, 'yieldMs': 1000, 'maxOutputBytes': 262144}, timeout=300,
                              label='read across >2 minute SSH outage')
        assert released.is_set(), 'Read returned before the transport outage ended'
        self.long_output += recovered.get('output', '')
        assert any(r['state'] in ('reconnecting', 'connecting', 'retrying') for r in self.states), self.states
        assert self.states[-1]['state'] in ('connected', 'ready'), self.states
        assert any(r['state'] == 'reconnecting' for r in self.ui_states), ('QML never bound reconnect state', self.ui_states)
        assert self.ui_states[-1]['state'] == 'connected', self.ui_states

        nearby, failed_output = self.read_until_complete(self.command(self.python(
            "import sys\nprint('NEARBY_FAILURE_STDOUT')\nprint('NEARBY_FAILURE_STDERR',file=sys.stderr)\nsys.exit(7)")))
        assert nearby.get('exitCode') == 7 and 'NEARBY_FAILURE_STDOUT' in failed_output and 'NEARBY_FAILURE_STDERR' in failed_output
        from PySide6.QtTest import QTest
        while recovered.get('status') == 'running':
            assert time.monotonic() - self.long_started < seconds + 180, '20 minute command exceeded deadline'
            # Allow several output lines to accumulate per turn so the long
            # command stays inside the fixture's live chat transcript window.
            QTest.qWait(30000)
            recovered = self.call('remote_command', {'action': 'read', 'environment': 'acceptance',
                                  'sessionId': session, 'yieldMs': 10000, 'maxOutputBytes': 262144}, timeout=90)
            self.long_output += recovered.get('output', '')
        assert recovered.get('exitCode') == 0, recovered
        lines = self.long_output.splitlines()
        assert lines and lines[0].startswith('START:'), self.long_output
        pid = int(lines[0].split(':')[1])
        expected = f'START:{pid}\n' + ''.join(f'TICK:{i:04d}\n' for i in range(seconds)) + f'DONE:{pid}\n'
        assert self.long_output == expected, ('Lost, duplicated or reordered output', len(self.long_output), len(expected))
        assert time.monotonic() - self.long_started >= seconds, 'Long command did not actually run for requested duration'
        (self.directory / 'long-command-output.txt').write_text(self.long_output, encoding='utf-8')
        (self.directory / 'chat-tool-rows.json').write_text(json.dumps(self.tool_rows, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        self.note('passed', commandPid=pid, longSeconds=seconds, payloadBytes=self.spec['payloadBytes'],
                  outageSeconds=self.spec['outageSeconds'], actualModelRequests=self.model.requests)
        return {'ok': True, 'commandPid': pid, 'longSeconds': seconds, 'payloadBytes': self.spec['payloadBytes'],
                'outageSeconds': self.spec['outageSeconds'], 'states': self.states, 'qmlStates': self.ui_states, 'steps': self.steps,
                'scope': 'offscreen real gateway/Pi/tools/SSH/exec-server; scripted local model; no upstream model'}

    @staticmethod
    def pid_alive(pid):
        if os.name == 'nt':
            # os.kill(pid, 0) terminates processes on Windows; query the handle.
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            code = wintypes.DWORD()
            try:
                return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
            finally:
                kernel.CloseHandle(handle)
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def compare_payload(self):
        source, destination = self.directory / 'payload', self.directory / 'download'
        files = sorted(p.relative_to(source) for p in source.rglob('*') if p.is_file())
        actual = sorted(p.relative_to(destination) for p in destination.rglob('*') if p.is_file())
        assert actual == files, ('Directory file set differs', len(actual), len(files))
        total = 0
        for relative in files:
            with (source / relative).open('rb') as a, (destination / relative).open('rb') as b:
                while True:
                    expected, received = a.read(1024 * 1024), b.read(1024 * 1024)
                    assert expected == received, 'Byte mismatch: ' + str(relative)
                    total += len(expected)
                    if not expected:
                        break
        assert total == self.spec['payloadBytes'], (total, self.spec['payloadBytes'])
        self.note('transfer-byte-equality', files=len(files), bytes=total)


def start(app, engine, controller, spec_path):
    """Schedule acceptance on the real application event loop and exit on result."""
    from PySide6.QtCore import QTimer
    spec = json.loads(Path(spec_path).read_text(encoding='utf-8'))
    directory = Path(spec['runDir']).resolve()
    assert Path(os.environ['UMEKO_DATA_DIR']).resolve() == directory / 'profile'
    assert os.environ.get('QT_QPA_PLATFORM') == 'offscreen'

    def run():
        acceptance = None
        try:
            acceptance = Acceptance(app, engine, controller, spec)
            result = acceptance.run()
            status = 0
        except BaseException:
            result = {'ok': False, 'error': traceback.format_exc()}
            print(result['error'], flush=True)
            status = 1
        finally:
            if acceptance:
                acceptance.model.close()
        (directory / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        controller.close()
        app.exit(status)

    QTimer.singleShot(0, run)
