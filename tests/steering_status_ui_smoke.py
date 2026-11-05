"""Real Pi + gated local SSE provider -> backend actions -> actual QML task footer.

The gates, bridge events and provider requests decide when actions occur. Timeouts
only bound a failed test; elapsed time never decides whether a status is correct.
No user input, native notices, external credentials or user's profile are used.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from socketserver import TCPServer
import sys
import tempfile
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_QUICK_BACKEND'] = 'software'
os.environ['UMEKO_LANGUAGE'] = 'en'


class GatedProvider:
    """Each request starts a real SSE draft, then waits for its explicit gate."""
    def __init__(self):
        self.requests = []
        self.errors = []
        self.closed = threading.Event()
        self.scenario = ''
        owner = self

        class Server(ThreadingHTTPServer):
            daemon_threads = True

            def server_bind(self):
                TCPServer.server_bind(self)
                self.server_name = 'localhost'
                self.server_port = self.server_address[1]

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                request = {'scenario': owner.scenario, 'body': body,
                           'release': threading.Event(), 'streamed': threading.Event(),
                           'finished': threading.Event()}
                owner.requests.append(request)
                try:
                    # Error response waits until the test has observed the real
                    # resumed user_start, rather than racing its HTTP response.
                    if owner.scenario == 'error' and len(owner.current()) == 2:
                        request['streamed'].set()
                        if not request['release'].wait(45):
                            raise AssertionError('Error response gate was not released')
                        raw = json.dumps({'error': {'message': 'STEERING_FIXTURE_ERROR',
                                                   'type': 'BadRequestError', 'code': 400}}).encode()
                        self.send_response(400)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Content-Length', str(len(raw)))
                        self.end_headers()
                        self.wfile.write(raw)
                        return
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream')
                    self.end_headers()

                    def emit(delta, finish=None):
                        chunk = {'id': 'steering-fixture', 'object': 'chat.completion.chunk',
                                 'created': 1, 'model': 'test-model', 'choices': [
                                     {'index': 0, 'delta': delta, 'finish_reason': finish}]}
                        self.wfile.write(('data: ' + json.dumps(chunk) + '\n\n').encode())
                        self.wfile.flush()

                    emit({'role': 'assistant'})
                    emit({'content': 'STREAMING_' + owner.scenario + '_' + str(len(owner.current()))})
                    request['streamed'].set()
                    if not request['release'].wait(45):
                        raise AssertionError('SSE completion gate was not released')
                    if owner.closed.is_set():
                        return
                    emit({'content': ' FIXTURE_COMPLETE'})
                    emit({}, 'stop')
                    self.wfile.write(b'data: [DONE]\n\n')
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    # Native Pi intentionally disconnects interrupted requests.
                    pass
                except Exception as error:
                    owner.errors.append(repr(error))
                finally:
                    request['finished'].set()

        self.server = Server(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def current(self):
        return [request for request in self.requests if request['scenario'] == self.scenario]

    def close(self):
        self.closed.set()
        for request in self.requests:
            request['release'].set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--record', type=Path)
    parser.add_argument('--scenario', action='append', choices=['normal', 'stop', 'error', 'consecutive'])
    args = parser.parse_args()
    from PySide6.QtCore import QEventLoop, QObject, QTimer, Signal, Slot

    class QuietTray(QObject):
        quitRequested = Signal()
        notificationRequested = Signal(str)

        def __init__(self, window, icon, parent):
            super().__init__(parent)
            self.tray = None

        def set_language(self, *_): pass
        def restore(self): pass

    class QuietNotifications(QObject):
        activated = Signal(str)

        def __init__(self, window, tray, root, parent): super().__init__(parent)

        @Slot(str, str, bool, bool)
        def task_finished(self, *_): pass

    provider = GatedProvider()
    samples, results, violations = [], {}, []
    app = engine = backend = window = None
    active = {'scenario': ''}
    with tempfile.TemporaryDirectory(prefix='umeko-steering-status-') as sandbox, ExitStack() as mocks:
        sandbox = Path(sandbox)
        os.environ['UMEKO_DATA_DIR'] = str(sandbox / 'profile')
        os.environ['PI_CODING_AGENT_DIR'] = str(sandbox / 'agent')
        from app.storage import Store
        from main import create_application
        import app.pi_sessions as pi_sessions
        import app.pi_runtime as pi_runtime
        seed = Store()
        seed.data['agent']['agentDir'] = str(sandbox / 'agent')
        seed.data['agent']['safeMode'] = True
        seed.data['workspace'] = str(sandbox / 'workspace')
        (sandbox / 'workspace').mkdir()
        seed.data['providers'] = [{'id': 'test-provider', 'name': 'Test provider', 'api': 'openai',
            'baseUrl': f'http://127.0.0.1:{provider.server.server_port}/v1', 'key': 'fixture-only-key',
            'proxy': {'mode': 'direct'}, 'models': [{'upstream': 'test-model', 'alias': 'test-model'}]}]
        seed.data['selectedProvider'], seed.data['selectedModel'] = 'test-provider', 'test-model'
        seed.save()
        mocks.enter_context(patch('app.tray.TrayController', QuietTray))
        mocks.enter_context(patch('app.notifications.TaskNotifications', QuietNotifications))
        mocks.enter_context(patch('app.controller.Controller.loadNativeIndex', lambda self: None))
        mocks.enter_context(patch('app.desktop_plugins.DesktopPlugins.start', lambda *_: None))
        observer = sandbox / 'observe-pi.mjs'
        native_module = ROOT / 'runtime/releases' / pi_runtime.RELEASE_NAME / 'node_modules/@earendil-works/pi-coding-agent/dist/core/agent-session.js'
        observer.write_text('''const {AgentSession} = await import(''' + json.dumps(native_module.as_uri()) + ''');
const original = AgentSession.prototype._emit;
AgentSession.prototype._emit = function(event) {
  if (['agent_start','turn_start','turn_end','message_start','message_end','agent_end'].includes(event.type))
    process.stdout.write(JSON.stringify({type:'pi_event', event:event.type,
      role:event.message?.role, stopReason:event.message?.stopReason})+'\\n');
  return original.call(this, event);
};
''', encoding='utf-8')
        original_overrides = pi_sessions.npm_overrides
        node_options = os.environ.get('NODE_OPTIONS', '') + ' --import=' + observer.as_uri()
        mocks.enter_context(patch.object(pi_sessions, 'npm_overrides',
            lambda agent: {**original_overrides(agent), 'NODE_OPTIONS': node_options}))
        # The Windows task runner supplies a preload that hides Node's own child
        # processes. Preserve it in this fixture's Pi child after the normal
        # production environment scrub, without changing the product adapter.
        if os.name == 'nt' and os.environ.get('NODE_OPTIONS'):
            options = os.environ['NODE_OPTIONS']
            original_environment = pi_runtime.node_environment
            mocks.enter_context(patch.object(pi_runtime, 'node_environment',
                lambda values=None: {**original_environment(values), 'NODE_OPTIONS': options}))
        try:
            app, engine, backend = create_application()
            assert engine.rootObjects(), 'Actual Main.qml did not load'
            window = engine.rootObjects()[0]
            window.setProperty('page', 'chat')
            warnings = []
            engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))

            def find(name, root=None):
                pending = [root or window.contentItem()]
                while pending:
                    item = pending.pop()
                    if item.objectName() == name and item.isVisible():
                        return item
                    pending.extend(item.childItems())
                return None

            def snapshot(source, event=None):
                # This is the conversation footer TaskStatus and its rendered
                # Text child, not backend.turnStatus or a fixture-created item.
                status = find('turnStatus')
                text = find('taskStatusText', status) if status is not None else None
                composer = find('composerTaskStatus')
                composer_text = find('taskStatusText', composer) if composer is not None else None
                row = {'index': len(samples), 'scenario': active['scenario'], 'source': source,
                       'footerState': status.property('state') if status is not None else None,
                       'footerText': text.property('text') if text is not None else None,
                       'footerVisible': status.isVisible() if status is not None else False,
                       'composerState': composer.property('state') if composer is not None else None,
                       'composerText': composer_text.property('text') if composer_text is not None else None,
                       'phase': backend._view.phase, 'cancelled': backend._view.cancelled}
                if event is not None:
                    row['event'] = {key: event[key] for key in ('type', 'event', 'role', 'stopReason', 'text', 'error') if key in event}
                samples.append(row)
                return row

            def on_event(record, event):
                if record is backend._view:
                    snapshot('pi' if event.get('type') == 'pi_event' else 'bridge', event)

            backend._pool.event.connect(on_event)
            loop = QEventLoop()

            def until(predicate, label, seconds=45):
                deadline = time.monotonic() + seconds
                while not predicate():
                    assert time.monotonic() < deadline, (label, samples[-8:], provider.errors)
                    assert not provider.errors, provider.errors
                    # Event-loop pumping is not a timing assertion or a release
                    # condition. Every transition below waits on a real event.
                    QTimer.singleShot(10, loop.quit)
                    loop.exec()

            def event_seen(kind, **fields):
                return any(row['scenario'] == active['scenario'] and row.get('event', {}).get('type') == kind
                           and all(row['event'].get(key) == value for key, value in fields.items()) for row in samples)

            def streamed(number):
                return len(provider.current()) >= number and provider.current()[number - 1]['streamed'].is_set()

            def release(number):
                snapshot('release-request-' + str(number))
                provider.current()[number - 1]['release'].set()

            for scenario in args.scenario or ['normal', 'stop', 'error', 'consecutive']:
                active['scenario'] = provider.scenario = scenario
                backend.newSession()
                assert backend.send('INITIAL_' + scenario), 'Initial backend.send was rejected'
                snapshot('action-send')
                until(lambda: streamed(1) and event_seen('delta') and backend._view.phase == 'running'
                      and find('turnStatus') is not None, 'Initial real streaming draft')
                snapshot('initial-stream-ready')
                if scenario == 'stop':
                    backend.stop()
                    row = snapshot('action-stop')
                    if row['footerState'] != 'stopping' or 'Stopping' not in str(row['footerText']):
                        violations.append('stop action did not show Stopping: ' + str(row))
                    if row['composerState'] != 'stopping' or 'Stopping' not in str(row['composerText']):
                        violations.append('stop action composer did not show Stopping: ' + str(row))
                    until(lambda: event_seen('done') and not backend.busy, 'Explicit stop terminal')
                    release(1)
                    expected, label = 'stopped', 'Stopped'
                else:
                    assert backend.steer('STEER_ONE_' + scenario), 'backend.steer was rejected'
                    snapshot('action-steer-one')
                    until(lambda: event_seen('message', role='assistant', stopReason='aborted')
                          and event_seen('user_start', text='STEER_ONE_' + scenario) and streamed(2),
                          'Steering interrupted stream and resumed native Pi')
                    snapshot('first-steer-resumed')
                    release(1)
                    if scenario == 'consecutive':
                        until(lambda: any(row['scenario'] == scenario and row.get('event', {}).get('type') == 'delta'
                                          and 'STREAMING_consecutive_2' in row['event'].get('text', '') for row in samples),
                              'Second draft reached actual bridge')
                        assert backend.steer('STEER_TWO_' + scenario), 'Second backend.steer was rejected'
                        snapshot('action-steer-two')
                        until(lambda: event_seen('user_start', text='STEER_TWO_' + scenario) and streamed(3),
                              'Consecutive steering resumed native Pi')
                        snapshot('second-steer-resumed')
                        release(2)
                        release(3)
                    else:
                        release(2)
                    until(lambda: event_seen('done') and not backend.busy, 'Steering terminal')
                    expected, label = ('failed', 'Failed') if scenario == 'error' else ('finished', 'Done')
                terminal = snapshot('terminal')
                scenario_rows = [row for row in samples if row['scenario'] == scenario]
                states = list(dict.fromkeys(row['footerState'] for row in scenario_rows))
                composer_states = list(dict.fromkeys(row['composerState'] for row in scenario_rows))
                results[scenario] = {'expected': expected, 'actual': terminal['footerState'],
                                     'footerText': terminal['footerText'], 'states': states,
                                     'composerState': terminal['composerState'], 'composerText': terminal['composerText'],
                                     'composerStates': composer_states,
                                     'providerRequests': len(provider.current())}
                if terminal['footerState'] != expected or label not in str(terminal['footerText']):
                    violations.append(scenario + ': terminal ' + str(results[scenario]))
                if scenario != 'stop' and any(state in ('stopping', 'stopped') for state in states):
                    violations.append(scenario + ': steering displayed cancellation ' + str(states))
                if terminal['composerState'] != expected or label not in str(terminal['composerText']):
                    violations.append(scenario + ': composer terminal ' + str(results[scenario]))
                if scenario != 'stop' and any(state in ('stopping', 'stopped') for state in composer_states):
                    violations.append(scenario + ': composer displayed cancellation ' + str(composer_states))
                if not event_seen('pi_event', event='agent_end'):
                    violations.append(scenario + ': native Pi agent_end was not captured')
                if not event_seen('pi_event', event='message_end', role='assistant', stopReason='aborted'):
                    violations.append(scenario + ': native Pi aborted assistant was not captured')
                if scenario == 'error' and not event_seen('message', role='assistant', stopReason='error'):
                    violations.append('error: real provider failure was not propagated')
                if scenario == 'consecutive':
                    aborted = [row for row in scenario_rows if row['source'] == 'bridge'
                               and row.get('event', {}).get('stopReason') == 'aborted']
                    if len(aborted) != 2:
                        violations.append('consecutive: expected two actual interrupted assistant streams')
                print('STEERING_STATUS_RESULT ' + json.dumps({scenario: results[scenario]}), flush=True)
            assert not provider.errors, provider.errors
            assert not warnings, '\n'.join(warnings)
        finally:
            if args.record:
                args.record.parent.mkdir(parents=True, exist_ok=True)
                args.record.write_text(json.dumps({'results': results, 'violations': violations, 'events': samples}, indent=2), encoding='utf-8')
            provider.close()
            if backend is not None:
                backend.close()
            if window is not None:
                window.hide()
            if engine is not None:
                import shiboken6
                shiboken6.delete(engine)
            if app is not None:
                app.processEvents()
    assert not violations, '\n'.join(violations)
    print('STEERING_STATUS_UI_OK: real Pi + QML scenarios ' + ', '.join(results), flush=True)


if __name__ == '__main__':
    main()
