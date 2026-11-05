"""Offscreen: fake upstream HTTP -> Gateway -> LocalServer -> real Pi -> chat QML.

No external provider, credentials, screenshots, input injection or notifications.
Run from the repository with its prepared Pi runtime and Python environment.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_QUICK_BACKEND'] = 'software'
os.environ['UMEKO_LANGUAGE'] = 'zh'

from PySide6.QtCore import QObject, QMetaObject, Q_ARG
from PySide6.QtTest import QTest
from app.pi_runtime import CREATE_NO_WINDOW, RELEASE_NAME, node_executable
from main import create_application


def main():
    profile = tempfile.TemporaryDirectory(prefix='umeko-provider-error-')
    root = Path(profile.name)
    os.environ['UMEKO_DATA_DIR'] = str(root / 'profile')
    data = Path(os.environ['UMEKO_DATA_DIR'])
    data.mkdir()
    agent = root / 'agent'
    agent.mkdir()
    workspace = root / 'workspace'
    workspace.mkdir()
    # Supply no persisted secrets; fake provider configuration is added in memory.
    (data / 'settings.json').write_text(json.dumps({
        'agent': {'agentDir': str(agent), 'outputLimitDefaultVersion': 1},
        'server': {'keys': []}, 'ui': {'language': 'zh', 'lineSpacing': 'standard'},
        'workspace': str(workspace),
    }), encoding='utf-8')
    reason = 'At most 3 image(s) may be provided in one prompt. (parameter=image)'
    original_body = json.dumps({'error': {'message': reason, 'type': 'BadRequestError',
                                         'param': 'image', 'code': 400},
                                'request_id': 'fixture-image-limit-400'}, ensure_ascii=False)
    provider_key = 'fixture-provider-private-key'
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append({'path': self.path, 'model': body.get('model'), 'stream': body.get('stream')})
            raw = original_body.encode('utf-8')
            self.send_response(400)
            self.send_header('Content-Type', 'application/json')
            self.send_header('X-Request-ID', 'fixture-image-limit-400')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    upstream = None
    upstream_thread = None
    process = None
    readers = []
    app = engine = backend = window = None
    try:
        upstream = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        upstream_thread.start()
        # Native index discovery is unrelated to this one explicitly created Pi
        # session. Keep startup confined to the temporary fixture directories.
        with patch('app.controller.Controller.loadNativeIndex', lambda self: None):
            app, engine, backend = create_application()
        window = engine.rootObjects()[0]
        warnings = []
        engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
        configured = {'id': 'test-provider', 'name': 'Test provider', 'api': 'openai',
                      'baseUrl': f'http://127.0.0.1:{upstream.server_port}/v1', 'key': provider_key,
                      # This fixture tests the business HTTP error, not discovery.
                      'models': [{'upstream': 'test-model', 'alias': 'test-model', 'vision': True,
                                  'reasoningLevels': [], 'reasoningLevelsAuto': False,
                                  'reasoningFormat': 'openai', 'reasoningFormatAuto': False}]}
        backend.store.data.update(providers=[configured], selectedProvider='test-provider', selectedModel='test-model')
        record = backend._view
        record.id = 'provider-error-fixture'
        record.workspace = str(workspace)
        record.messages = [{'role': 'assistant', 'text': '', 'error': False}]
        window.setProperty('page', 'chat')

        def items(start=None):
            pending = [start or window.contentItem()]
            while pending:
                item = pending.pop()
                yield item
                pending.extend(item.childItems())

        def find(name):
            return next((item for item in items() if item.objectName() == name), None)

        def wait(predicate, label, seconds=8):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                QTest.qWait(20)
                value = predicate()
                if value:
                    return value
            raise AssertionError(label + '\n' + '\n'.join(warnings))

        def chat_text():
            # SelectableText is the actual TextEdit rendered by MessageBody,
            # not the backend model or a parent item's source property.
            return '\n'.join(str(item.property('text') or '') for item in items()
                             if item.objectName().startswith('selectText_') and item.isVisible())

        release = ROOT / 'runtime/releases' / RELEASE_NAME / 'bridge.mjs'
        assert release.is_file(), 'Prepare the project Pi runtime before running this smoke test'
        process = subprocess.Popen([node_executable(), str(release)], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   encoding='utf-8', creationflags=CREATE_NO_WINDOW)
        events = queue.Queue()
        stderr = []

        def read_events():
            for line in process.stdout:
                if line.startswith('{'):
                    try:
                        events.put(json.loads(line))
                    except json.JSONDecodeError:
                        events.put({'type': 'fixture_invalid_json'})
            events.put({'type': 'fixture_eof'})

        readers = [threading.Thread(target=read_events, daemon=True),
                   threading.Thread(target=lambda: stderr.extend(process.stderr.readlines()), daemon=True)]
        for reader in readers:
            reader.start()
        payload = {'type': 'prompt', 'gateway': f'http://127.0.0.1:{backend.private_server.port}/',
                   'token': backend.private_token, 'model': 'test-model', 'models': backend.gateway.models(),
                   'workspace': str(workspace), 'defaultCwd': str(workspace), 'agentDir': str(agent),
                   'sessionDir': str(root / 'sessions'), 'agent': {'safeMode': True},
                   'text': 'Describe the supplied fixture.'}
        process.stdin.write(json.dumps(payload) + '\n')
        process.stdin.flush()
        failure_event = None
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            QTest.qWait(20)
            try:
                event = events.get_nowait()
            except queue.Empty:
                continue
            if event.get('type') in ('assistant_start', 'delta', 'thinking_delta', 'message'):
                backend._handle_pi_event(record, event)
            if event.get('type') == 'message' and event.get('role') == 'assistant' and event.get('error'):
                failure_event = event
            if event.get('type') == 'done':
                break
            if event.get('type') == 'fixture_eof':
                raise AssertionError('Pi exited before its terminal event: ' + ''.join(stderr))
            if event.get('type') == 'ui_request':
                raise AssertionError('Fixture unexpectedly requested user input')
        else:
            raise AssertionError('Pi did not finish within 45 seconds: ' + ''.join(stderr))
        assert failure_event, 'Pi did not propagate the real failed provider response'
        assert reason in failure_event['error'], failure_event
        for value in ('BadRequestError', 'image', '400'):
            assert value in failure_event['error'], failure_event
        assert requests == [{'path': '/v1/chat/completions', 'model': 'test-model', 'stream': True}], requests
        rendered = wait(lambda: reason in chat_text() and chat_text(), 'Chat QML lost upstream image-limit reason')
        assert '供应商返回 HTTP 400' in rendered, rendered
        for value in ('BadRequestError', 'image', '400'):
            assert value in rendered, rendered
        assert provider_key not in rendered
        assert '请检查地址、密钥和模型名称' not in rendered
        button = wait(lambda: find('requestDetails_0'), 'Failed chat has no request-details entry')
        assert button.isVisible()
        backend.setLanguage('en')
        rendered = wait(lambda: 'Provider returned HTTP 400' in chat_text() and chat_text(),
                        'Visible chat did not translate the provider HTTP prefix')
        assert reason in rendered and provider_key not in rendered
        for value in ('BadRequestError', 'image', '400'):
            assert value in rendered, rendered

        dialog = window.findChild(QObject, 'requestDetailsDialog')
        assert dialog is not None
        # Exercise the failed chat's real button without moving the user's mouse.
        assert QMetaObject.invokeMethod(button, 'clicked')
        wait(lambda: dialog.property('opened'), 'Chat request-details action did not open its report')
        response_tab = find('requestDetailsResponseTab')
        assert QMetaObject.invokeMethod(response_tab, 'clicked')
        details = wait(lambda: find('requestDetailsText'), 'Missing request-details TextArea')
        shown = wait(lambda: original_body in details.property('text') and details.property('text'),
                     'Request details lost the complete raw upstream body')
        assert '400' in shown and 'fixture-image-limit-400' in shown
        assert provider_key not in shown
        report = dialog.property('report')
        assert provider_key not in report and backend.private_token not in report
        assert json.loads(report)['provider'] == 'Test provider'
        assert json.loads(report)['http'][-1]['response']['body'] == original_body
        assert not warnings, '\n'.join(warnings)
        print('PROVIDER_ERROR_UI_OK: real HTTP400 -> Gateway -> LocalServer -> Pi -> visible chat; zh/en reason, raw response details, secret redaction', flush=True)
    finally:
        if process is not None:
            if process.poll() is None:
                try:
                    process.stdin.write('{"type":"shutdown"}\n')
                    process.stdin.flush()
                    process.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    process.kill()
                    process.wait(timeout=5)
            for reader in readers:
                reader.join(timeout=2)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
        if backend is not None:
            # Do not persist the fake key or notify the desktop on test teardown.
            backend.store.data['providers'] = []
            backend.close()
        if window is not None:
            window.hide()
        if app is not None:
            app.processEvents()
        if engine is not None:
            import shiboken6
            shiboken6.delete(engine)
        if upstream is not None:
            upstream.shutdown()
            upstream.server_close()
        if upstream_thread is not None:
            upstream_thread.join(timeout=2)
        profile.cleanup()


if __name__ == '__main__':
    main()
