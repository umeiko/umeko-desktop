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
        self.started = time.monotonic()
        self.steps, self.states = [], []
        self.ui_states = []
        self.outages = []
        self.active_outage = None
        self.current_tool = None
        self.injected_outage = None
        self.ssh_lifecycle = []
        self.relay_drops = []
        self.ssh_client = None
        self.sequence = 0
        self.long_output = ''
        self.long_started = None
        self.tool_rows = []
        self.backend.remoteEnvironmentsChanged.connect(self.state_changed)

    def state_changed(self):
        from PySide6.QtCore import QTimer
        # Capture every transport transition immediately. Only QML observation
        # needs deferral; deferring both can hide a short drop and recovery.
        self.observe_transport()
        # Observe an actual state signal after its QML bindings have updated.
        QTimer.singleShot(0, self.observe_state)

    def note(self, event, **data):
        row = {'event': event, 'elapsed': round(time.monotonic() - self.started, 3), **data}
        with (self.directory / 'events.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
        progress = self.evidence()
        progress.update(lastEvent=row, elapsed=row['elapsed'])
        temporary = self.directory / 'progress.json.tmp'
        temporary.write_text(json.dumps(progress, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        temporary.replace(self.directory / 'progress.json')
        print('REMOTE_REAL ' + json.dumps(row, ensure_ascii=False), flush=True)

    def evidence(self):
        return {'completedTools': len(self.steps), 'currentTool': self.current_tool,
                'commandsOnly': bool(self.spec.get('commandsOnly')),
                'fileStage': 'skipped-explicit-continuation' if self.spec.get('commandsOnly') else 'included',
                'states': self.states, 'qmlStates': self.ui_states, 'outages': self.outages,
                'injectedOutage': self.injected_outage, 'sshLifecycle': self.ssh_lifecycle,
                'relayDrops': self.relay_drops,
                'longOutputBytes': len(self.long_output.encode('utf-8'))}

    def append_long_output(self, result):
        output = result.get('output', '')
        self.long_output += output
        with (self.directory / 'long-command-output.txt').open('a', encoding='utf-8', newline='') as handle:
            handle.write(output)
        self.note('long-command-progress', status=result.get('status'),
                  outputBytes=len(self.long_output.encode('utf-8')),
                  elapsedSeconds=round(time.monotonic() - self.long_started, 3))

    def wait(self, predicate, seconds, label):
        from PySide6.QtTest import QTest
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return
            QTest.qWait(40)
            time.sleep(.005)
        raise AssertionError('Timed out: ' + label)

    def observe_transport(self):
        rows = self.backend.remoteEnvironments
        transport = next((r for r in rows if r.get('name') == 'acceptance'), {})
        status = {key: transport[key] for key in ('state', 'attempt', 'retryAfterMs', 'nextRetryAt',
                  'outageStartedAt', 'recovered', 'resumed', 'message', 'sshError') if key in transport}
        if not status.get('state') or (self.states and self.states[-1]['status'] == status):
            return
        at = time.monotonic()
        previous = self.states[-1]['state'] if self.states else None
        state = status['state']
        self.states.append({'state': state, 'at': at, 'status': status})
        if previous == 'connected' and state != 'connected' and not self.active_outage:
            self.active_outage = {'id': len(self.outages) + 1, 'startedAt': at,
                                  'startedElapsed': round(at - self.started, 3),
                                  'outageStartedAt': status.get('outageStartedAt')}
            self.outages.append(self.active_outage)
        if state == 'connected' and self.active_outage:
            self.active_outage.update(recoveredAt=at, durationSeconds=round(at - self.active_outage['startedAt'], 3),
                                      recoveredElapsed=round(at - self.started, 3), recoveredStatus=status)
            self.active_outage = None
        self.note('remote-state', **status)

    def observe_state(self):
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
        started = time.monotonic()
        self.current_tool = {'id': identity, 'tool': name,
                             'label': label or arguments.get('action', arguments.get('operation')),
                             'startedElapsed': round(started - self.started, 3), 'timeoutSeconds': timeout}
        self.note('tool-start', **self.current_tool)
        assert self.backend.send('Execute acceptance step ' + identity), self.backend.lastSendError
        self.wait(lambda: self.model.result is not None and not self.backend.busy, timeout, identity)
        result = decode_result(self.model.result)
        assert isinstance(result, dict), (name, result)
        # These are the actual UI transcript rows created by controller Pi events.
        tool_rows = [tool for row in self.backend._view.messages for tool in row.get('tools', [])
                     if tool.get('id') == identity and tool.get('name') == name]
        assert tool_rows, ('No real chat tool row', name, identity)
        self.tool_rows.extend(tool_rows)
        duration = round(time.monotonic() - started, 3)
        self.steps.append({'id': identity, 'tool': name, 'label': label, 'durationSeconds': duration, 'result': result})
        self.current_tool = None
        self.note('tool-finish', tool=name, status=result.get('status'), exitCode=result.get('exitCode'), durationSeconds=duration)
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
        self.ssh_client = ssh_client
        if self.spec.get('expectedSshExecutable'):
            assert ssh_client == Path(self.spec['expectedSshExecutable']).resolve(), tested
        self.note('ssh-client-selected', executable=str(ssh_client))
        short, output = self.read_until_complete(self.command(self.python("print('REMOTE_SHORT_OK')")))
        assert short.get('exitCode') == 0 and output == 'REMOTE_SHORT_OK\n', (short, output)

        interactive = self.command(self.python("print('PROMPT',flush=True)\ns=input()\nprint('ECHO:'+s,flush=True)"))
        assert interactive.get('status') == 'running', interactive
        reply = self.call('remote_command', {'action': 'write', 'environment': 'acceptance',
                          'sessionId': interactive['sessionId'], 'input': 'acceptance-input\n', 'yieldMs': 1000})
        final, tail = self.read_until_complete(reply)
        assert final.get('exitCode') == 0 and interactive.get('output', '') + tail == 'PROMPT\nECHO:acceptance-input\n'

        if self.spec.get('commandsOnly'):
            self.note('file-stage-skipped', reason='explicit commands-only continuation', verifiedPayloadBytes=0)
        else:
            self.run_file_stage()

        # Start after transfer so even a slow lab link cannot consume the
        # twenty-minute producer before the deliberate disconnect happens.
        seconds = self.spec['longSeconds']
        source = ("import os,time\npid=os.getpid()\nprint('START:'+str(pid),flush=True)\n"
                  f"for i in range({seconds}):\n print('TICK:'+str(i).zfill(4),flush=True)\n time.sleep(1)\n"
                  "print('DONE:'+str(pid),flush=True)\n")
        self.long_started = time.monotonic()
        long = self.command(self.python(source))
        assert long.get('status') == 'running', long
        self.append_long_output(long)
        session = long['sessionId']

        # Drop only the SSH client owned by this test; exec-server and the long
        # detached command stay alive. The shim rejects reconnects for >2 minutes.
        control = self.directory / 'ssh-control'
        launches = [json.loads(line) for line in (control / 'clients.jsonl').read_text().splitlines()]
        (control / 'blocked').write_text('acceptance fault injection\n')
        blocked_at = time.monotonic()
        if os.name == 'nt':
            established_at = next(row['at'] for row in reversed(self.states) if row['state'] == 'connected')
            killed_identity = self.terminate_windows_tunnel(launches, established_at)
            killed = killed_identity['pid']
        else:
            candidates = [r for r in launches if r.get('tunnel') and self.pid_alive(r['pid'])]
            assert len(candidates) == 1, ('Expected one owned SSH tunnel', candidates)
            killed = candidates[0]['pid']
            os.kill(killed, signal.SIGTERM)
            self.wait(lambda: not self.pid_alive(killed), 10, 'owned SSH client exited')
            killed_identity = {'pid': killed}
        self.injected_outage = {**killed_identity, 'blockedAt': blocked_at,
                                'requestedBlockSeconds': self.spec['outageSeconds']}
        self.injected_outage['confirmedExitedAt'] = time.monotonic()
        self.note('ssh-client-killed', **self.injected_outage)
        released = threading.Event()
        release_timing = {}

        def restore():
            time.sleep(self.spec['outageSeconds'])
            (control / 'blocked').unlink(missing_ok=True)
            release_timing['releasedAt'] = time.monotonic()
            released.set()

        threading.Thread(target=restore, daemon=True).start()
        recovery_timeout = self.spec.get('recoveryTimeout', 300)
        recovered = self.call('remote_command', {'action': 'read', 'environment': 'acceptance',
                              'sessionId': session, 'yieldMs': 1000, 'maxOutputBytes': 262144}, timeout=recovery_timeout,
                              label='read across >2 minute SSH outage')
        assert released.is_set(), 'Read returned before the transport outage ended'
        self.injected_outage.update(release_timing, recoveredAt=time.monotonic())
        self.injected_outage['actualBlockSeconds'] = round(release_timing['releasedAt'] - self.injected_outage['blockedAt'], 3)
        self.injected_outage['recoverySeconds'] = round(self.injected_outage['recoveredAt'] - self.injected_outage['blockedAt'], 3)
        assert self.injected_outage['actualBlockSeconds'] >= self.spec['outageSeconds'], self.injected_outage
        self.note('injected-outage-recovered', **self.injected_outage)
        self.append_long_output(recovered)
        assert any(r['state'] in ('reconnecting', 'connecting', 'retrying') for r in self.states), self.states
        assert self.states[-1]['state'] in ('connected', 'ready'), self.states
        assert any(r['state'] == 'reconnecting' for r in self.ui_states), ('QML never bound reconnect state', self.ui_states)
        assert self.ui_states[-1]['state'] == 'connected', self.ui_states
        assert any(r['status'].get('retryAfterMs', 0) > 0 for r in self.states
                   if r['at'] >= self.injected_outage['blockedAt']), 'No actual scheduled reconnect retry was observed'

        nearby, failed_output = self.read_until_complete(self.command(self.python(
            "import sys\nprint('NEARBY_FAILURE_STDOUT')\nprint('NEARBY_FAILURE_STDERR',file=sys.stderr)\nsys.exit(7)")))
        assert nearby.get('exitCode') == 7 and 'NEARBY_FAILURE_STDOUT' in failed_output and 'NEARBY_FAILURE_STDERR' in failed_output
        from PySide6.QtTest import QTest
        while recovered.get('status') == 'running':
            assert time.monotonic() - self.long_started < seconds + self.spec.get('recoveryTimeout', 180), '20 minute command exceeded deadline'
            # Allow several output lines to accumulate per turn so the long
            # command stays inside the fixture's live chat transcript window.
            QTest.qWait(30000)
            recovered = self.call('remote_command', {'action': 'read', 'environment': 'acceptance',
                                  'sessionId': session, 'yieldMs': 10000, 'maxOutputBytes': 262144},
                                  timeout=self.spec.get('recoveryTimeout', 90))
            self.append_long_output(recovered)
        assert recovered.get('exitCode') == 0, recovered
        lines = self.long_output.splitlines()
        assert lines and lines[0].startswith('START:'), self.long_output
        pid = int(lines[0].split(':')[1])
        expected = f'START:{pid}\n' + ''.join(f'TICK:{i:04d}\n' for i in range(seconds)) + f'DONE:{pid}\n'
        assert self.long_output == expected, ('Lost, duplicated or reordered output', len(self.long_output), len(expected))
        assert time.monotonic() - self.long_started >= seconds, 'Long command did not actually run for requested duration'
        (self.directory / 'chat-tool-rows.json').write_text(json.dumps(self.tool_rows, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        self.collect_ssh_evidence()
        assert not self.active_outage, ('An observed transport drop never recovered', self.active_outage)
        self.note('long-command-output-complete', commandPid=pid, outputLines=len(lines),
                  actualSeconds=round(time.monotonic() - self.long_started, 3))
        verified_payload = 0 if self.spec.get('commandsOnly') else self.spec['payloadBytes']
        self.note('passed', commandPid=pid, longSeconds=seconds, payloadBytes=verified_payload,
                  outageSeconds=self.spec['outageSeconds'], actualModelRequests=self.model.requests)
        return {'ok': True, 'commandPid': pid, 'longSeconds': seconds, 'payloadBytes': verified_payload,
                'outageSeconds': self.spec['outageSeconds'], **self.evidence(), 'steps': self.steps,
                'scope': ('commands-only continuation; files not exercised in this run; '
                          if self.spec.get('commandsOnly') else 'full file and command acceptance; ')
                         + 'offscreen real gateway/Pi/tools/SSH/exec-server; scripted local model; no upstream model'}

    def run_file_stage(self):
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

    @staticmethod
    def terminate_windows_tunnel(launches, established_at):
        """Validate native identity and terminate through one retained handle."""
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                    ctypes.POINTER(wintypes.DWORD)]
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        eligible = sorted((row for row in launches if row.get('tunnel') and row.get('at', float('inf')) <= established_at),
                          key=lambda row: row['at'], reverse=True)
        for row in eligible:
            if not row.get('windowsCreationTime') or not row.get('windowsImage'):
                continue
            handle = kernel.OpenProcess(0x1000 | 0x100000 | 0x0001, False, row['pid'])
            if not handle:
                continue
            try:
                created, exited, system, user = (wintypes.FILETIME() for _ in range(4))
                code, size = wintypes.DWORD(), wintypes.DWORD(32768)
                image = ctypes.create_unicode_buffer(size.value)
                if not (kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(system), ctypes.byref(user))
                        and kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size))
                        and kernel.GetExitCodeProcess(handle, ctypes.byref(code))):
                    continue
                creation = (created.dwHighDateTime << 32) | created.dwLowDateTime
                if (code.value != 259 or creation != row['windowsCreationTime']
                        or os.path.normcase(image.value) != os.path.normcase(row['windowsImage'])
                        or Path(image.value).resolve() != Path(row['executable']).resolve()):
                    continue
                if not kernel.TerminateProcess(handle, 1):
                    raise ctypes.WinError(ctypes.get_last_error())
                assert kernel.WaitForSingleObject(handle, 10000) == 0, 'Owned SSH handle did not signal exit'
                return {'pid': row['pid'], 'windowsCreationTime': creation, 'windowsImage': image.value,
                        'identityVerifiedOnTerminationHandle': True, 'launchedAt': row['at']}
            finally:
                kernel.CloseHandle(handle)
        raise AssertionError('No live test-owned Windows tunnel matches native creation time, image and established connection')

    def run_network(self):
        """Exercise network sharing through real streamed Pi tool calls."""
        b = self.backend
        self.note('network-begin', platform=self.spec['platform'], host=self.spec['host'])
        saved = b.saveProvider('', 'Test provider', 'openai',
                               f'http://127.0.0.1:{self.model.server.server_port}/v1', 'fixture-only',
                               json.dumps([{'upstream': 'test-model', 'alias': 'test-model',
                                            'reasoningLevelsAuto': False, 'reasoningFormatAuto': False,
                                            'reasoningLevels': [], 'reasoningFormat': 'openai'}]))
        assert saved, 'Cannot save isolated scripted provider'
        provider = next(p for p in b.store.data['providers'] if p['name'] == 'Test provider')
        b.selectModel(provider['id'], 'test-model')
        b.setToolPermissionMode('auto')
        self.wait(lambda: not b.busy, 90, 'Pi fixture startup')
        added = self.call('umeko_desktop', {'operation': 'remote-environments.add', 'arguments': {
            'name': 'acceptance', 'host': self.spec['host'], 'platform': self.spec['platform']}})
        assert added.get('ok'), added
        tested = self.call('umeko_desktop', {'operation': 'remote-environments.test', 'arguments': {'name': 'acceptance'}},
                           timeout=self.spec['bootstrapTimeout'])
        assert tested.get('ok'), tested
        self.ssh_client = Path(tested['sshClient']).resolve()
        outcomes = []

        def probe(phase, name, succeeds):
            command = self.spec['commands'][phase][name]
            final, output = self.read_until_complete(self.command(command), timeout=120)
            assert isinstance(final.get('exitCode'), int), ('No command exit status', phase, name, final)
            if name == 'apt':
                assert 'Download is performed unsandboxed as root' not in output, ('apt downloader escaped fixture UID', output)
            assert (final['exitCode'] == 0) == succeeds, (phase, name, final, output[-4000:])
            outcome = {'phase': phase, 'program': name, 'exitCode': final['exitCode'],
                       'expectedSuccess': succeeds, 'output': output[-4000:]}
            outcomes.append(outcome)
            self.note('network-probe', **outcome)

        status = self.call('remote_network', {'action': 'status', 'environment': 'acceptance'})
        assert status.get('ok') and status.get('network') == 'local', ('Sharing must be automatic by default', status)
        if self.spec['platform'] == 'linux':
            assert status.get('outbound') == 'builtin', ('CI must use the built-in direct outbound path', status)
        else:
            assert status.get('outbound') == 'configured', ('Windows must use the explicitly configured proxy', status)
        qml_network = self.observe_network_settings()
        probe('default', 'curl', True)
        disabled = self.call('remote_network', {'action': 'off', 'environment': 'acceptance'})
        assert disabled.get('ok') and disabled.get('network') == 'remote', disabled
        for name in self.spec['commands']['disabled']:
            probe('disabled', name, False)
        enabled = self.call('remote_network', {'action': 'on', 'environment': 'acceptance'})
        assert enabled.get('ok') and enabled.get('network') == 'local', enabled
        for name in self.spec['commands']['enabled']:
            probe('enabled', name, True)
        diagnostic = self.call('remote_network', {'action': 'test', 'environment': 'acceptance',
                                                 'url': 'https://example.com/'})
        assert diagnostic.get('ok'), diagnostic

        # Fault injection targets only the SSH child recorded by this fixture.
        # It never enumerates or touches a proxy, service, or unrelated client.
        control = self.directory / 'ssh-control'
        launches = [json.loads(line) for line in (control / 'clients.jsonl').read_text().splitlines()]
        tunnels = [row for row in launches if row.get('tunnel')]
        assert tunnels and self.pid_alive(tunnels[-1]['pid']), 'Expected a live acceptance-owned SSH client'
        # On Linux this launcher is wrapped by a Python recorder. Once Umeko
        # retires the recorder, the detached real ssh may still need reaping.
        for row in tunnels[:-1]:
            if not self.pid_alive(row['ownerPid']) and self.pid_alive(row['pid']):
                os.kill(row['pid'], signal.SIGTERM)
        killed = tunnels[-1]['pid']
        os.kill(killed, signal.SIGTERM)
        self.note('network-owned-ssh-cut', pid=killed)
        probe('reconnected', 'curl', True)
        after = [json.loads(line) for line in (control / 'clients.jsonl').read_text().splitlines()]
        assert any(row.get('tunnel') and row['pid'] != killed and self.pid_alive(row['pid']) for row in after), 'No replacement SSH client'
        if self.spec['platform'] == 'windows':
            # Remove only this invocation's generated remote download subtree.
            # Linux has root-owned apt archives on a disposable runner instead.
            source = ('import pathlib,shutil,stat\n'
                      'target=pathlib.Path(' + repr(self.spec['remoteDirectory']) + ')\n'
                      'root=target.resolve(strict=True)\n'
                      'assert target.is_absolute() and root.parent == target.parent.resolve(strict=True)\n'
                      'assert root.name == ' + repr(self.directory.name) + '\n'
                      'def retry_readonly(remove,item,error):\n'
                      ' path=pathlib.Path(item)\n'
                      ' if not isinstance(error,PermissionError) or root not in path.resolve().parents: raise error\n'
                      ' path.chmod(path.stat().st_mode | stat.S_IWRITE)\n'
                      ' remove(item)\n'
                      'shutil.rmtree(root,onexc=retry_readonly)\nprint("NETWORK_TEMP_CLEANED")')
            cleaned, output = self.read_until_complete(self.command(self.python(source) + '; exit $LASTEXITCODE'))
            assert cleaned.get('exitCode') == 0 and 'NETWORK_TEMP_CLEANED' in output, (cleaned, output)
        (self.directory / 'chat-tool-rows.json').write_text(json.dumps(self.tool_rows, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        result = {'ok': True, 'scenario': 'remote-network', 'probes': outcomes,
                  'defaultStatus': status, 'disabled': disabled, 'enabled': enabled,
                  'qmlNetworkText': qml_network,
                  'diagnostic': diagnostic, 'cutSshPid': killed,
                  'directBaseline': self.spec.get('directBaseline'),
                  'steps': self.steps, 'actualModelRequests': self.model.requests,
                  'scope': 'real app/gateway/Pi/tools/SSH/downloads and UI rows; local scripted model'}
        self.note('network-passed', probeCount=len(outcomes), actualModelRequests=self.model.requests)
        return result

    def observe_network_settings(self):
        from PySide6.QtCore import QMetaObject
        window = self.engine.rootObjects()[0]

        def item_named(name):
            nodes = [window.contentItem()]
            while nodes:
                item = nodes.pop()
                if item.objectName() == name:
                    return item
                nodes.extend(item.childItems())
            return None

        window.setProperty('settingsTab', 3)
        window.setProperty('page', 'settings')
        try:
            self.wait(lambda: item_named('openUmekoDesktopSettingsButton') is not None, 15, 'desktop settings button')
            button = item_named('openUmekoDesktopSettingsButton')
            assert QMetaObject.invokeMethod(button, 'clicked'), 'Could not open desktop settings'

            def active_label():
                label = item_named('remoteEnvironmentNetwork_acceptance')
                return label if label is not None and label.isVisible() else None

            self.wait(active_label, 15, 'shared network label')
            text = active_label().property('text')
            assert text in ('服务器正在使用本机网络', "The server is using this computer's network"), text
            self.note('qml-network-status', text=text)
            return text
        finally:
            window.setProperty('page', 'chat')

    def collect_ssh_evidence(self):
        lifecycle = self.directory / 'ssh-control/lifecycle.jsonl'
        self.ssh_lifecycle = [json.loads(line) for line in lifecycle.read_text(encoding='utf-8').splitlines()]
        assert all(Path(row['executable']).resolve() == self.ssh_client for row in self.ssh_lifecycle
                   if row['event'] == 'client-start'), 'Reconnect selected a different real SSH executable'
        starts = sorted((r for r in self.ssh_lifecycle if r['event'] == 'client-start' and r.get('tunnel')),
                        key=lambda r: r['at'])
        identity = lambda row: (row['pid'], row.get('windowsCreationTime'))
        exits = {identity(r): r for r in self.ssh_lifecycle if r['event'] == 'client-exit' and r.get('tunnel')}
        drops = []
        for outage in self.outages:
            assert 'recoveredAt' in outage, ('Observed disconnection did not recover', outage)
            previous = max(s['at'] for s in self.states if s['state'] == 'connected' and s['at'] < outage['startedAt'])
            old = next((r for r in reversed(starts) if r['at'] <= previous), None)
            new = next((r for r in reversed(starts) if previous < r['at'] <= outage['recoveredAt']), None)
            assert old and new and identity(old) != identity(new), ('No replacement SSH client in observed recovery', outage)
            # Umeko can close a wrapper before it records its child's exit. The
            # application transitions and the replacement client prove recovery.
            exit_record = exits.get(identity(old), {})
            drops.append({'pid': old['pid'], 'exitCode': exit_record.get('exitCode'),
                          'droppedAt': outage['startedAt'], 'replacementPid': new['pid'],
                          'windowsCreationTime': old.get('windowsCreationTime'),
                          'replacementWindowsCreationTime': new.get('windowsCreationTime'),
                          'connectedAt': outage['recoveredAt'], 'durationSeconds': outage['durationSeconds']})
        assert any(identity(drop) == identity(self.injected_outage) for drop in drops), 'Injected SSH client was not replaced'
        self.relay_drops = drops
        self.note('ssh-relay-drops-recovered', drops=drops, count=len(drops))

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
            # Both scenarios exercise the opt-in tools on isolated profiles.
            assert controller.saveDesktopSettings('{"remoteWorkspaceEnabled":true}')
            acceptance = Acceptance(app, engine, controller, spec)
            result = acceptance.run_network() if spec.get('scenario') == 'remote-network' else acceptance.run()
            status = 0
        except BaseException:
            result = {'ok': False, **(acceptance.evidence() if acceptance else {}), 'error': traceback.format_exc()}
            if acceptance:
                acceptance.note('failed', error=result['error'])
            print(result['error'], flush=True)
            status = 1
        finally:
            if acceptance:
                acceptance.model.close()
        (directory / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        controller.close()
        app.exit(status)

    QTimer.singleShot(0, run)
