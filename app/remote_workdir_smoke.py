"""Opt-in real SSH remote-workdir acceptance, called only by --remote-workdir-smoke.

Exercises the real WorkspacePicker dialog, all 7 Pi built-in tools (read, write,
edit, bash, ls, find, grep), all 4 built-in plugins (file-tree, git-viewer,
change-review, terminal), app restart + project reopen, and SSH connection-drop
auto-recovery using a local scripted SSE model (0 cost).
"""
from __future__ import annotations

import json
import os
import signal
import threading
import time
import traceback
from pathlib import Path

from .remote_environments_smoke import Acceptance as _BaseAcceptance, ScriptedModel, decode_result


def _to_py(val):
    return val.toVariant() if hasattr(val, 'toVariant') else val


class WorkdirAcceptance:
    def __init__(self, app, engine, backend, spec):
        self.app, self.engine, self.backend, self.spec = app, engine, backend, spec
        self.directory = Path(spec['runDir'])
        self.phase = spec.get('phase', 'main')
        self.model = ScriptedModel()
        self.started = time.monotonic()
        self.sequence = 0
        self.states = []
        self.ui_reconnecting_seen = False
        self.ui_reconnecting_text = ''
        self.plugin_replies = {}
        self.checks = {}
        self.backend.remoteEnvironmentsChanged.connect(self._on_env_changed)
        self.backend.desktopPlugins.response.connect(self._on_plugin_response)

    def note(self, event, **data):
        row = {'phase': self.phase, 'event': event, 'elapsed': round(time.monotonic() - self.started, 3), **data}
        with (self.directory / 'workdir-events.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
        print('REMOTE_WORKDIR ' + json.dumps(row, ensure_ascii=False), flush=True)

    def wait(self, predicate, seconds, label):
        from PySide6.QtTest import QTest
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return
            QTest.qWait(40)
            time.sleep(0.005)
        raise AssertionError('Timed out: ' + label)

    def _find_qml(self, object_name):
        from PySide6.QtCore import QObject
        root = self.engine.rootObjects()[0]
        found = root.findChild(QObject, object_name)
        if found is not None:
            return found
        stack = [root.contentItem()]
        while stack:
            item = stack.pop()
            if item.objectName() == object_name:
                return item
            stack.extend(item.childItems())
        return None

    def _on_env_changed(self):
        host = self.spec['host']
        for row in self.backend.remoteEnvironments:
            if row.get('host') == host or row.get('name') == host:
                st = row.get('state')
                if st and (not self.states or self.states[-1]['state'] != st):
                    self.states.append({'state': st, 'message': row.get('message', ''), 'at': round(time.monotonic() - self.started, 3)})
                    self.note('remote-state', state=st)
                if st == 'reconnecting':
                    picker = self._find_qml('workspacePicker')
                    if picker is not None and bool(picker.property('isReconnecting')):
                        self.ui_reconnecting_seen = True
                        status_item = self._find_qml('remoteBrowserStatusText')
                        if status_item is not None:
                            self.ui_reconnecting_text = str(status_item.property('text') or '')

    def _on_plugin_response(self, req_id, payload):
        self.plugin_replies[req_id] = dict(payload)

    def _configure_model(self):
        b = self.backend
        existing = next((p for p in b.store.data.get('providers', []) if p.get('name') == 'Test provider'), None)
        pid = existing['id'] if existing else ''
        toasts = []
        b.toast.connect(toasts.append)
        try:
            saved = b.saveProvider(
                pid, 'Test provider', 'openai',
                f'http://127.0.0.1:{self.model.server.server_port}/v1', 'fixture-only',
                json.dumps([{'upstream': 'test-model', 'alias': 'test-model',
                             'reasoningLevelsAuto': False, 'reasoningFormatAuto': False,
                             'reasoningLevels': [], 'reasoningFormat': 'openai'}]),
            )
            assert saved, toasts
        finally:
            b.toast.disconnect(toasts.append)
        provider = next(p for p in b.store.data['providers'] if p['name'] == 'Test provider')
        b.selectModel(provider['id'], 'test-model')
        b.setToolPermissionMode('auto')

    def call_tool(self, name, arguments, timeout=180, label=None):
        self.sequence += 1
        identity = f'rw-{self.phase}-{self.sequence}'
        self.model.current = {'id': identity, 'name': name, 'arguments': arguments}
        self.model.result = None
        self.note('tool-start', tool=name, label=label or name)
        assert self.backend.send('Execute acceptance step ' + identity), self.backend.lastSendError
        self.wait(lambda: self.model.result is not None and not self.backend.busy, timeout, f'{name}:{identity}')
        decoded = decode_result(self.model.result)
        text = decoded if isinstance(decoded, str) else json.dumps(decoded, ensure_ascii=False)
        self.note('tool-finish', tool=name, preview=text[:200])
        return text

    def call_plugin(self, plugin_id, method, args=None, timeout=60):
        plugins = self.backend.desktopPlugins
        plugins.synchronize()
        req_id = plugins.call_for(plugin_id, method, json.dumps(args or {}), timeout_ms=int(timeout * 1000))
        assert req_id, f'Failed to dispatch plugin call {plugin_id}.{method}'
        self.wait(lambda: req_id in self.plugin_replies, timeout + 5, f'{plugin_id}.{method}')
        reply = self.plugin_replies.pop(req_id)
        self.note('plugin-call', plugin=plugin_id, method=method, ok=reply.get('ok'))
        return reply

    def _run_dialog_flow(self):
        host = self.spec['host']
        remote_parent = self.spec['remoteParent']
        folder_name = self.spec['folderName']
        expected_platform = self.spec['platform']
        bootstrap_timeout = float(self.spec.get('bootstrapTimeout', 300))

        picker = self._find_qml('workspacePicker')
        assert picker is not None, 'WorkspacePicker not found in Main.qml'
        picker.openPicker('remote')
        self.wait(lambda: any(h.get('alias') == host for h in self.backend.sshConfigHosts), 20, 'sshConfigHosts load')
        picker.rebuildHostChoices()
        choices = _to_py(picker.property('hostChoices')) or []
        idx = next((i for i, c in enumerate(choices) if c.get('host') == host), -1)
        assert idx >= 0, f'Host {host} not in WorkspacePicker choices: {choices}'
        picker.applyHostChoice(idx)
        # Wait for automatic ensureRemoteHost + platform detection
        self.wait(lambda: not bool(picker.property('ensuringHost')) and bool(picker.property('selectedEnvName')),
                  bootstrap_timeout, f'ensureRemoteHost({host})')
        env_name = str(picker.property('selectedEnvName'))
        detected_platform = str(picker.property('selectedPlatform'))
        assert detected_platform == expected_platform, (detected_platform, expected_platform)
        self.note('dialog-host-selected', envName=env_name, platform=detected_platform)

        # Browse remoteParent (this triggers exec-server bootstrap on first connect)
        picker.openBrowserFresh(remote_parent)
        self.wait(lambda: not bool(picker.property('browserLoading')) and bool(picker.property('currentBrowsePath')),
                  bootstrap_timeout, f'browse {remote_parent}')
        browsed_parent = str(picker.property('currentBrowsePath'))
        assert not picker.property('browserError'), picker.property('browserError')
        self.note('dialog-browsed-parent', path=browsed_parent, count=len(_to_py(picker.property('browserEntries')) or []))

        # Test Go Up
        picker.goUpDirectory()
        self.wait(lambda: not bool(picker.property('browserLoading')) and str(picker.property('currentBrowsePath')) != browsed_parent,
                  60, 'goUpDirectory')
        up_path = str(picker.property('currentBrowsePath'))
        self.note('dialog-went-up', path=up_path)

        # Return to remoteParent and test path autocomplete
        picker.openBrowserFresh(browsed_parent)
        self.wait(lambda: not bool(picker.property('browserLoading')) and str(picker.property('currentBrowsePath')) == browsed_parent,
                  60, 'return to remoteParent')
        sep = '\\' if expected_platform == 'windows' else '/'
        probe_prefix = browsed_parent.rstrip('\\/') + sep
        path_input = self._find_qml('remotePathInput')
        assert path_input is not None
        path_input.forceActiveFocus()
        path_input.setProperty('text', probe_prefix)
        picker.setProperty('typedPath', probe_prefix)
        picker.triggerAutocomplete()
        self.wait(lambda: len(_to_py(picker.property('autocompleteItems')) or []) > 0 or len(_to_py(picker.property('browserEntries')) or []) == 0,
                  30, 'autocomplete listing')
        ac_count = len(_to_py(picker.property('autocompleteItems')) or [])
        self.note('dialog-autocomplete', prefix=probe_prefix, suggestions=ac_count)

        # Create new folder via mkdir
        picker.setProperty('mkdirOpen', True)
        picker.setProperty('mkdirName', folder_name)
        picker.submitMkdir()
        self.wait(lambda: not bool(picker.property('mkdirBusy')) and not bool(picker.property('browserLoading'))
                  and folder_name.lower() in str(picker.property('currentBrowsePath')).lower(),
                  90, f'mkdir {folder_name}')
        assert not picker.property('browserError'), picker.property('browserError')
        created_path = str(picker.property('currentBrowsePath'))
        self.note('dialog-mkdir-done', path=created_path)

        # Choose this path -> activates remote workspace
        picker.setProperty('selectedIndex', -1)
        picker.confirmRemoteSelection()
        self.wait(lambda: bool(self.backend.activeRemoteWorkspace.get('remotePath')) and not bool(picker.property('visible')),
                  30, 'confirmRemoteSelection')
        active = dict(self.backend.activeRemoteWorkspace)
        assert folder_name.lower() in active['remotePath'].lower(), active
        mirror = str(self.backend.store.data['workspace'])
        assert Path(mirror).is_dir(), mirror
        self.checks['dialog'] = {
            'ok': True, 'host': host, 'envName': env_name, 'detectedPlatform': detected_platform,
            'browsedParent': browsed_parent, 'wentUpTo': up_path,
            'autocompleteSuggestions': ac_count, 'createdPath': active['remotePath'], 'mirrorDir': mirror,
        }
        return active, mirror

    def _run_seven_tools(self):
        # 1. write
        w1 = self.call_tool('write', {'path': 'alpha.txt', 'content': 'line-one\nBEFORE_EDIT_MARKER\nline-three\n'})
        w2 = self.call_tool('write', {'path': 'sub/beta.txt', 'content': 'nested remote content\n'})
        # 2. read
        r1 = self.call_tool('read', {'path': 'alpha.txt'})
        assert 'BEFORE_EDIT_MARKER' in r1, r1
        # 3. edit
        self.call_tool('edit', {'path': 'alpha.txt', 'edits': [{'oldText': 'BEFORE_EDIT_MARKER', 'newText': 'AFTER_EDIT_MARKER'}]})
        r2 = self.call_tool('read', {'path': 'alpha.txt'})
        assert 'AFTER_EDIT_MARKER' in r2, r2
        # 4. ls
        ls_out = self.call_tool('ls', {'path': '.'})
        assert 'alpha.txt' in ls_out and 'sub' in ls_out, ls_out
        # 5. find
        find_out = self.call_tool('find', {'pattern': '*.txt'})
        assert 'alpha.txt' in find_out and 'beta.txt' in find_out, find_out
        # 6. grep
        grep_out = self.call_tool('grep', {'pattern': 'AFTER_EDIT_MARKER'})
        assert 'alpha.txt' in grep_out and 'AFTER_EDIT_MARKER' in grep_out, grep_out
        # 7. bash (also prepares git repo for git-viewer & change-review)
        bash_script = '\n'.join([
            'echo REMOTE_BASH_OK',
            'git init',
            'git config user.name "Umeko Test"',
            'git config user.email "test@example.invalid"',
            'git add alpha.txt',
            'git commit -m "initial remote commit"',
            'echo untracked-line > untracked.txt',
            'echo bash-marker > bash-marker.txt',
        ])
        bash_out = self.call_tool('bash', {'command': bash_script})
        assert 'REMOTE_BASH_OK' in bash_out, bash_out

        # Make an unstaged edit on alpha.txt so git-viewer shows both modified and untracked
        self.call_tool('edit', {'path': 'alpha.txt', 'edits': [{'oldText': 'line-three', 'newText': 'line-three-modified'}]})

        self.checks['tools'] = {
            'ok': True,
            'write': w1[:120], 'writeSub': w2[:120], 'readAfterEdit': r2[:160],
            'ls': ls_out[:160], 'find': find_out[:160], 'grep': grep_out[:160], 'bash': bash_out[:160],
        }

    def _run_four_plugins(self, active):
        plugins = self.backend.desktopPlugins
        plugins.setEnabled('terminal', True)
        plugins.setEnabled('change-review', True)
        plugins.synchronize()

        # 1. file-tree
        ft_list = self.call_plugin('file-tree', 'list', {'path': '.'})
        assert ft_list.get('ok'), ft_list
        ft_names = [e['name'] for e in ft_list['result'].get('entries', [])]
        assert 'alpha.txt' in ft_names and 'sub' in ft_names and 'untracked.txt' in ft_names, ft_names
        ft_copy = self.call_plugin('file-tree', 'copyPath', {'path': 'alpha.txt'})
        assert ft_copy.get('ok') and 'alpha.txt' in ft_copy['result'].get('path', ''), ft_copy
        ft_preview = self.call_plugin('file-tree', 'preview', {'path': 'alpha.txt'})
        assert ft_preview.get('ok'), ft_preview
        self.checks['fileTree'] = {'ok': True, 'entries': ft_names, 'copyPath': ft_copy['result']['path']}

        # 2. git-viewer
        gv_status = self.call_plugin('git-viewer', 'status', {})
        assert gv_status.get('ok') and gv_status['result'].get('repository'), gv_status
        gv_paths = [e['path'] for e in gv_status['result'].get('entries', [])]
        assert 'alpha.txt' in gv_paths and 'untracked.txt' in gv_paths, gv_paths
        gv_diff = self.call_plugin('git-viewer', 'diff', {'path': 'alpha.txt', 'group': 'changes'})
        assert gv_diff.get('ok') and 'line-three-modified' in gv_diff['result'].get('text', ''), gv_diff
        gv_hist = self.call_plugin('git-viewer', 'history', {})
        assert gv_hist.get('ok') and any('initial remote commit' in c.get('subject', '') for c in gv_hist['result'].get('entries', [])), gv_hist
        self.checks['gitViewer'] = {'ok': True, 'branch': gv_status['result'].get('branch'), 'paths': gv_paths}

        # 3. change-review (trigger a real Pi turn that edits alpha.txt, then verify status & diff)
        self.call_tool('edit', {'path': 'alpha.txt', 'edits': [{'oldText': 'line-three-modified', 'newText': 'line-three-reviewed'}]})
        cr_status = None
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            res = self.call_plugin('change-review', 'status', {})
            if res.get('ok') and not res['result'].get('active') and any(e.get('path') == 'alpha.txt' for e in res['result'].get('entries', [])):
                cr_status = res['result']
                break
            time.sleep(0.3)
        assert cr_status is not None, 'change-review did not capture remote turn edit on alpha.txt'
        cr_diff = self.call_plugin('change-review', 'diff', {'path': 'alpha.txt'})
        assert cr_diff.get('ok') and 'line-three-reviewed' in cr_diff['result'].get('text', ''), cr_diff
        self.checks['changeReview'] = {'ok': True, 'entries': [e['path'] for e in cr_status['entries']]}

        # 4. terminal (interactive SSH PTY into remote directory)
        term_create = self.call_plugin('terminal', 'create', {})
        assert term_create.get('ok'), term_create
        term_id = term_create['result']['id']
        marker = f'REMOTE_TERM_OK_{int(time.time())}'
        try:
            # Give the SSH shell a moment to initialize prompt
            from PySide6.QtTest import QTest
            QTest.qWait(2500)
            w_res = self.call_plugin('terminal', 'write', {'terminalId': term_id, 'data': f'echo {marker}\r'})
            assert w_res.get('ok'), w_res
            term_text = ''
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                r_res = self.call_plugin('terminal', 'read', {'terminalId': term_id, 'lines': 200})
                if r_res.get('ok'):
                    term_text = r_res['result'].get('text', '')
                    if marker in term_text:
                        break
                QTest.qWait(300)
            assert marker in term_text, f'Terminal output never contained {marker}: {term_text[-500:]}'
            self.checks['terminal'] = {'ok': True, 'markerSeen': True, 'tail': term_text[-200:]}
        finally:
            self.call_plugin('terminal', 'close', {'terminalId': term_id})

    def _run_reconnect_check(self):
        control = self.directory / 'ssh-control'
        clients_file = control / 'clients.jsonl'
        assert clients_file.is_file(), 'SSH control log missing'
        launches = [json.loads(line) for line in clients_file.read_text(encoding='utf-8').splitlines() if line.strip()]
        tunnels = [r for r in launches if r.get('tunnel') and _BaseAcceptance.pid_alive(r['pid'])]
        assert tunnels, ('No active owned SSH tunnel found', launches)

        outage_sec = int(self.spec.get('outageSeconds', 12))
        (control / 'blocked').write_text('workdir reconnect test\n', encoding='utf-8')
        killed_pids = []
        for row in tunnels:
            try:
                os.kill(row['pid'], signal.SIGTERM)
                killed_pids.append(row['pid'])
            except OSError:
                pass
        self.note('ssh-tunnels-killed', pids=killed_pids, outageSeconds=outage_sec)

        released = threading.Event()

        def restore():
            time.sleep(outage_sec)
            (control / 'blocked').unlink(missing_ok=True)
            released.set()

        threading.Thread(target=restore, daemon=True).start()
        # Keep WorkspacePicker observing state during outage
        picker = self._find_qml('workspacePicker')
        if picker is not None:
            picker.openPicker('remote')
            picker.openBrowserFresh(self.backend.activeRemoteWorkspace.get('remotePath', ''))

        recovered_text = self.call_tool('read', {'path': 'alpha.txt'}, timeout=max(120, outage_sec + 90), label='read across SSH drop')
        assert released.is_set(), 'Tool completed before simulated outage ended'
        assert 'line-three-reviewed' in recovered_text, recovered_text
        assert any(s['state'] == 'reconnecting' for s in self.states), self.states
        assert self.states[-1]['state'] == 'connected', self.states
        self.checks['reconnect'] = {
            'ok': True,
            'killedPids': killed_pids,
            'outageSeconds': outage_sec,
            'states': list(self.states),
            'uiReconnectingSeen': self.ui_reconnecting_seen,
            'uiReconnectingText': self.ui_reconnecting_text,
        }

    def run_main(self):
        self._configure_model()
        active, mirror = self._run_dialog_flow()
        self._run_seven_tools()
        self._run_four_plugins(active)
        self._run_reconnect_check()
        rows = self.backend.projectRows
        proj = next((r for r in rows if r.get('environment') == active['environment'] and r.get('remotePath') == active['remotePath']), None)
        assert proj is not None, rows
        return {
            'ok': True,
            'phase': 'main',
            'projectId': proj['id'],
            'projectName': proj['name'],
            'remoteWorkspace': active,
            'mirrorDir': mirror,
            'checks': self.checks,
        }

    def run_reopen(self):
        self._configure_model()
        expected_path = self.spec['expectedRemotePath']
        project_id = self.spec['projectId']
        rows = self.backend.projectRows
        proj = next((r for r in rows if r.get('id') == project_id), None)
        assert proj is not None, ('Saved remote project missing after restart', project_id, rows)
        assert proj.get('isRemote') and proj.get('remotePath') == expected_path, proj
        self.backend.openProject(project_id)
        self.wait(lambda: self.backend.activeRemoteWorkspace.get('remotePath') == expected_path, 20, 'openProject after restart')
        read_text = self.call_tool('read', {'path': 'alpha.txt'}, timeout=float(self.spec.get('bootstrapTimeout', 180)))
        assert 'line-three-reviewed' in read_text, read_text
        ft_list = self.call_plugin('file-tree', 'list', {'path': '.'})
        assert ft_list.get('ok') and any(e['name'] == 'alpha.txt' for e in ft_list['result'].get('entries', [])), ft_list
        return {
            'ok': True,
            'phase': 'reopen',
            'projectId': project_id,
            'projectName': proj['name'],
            'remotePath': self.backend.activeRemoteWorkspace.get('remotePath'),
            'readPreview': read_text[:160],
            'fileTreeCount': len(ft_list['result'].get('entries', [])),
        }


def start(app, engine, controller, spec_path):
    from PySide6.QtCore import QTimer
    spec = json.loads(Path(spec_path).read_text(encoding='utf-8'))
    directory = Path(spec['runDir']).resolve()
    assert Path(os.environ['UMEKO_DATA_DIR']).resolve() == directory / 'profile'
    assert os.environ.get('QT_QPA_PLATFORM') == 'offscreen'
    result_name = 'reopen-result.json' if spec.get('phase') == 'reopen' else 'result.json'

    def run():
        runner = None
        try:
            runner = WorkdirAcceptance(app, engine, controller, spec)
            result = runner.run_reopen() if spec.get('phase') == 'reopen' else runner.run_main()
            status = 0
        except BaseException:
            result = {'ok': False, 'phase': spec.get('phase', 'main'), 'error': traceback.format_exc()}
            print(result['error'], flush=True)
            status = 1
        finally:
            if runner is not None:
                runner.model.close()
        (directory / result_name).write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        controller.close()
        app.exit(status)

    QTimer.singleShot(0, run)
