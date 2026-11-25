"""Run the Windows package with an isolated profile and a scripted loopback model."""

import argparse
from collections import Counter
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
from threading import Barrier, Event, Lock, Thread
import time


MARK = re.compile(r'P641 (BEGIN|API|UI|TEST|QUIET|RESUME|GROUP|ALL|RACE_START|RACE|HOLD|STEER|LEGACY)\b')
ACTOR = re.compile(r'Smoke member identity: (lead|api-dev|ui-dev|tester)\.')
NAMES = ('lead', 'api-dev', 'ui-dev', 'tester')


def wait_for(condition, label, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = condition()
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError(label)


def contents(message):
    text = message.get('content')
    return ''.join(item.get('text', '') for item in text if item.get('type') == 'text') if isinstance(text, list) else text or ''


class ScriptedModel:
    def __init__(self, log):
        self.log = log
        self.lock = Lock()
        self.requests = []
        self.errors = []
        self.claims = {}
        self.ids = {}
        self.team = self.task = self.race_task = ''
        self.barrier = Barrier(2, timeout=15)
        self.hold_started = Event()
        self.release_hold = Event()

    def count(self):
        with self.lock:
            return Counter(row['member'] for row in self.requests)

    def script(self, member, phase, results, text):
        step = len(results)
        if results and not results[-1].get('ok') and phase != 'RACE':
            raise AssertionError(f'{member} {phase} tool failed: {results[-1]}')
        if phase == 'BEGIN':
            if step == 0:
                return 'agent_bus.team_create', {'name': 'Team fixture', 'members': [
                    {'targetId': self.ids[name], 'name': name, 'groups': ['devs'] if name != 'tester' else []}
                    for name in NAMES[1:]]}
            if step == 1:
                self.team = results[-1]['id']
                return 'agent_bus.team_members', {'teamId': self.team}
            if step == 2:
                assert [row['status'] for row in results[-1]['members']] == ['running'] + 3 * ['not_started']
                return self.post('task', title='Ship a feature', text='Implement and verify')
            if step == 3:
                self.task = results[-1]['event']['task']['id']
                return self.post('message', text='@api-dev P641 API')
        elif phase == 'API':
            if step == 0:
                return self.post('claim', taskId=self.task, expectedVersion=1)
            if step == 1:
                return self.post('progress', taskId=self.task, expectedVersion=2, text='API ready')
            if step == 2:
                return self.post('handoff', taskId=self.task, expectedVersion=3, to='ui-dev', text='@ui-dev P641 UI')
        elif phase == 'UI' and step == 0:
            return self.post('handoff', taskId=self.task, expectedVersion=4, to='tester', text='@tester P641 TEST')
        elif phase == 'TEST' and step == 0:
            return self.post('result', taskId=self.task, expectedVersion=5, text='Feature verified')
        elif phase in ('QUIET', 'RESUME', 'GROUP', 'ALL', 'STEER') and step == 0:
            return self.post('message', text=f'{phase.lower()} recorded by {member}')
        elif phase == 'HOLD':
            self.hold_started.set()
            assert self.release_hold.wait(timeout=10), 'Timed out holding the model response'
        elif phase == 'RACE_START':
            if step == 0:
                return self.post('task', title='One claimant', text='Both developers try the same version')
            if step == 1:
                self.race_task = results[-1]['event']['task']['id']
                return self.post('message', text='@devs P641 RACE')
        elif phase == 'RACE':
            if step == 0:
                self.barrier.wait()
                return self.post('claim', taskId=self.race_task, expectedVersion=1)
            with self.lock:
                self.claims[member] = results[-1]
        elif phase == 'LEGACY' and step == 0:
            if member == 'lead' and 'Agent Bus result' not in text:
                return 'agent_bus.dispatch', {'targetId': self.ids['tester'], 'text': 'P641 LEGACY'}
            if member == 'tester':
                request = re.search(r'"bridgeRequestId"\s*:\s*"([a-z0-9]+)"', text)
                return 'agent_bus.reply', {'requestId': request[1], 'result': 'legacy reply verified'}
        return None

    def post(self, kind, **fields):
        return 'agent_bus.team_post', {'teamId': self.team, 'event': {'kind': kind, **fields}}

    def complete(self, body):
        messages = body.get('messages', [])
        member = next((match[1] for row in messages if (match := ACTOR.search(contents(row)))), 'unknown')
        text = ''
        phase = None
        results = []
        for row in reversed(messages):
            value = contents(row)
            if row['role'] == 'tool':
                results.insert(0, json.loads(value))
            elif row['role'] == 'user':
                trigger = MARK.search(value)
                if trigger or member == 'lead' and 'Agent Bus result' in value:
                    phase, text = trigger[1] if trigger else 'LEGACY', value
                    break
        with self.lock:
            number = len(self.requests) + 1
            record = {'request': number, 'member': member, 'phase': phase, 'step': len(results),
                      'model': body.get('model'), 'at': time.time()}
            self.requests.append(record)
            with self.log.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(record) + '\n')
        assert body.get('model') == 'test-model' and member in NAMES and phase, record
        response = 'Legacy reply received.' if member == 'lead' and 'Agent Bus result' in text else 'Scripted turn finished.'
        return number, self.script(member, phase, results, text), response


def handler_for(fixture):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            try:
                assert self.path == '/v1/chat/completions', self.path
                number, tool, response = fixture.complete(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                if tool:
                    operation, arguments = tool
                    delta = {'tool_calls': [{'index': 0, 'id': f'call_smoke_{number}', 'type': 'function',
                             'function': {'name': 'umeko_desktop', 'arguments': json.dumps({
                                 'operation': operation, 'arguments': arguments})}}]}
                    reason = 'tool_calls'
                else:
                    delta, reason = {'content': response}, 'stop'
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                for part, finish in [({'role': 'assistant'}, None), (delta, None), ({}, reason)]:
                    value = {'id': f'completion-{number}', 'object': 'chat.completion.chunk', 'model': 'test-model',
                             'created': int(time.time()), 'choices': [{'index': 0, 'delta': part, 'finish_reason': finish}]}
                    self.wfile.write(f'data: {json.dumps(value)}\n\n'.encode())
                    self.wfile.flush()
                self.wfile.write(b'data: [DONE]\n\n')
            except Exception as error:
                fixture.errors.append(repr(error))
                self.send_error(400, 'Scripted model request failed')

        def log_message(self, *_args):
            pass

    return Handler


def command(directory, action, **args):
    path = directory / 'request.json'
    response = directory / 'response.json'
    response.unlink(missing_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'action': action, **args}), encoding='utf-8')
    temporary.replace(path)
    result = wait_for(lambda: json.loads(response.read_text(encoding='utf-8')) if response.is_file() else None,
                      f'Packaged app did not acknowledge {action}', 12)
    assert result['accepted'], result
    return result


@contextmanager
def launch(executable, directory, name):
    profile = directory / 'profile'
    env = dict(os.environ, UMEKO_DATA_DIR=str(profile), UMEKO_SHELL_SMOKE_DIRECTORY=str(directory),
               PI_CODING_AGENT_DIR=str(profile / 'agent'), QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
               UMEKO_DIAGNOSTICS=str(directory.parent / f'{name}-qt.log'), NO_PROXY='127.0.0.1,localhost')
    for key in ('NODE_OPTIONS', 'NODE_PATH', 'QT_PLUGIN_PATH', 'QML_IMPORT_PATH', 'QML2_IMPORT_PATH'):
        env.pop(key, None)
    with (directory.parent / f'{name}-output.log').open('wb') as log:
        process = subprocess.Popen([str(executable), '--smoke'], cwd=directory / 'workspace', env=env,
                                   stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            yield process.pid
            command(directory, 'quit')
            assert process.wait(timeout=12) == 0
        finally:
            if process.poll() is None:
                try:
                    command(directory, 'quit')
                    process.wait(timeout=12)
                except (AssertionError, OSError, subprocess.TimeoutExpired):
                    process.terminate()
                    process.wait(timeout=12)


def exercise(executable, directory, fixture):
    def send(text):
        command(directory, 'team_send', targetId=fixture.ids['lead'], text=text)

    def settled(event_count):
        def observe():
            assert not fixture.errors, fixture.errors
            state = command(directory, 'team_state', teamId=fixture.team)
            if 'board' in state and len(state['board']['events']) >= event_count and not state['queued'] and not any(
                    row['busy'] for row in state['agents'].values()):
                return state
        return wait_for(observe, f'Board did not settle after {event_count} events')

    with launch(executable, directory, 'first') as pid:
        fixture.ids = command(directory, 'team_setup')['agents']
        send('P641 BEGIN')
        first = settled(7)
        assert [event['kind'] for event in first['board']['events']] == [
            'task', 'message', 'claim', 'progress', 'handoff', 'handoff', 'result']
        assert [event['actor'] for event in first['board']['events']] == [
            'lead', 'lead', 'api-dev', 'api-dev', 'api-dev', 'ui-dev', 'tester']
        assert first['board']['tasks'][0]['result'] == 'Feature verified'
        assert {row['status'] for row in first['members']} == {'waiting'}
        api_session = first['agents']['api-dev']['sessionId']
        checker = fixture.count()
        send('P641 QUIET')
        settled(8)
        time.sleep(3)
        idle_requests = {name: fixture.count()[name] - checker[name] for name in NAMES[1:]}
        assert idle_requests == dict.fromkeys(NAMES[1:], 0), idle_requests

        lead_requests = fixture.count()['lead']
        send('@api-dev P641 RESUME')
        resumed = settled(10)
        assert resumed['board']['events'][-1]['text'] == 'resume recorded by api-dev'
        assert resumed['agents']['api-dev']['sessionId'] == api_session
        assert fixture.count()['lead'] == lead_requests
        send('@devs P641 GROUP')
        grouped = settled(13)
        assert grouped['board']['events'][10]['recipients'] == ['api-dev', 'ui-dev']
        assert {row['actor'] for row in grouped['board']['events'][11:]} == {'api-dev', 'ui-dev'}
        send('@all P641 ALL')
        everyone = settled(17)
        assert everyone['board']['events'][13]['recipients'] == list(NAMES[1:])
        assert {row['actor'] for row in everyone['board']['events'][14:]} == set(NAMES[1:])

        send('P641 RACE_START')
        raced = settled(20)
        assert set(fixture.claims) == {'api-dev', 'ui-dev'}, fixture.claims
        assert sorted(claim['ok'] for claim in fixture.claims.values()) == [False, True], fixture.claims
        assert '当前版本为 2' in next(claim['error'] for claim in fixture.claims.values() if not claim['ok'])
        claims = [event for event in raced['board']['events'][17:] if event['kind'] == 'claim']
        assert len(claims) == 1 and claims[0]['task']['version'] == 2

        send('@api-dev P641 HOLD')
        try:
            assert fixture.hold_started.wait(timeout=12)
            assert command(directory, 'team_state', teamId=fixture.team)['agents']['api-dev']['busy']
            send('@api-dev P641 STEER')
            time.sleep(0.75)
        finally:
            fixture.release_hold.set()
        steered = settled(23)
        assert steered['board']['events'][-1]['text'] == 'steer recorded by api-dev'

        before_legacy = len(fixture.requests)
        send('P641 LEGACY')
        def legacy_reply():
            state = settled(23)
            return state if any(row['status'] == 'completed' and row['result'] == 'legacy reply verified'
                                for row in state['requests']) and sum(row['member'] == 'lead' and row['phase'] == 'LEGACY'
                                for row in fixture.requests[before_legacy:]) >= 3 else None
        final = wait_for(legacy_reply, 'One-to-one Agent Bus reply did not arrive')
        assert any('Legacy reply received.' in row['text'] for row in final['agents']['lead']['chat'])
        for member in final['agents'].values():
            assert member['sessionId'] and Path(member['sessionFile']).is_file() and not member['approval'], member
            assert any(tool['name'] == 'umeko_desktop' for msg in member['chat'] for tool in msg['tools']), member
        assert (directory / 'profile/tasks.sqlite3').is_file()
        assert not fixture.errors, fixture.errors

    request_count = fixture.count()
    with launch(executable, directory, 'restart') as restarted_pid:
        restarted = command(directory, 'team_state', teamId=fixture.team)
        assert restarted_pid != pid and restarted['board'] == final['board']
        assert {row['status'] for row in restarted['members']} == {'waiting'}
        assert not restarted['queued'] and fixture.count() == request_count
    return {'boardEvents': len(final['board']['events']), 'idleRequests': idle_requests,
            'requestCounts': dict(request_count), 'race': {name: result['ok'] for name, result in fixture.claims.items()},
            'directResumeSameSession': True, 'directRoutingLeadRequests': 0, 'runningMention': True,
            'group': True, 'broadcast': True,
            'oneToOne': True, 'restart': True, 'sessionFiles': 4,
            'applicationPids': [pid, restarted_pid], 'runtimePids': {name: row['pid'] for name, row in final['agents'].items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    executable, output = args.executable.resolve(strict=True), args.output.resolve()
    directory = output / 'isolated'
    profile, workspace = directory / 'profile', directory / 'workspace'
    for parent in (workspace, *workspace.parents):
        for name in ('AGENTS.md', 'CLAUDE.md'):
            assert not (parent / name).is_file(), str(parent / name)
    profile.mkdir(parents=True)
    workspace.mkdir()
    (profile / 'desktop-plugins').mkdir()
    (profile / 'desktop-plugins/settings.json').write_text(
        json.dumps({'enabled': {'desktop-pet': False}}), encoding='utf-8')
    fixture = ScriptedModel(output / 'model-requests.jsonl')
    with ThreadingHTTPServer(('127.0.0.1', 0), handler_for(fixture)) as server:
        url = f'http://127.0.0.1:{server.server_port}/v1'
        (profile / 'settings.json').write_text(json.dumps({
            'selectedProvider': 'test-provider', 'selectedModel': 'test-model',
            'providers': [{'id': 'test-provider', 'name': 'Test provider', 'api': 'openai', 'baseUrl': url,
                           'key': '', 'models': [{'upstream': 'test-model', 'alias': 'test-model',
                                                  'reasoningLevelsAuto': False, 'reasoningFormatAuto': False}]}],
            'agent': {'agentDir': str(profile / 'agent')}, 'ui': {'sessionCacheSize': 8},
            'desktop': {'teamCollaborationEnabled': True},
        }), encoding='utf-8')
        Thread(target=server.serve_forever, daemon=True).start()
        try:
            result = exercise(executable, directory, fixture)
        finally:
            server.shutdown()
            (output / 'model-errors.json').write_text(json.dumps(fixture.errors), encoding='utf-8')
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
