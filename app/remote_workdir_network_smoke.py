"""Packaged acceptance for downloads from a remote workdir."""
import json
import os
from pathlib import Path
import re
import signal
import time

from PySide6.QtTest import QTest

from .remote_environments_smoke import Acceptance
from .remote_network_screenshots import NetworkSettingsShots

CURL = 'curl.exe -fsSL --connect-timeout 10 --max-time 35 https://github.com/robots.txt -o '


def run_network(runner):
    backend = runner.backend
    runner._configure_model()
    active, mirror = runner._run_dialog_flow()
    assert active['host'] == active['environment'] == 'dev-server'
    probes, tool_rows = [], []

    def tool(command, label, succeeds=True):
        output = runner.call_tool('bash', {'command': command, 'timeout': 65}, timeout=160, label=label)
        identity = f'rw-{runner.phase}-{runner.sequence}'
        row = next(t for row in backend._view.messages for t in row.get('tools', [])
                   if t.get('id') == identity and t.get('name') == 'bash')
        assert row.get('state') == ('done' if succeeds else 'error'), (label, row, output)
        tool_rows.append(row)
        return output

    def wait_network(enabled):
        expected = 'local' if enabled else 'remote'
        runner.wait(lambda: any(
            row['name'] == 'dev-server' and row.get('state') == 'connected'
            and row.get('networkStatus', {}).get('network') == expected
            for row in backend.remoteEnvironments), 180, f'network is {expected}')
        status = next(row['networkStatus'] for row in backend.remoteEnvironments if row['name'] == 'dev-server')
        if enabled:
            assert status.get('outbound') == 'configured', status
        return status

    def verify(path):
        code = f"from pathlib import Path; p=Path('{path}'); assert p.is_file() and p.stat().st_size; print('DOWNLOAD_ON_DISK')"
        assert 'DOWNLOAD_ON_DISK' in tool(f'python -c "{code}"', 'check downloaded file')
        assert not (Path(mirror) / path).exists(), 'The local mirror received a remote download'

    def batch(stage, succeeds):
        downloads = {
            'git': (f'git clone --depth 1 https://github.com/octocat/Hello-World.git git-{stage}', f'git-{stage}/README'),
            'pip': (f'python -m pip install --disable-pip-version-check --no-cache-dir --no-deps --retries 0 --timeout 15 --index-url https://pypi.org/simple --target pip-{stage} six==1.17.0', f'pip-{stage}/six.py'),
            'curl': (CURL + f'curl-{stage}.txt', f'curl-{stage}.txt'),
        }
        for program, (command, path) in downloads.items():
            output = tool(command, f'{stage} {program}', succeeds)
            if succeeds:
                verify(path)
            code = re.search(r'command exited with code (\d+)', output, re.I)
            row = {'phase': stage, 'program': program, 'ok': succeeds,
                   'exitCode': int(code[1]) if code else 0 if succeeds else None}
            probes.append(row)
            runner.note('workspace-network-probe', **row, output=output[-1500:])

    wait_network(False)
    batch('off', False)
    shots = NetworkSettingsShots(runner, output=runner.spec['screens'])
    assert backend.setRemoteNetworkEnabled(True)
    status = wait_network(True)
    batch('on', True)

    user_command = CURL + 'curl-user.txt'
    requests = runner.model.requests
    assert backend.send('! ' + user_command), backend.lastSendError

    def user_row():
        return next((t for row in backend._view.messages for t in row.get('tools', [])
                     if t.get('name') == 'bash' and t.get('arguments', {}).get('command') == user_command), {})

    runner.wait(lambda: not backend.busy and bool(user_row()), 150, 'user shell result in chat')
    assert user_row().get('state') == 'done' and runner.model.requests == requests, user_row()
    tool_rows.append(user_row())
    verify('curl-user.txt')
    runner.note('workspace-user-shell', ok=True, modelRequests=0)

    backend.desktopPlugins.setEnabled('terminal', True)
    created = runner.call_plugin('terminal', 'create', {}, timeout=90)
    assert created.get('ok'), created
    terminal = created['result']['id']
    try:
        QTest.qWait(1500)
        sent = runner.call_plugin('terminal', 'write', {'terminalId': terminal, 'text':
            CURL + "curl-terminal.txt; if ($LASTEXITCODE -eq 0) { Write-Output ('TERM_' + 'DOWNLOAD_OK') }\r"})
        assert sent.get('ok'), sent
        deadline = time.monotonic() + 65
        while time.monotonic() < deadline:
            reply = runner.call_plugin('terminal', 'read', {'terminalId': terminal, 'lines': 150})
            if 'TERM_DOWNLOAD_OK' in reply.get('result', {}).get('text', ''):
                break
            QTest.qWait(300)
        else:
            raise AssertionError(('Terminal download did not complete', reply))
    finally:
        runner.call_plugin('terminal', 'kill', {'terminalId': terminal})
    verify('curl-terminal.txt')
    runner.note('workspace-terminal-network', ok=True)

    clients = runner.directory / 'ssh-control/clients.jsonl'
    window = runner.engine.rootObjects()[0]
    previous_page = window.property('page')
    shots.open_settings()
    shots.place_card()
    rows = [json.loads(line) for line in clients.read_text(encoding='utf-8').splitlines()]
    owned = [row for row in rows if row.get('tunnel') and
             Acceptance.pid_alive(row['ownerPid']) and Acceptance.pid_alive(row['pid'])]
    assert owned, 'No test-owned SSH client to disconnect'
    for row in owned:
        os.kill(row['pid'], signal.SIGTERM)

    def retry_text():
        item = runner._find_qml('remoteEnvironmentRetry_dev-server')
        return str(item.property('text')) if item is not None and item.property('visible') else ''

    def first_retry_visible():
        return re.search(r'(?:Retry |第 )1(?:\D|$)', retry_text()) and re.search(r'\d\d:\d\d:\d\d', retry_text())

    runner.wait(first_retry_visible, 25, 'first visible retry and time')
    first_retry = retry_text()
    runner.note('workspace-retry-visible', text=first_retry, killedPids=[row['pid'] for row in owned])
    window.setProperty('page', previous_page)
    tool(CURL + 'curl-reconnected.txt', 'reconnected curl')
    verify('curl-reconnected.txt')
    wait_network(True)
    (runner.directory / 'chat-tool-rows.json').write_text(json.dumps(tool_rows, ensure_ascii=False, indent=2), encoding='utf-8')
    runner.note('workspace-downloads-passed', probes=probes, userBang=True, terminal=True, reconnected=True)
    screenshots = shots.pair('on', enabled=True)
    assert backend.setRemoteNetworkEnabled(False)
    wait_network(False)
    screenshots += shots.pair('off', enabled=False)
    return {'ok': True, 'probes': probes, 'remoteWorkspace': active, 'status': status,
            'userBang': True, 'terminal': True, 'reconnected': True, 'firstRetry': first_retry,
            'actualModelRequests': runner.model.requests, 'settingsScreenshots': screenshots}
