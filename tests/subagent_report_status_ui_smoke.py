"""Real Pi + scripted local provider: a background child reports after the parent finished.

The parent delegates one background subagent and ends its own turn. The child
then reports, and Pi starts a new parent run by itself. While that run streams,
the conversation footer must show Running, the composer must offer Stop, and a
message typed by the user must enter the existing follow-up queue. After the run
the footer shows Done again.

No accounts, visible windows, input injection or the user's profile are used.
Gates and bridge events decide each step; timeouts only bound a failed run.
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

CHILD_HINT = 'notify_parent'
CHILD_TASK = 'CHILD_TASK_140'
USER_TEXT = 'USER_DURING_REPORT_140'
BUSY_ERROR = 'Agent is already processing'


class ScriptedProvider:
    """OpenAI-compatible SSE fixture with one gate per scripted reply."""

    def __init__(self):
        self.requests = []
        self.errors = []
        self.closed = threading.Event()
        self.child_release = threading.Event()
        self.report_release = threading.Event()
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
                system = '\n'.join(str(message.get('content') or '') for message in body.get('messages', [])
                                   if message.get('role') in ('system', 'developer'))
                child = CHILD_HINT in system
                users = [str(message.get('content') or '') for message in body.get('messages', [])
                         if message.get('role') == 'user']
                parent_number = sum(1 for request in owner.requests if not request['child']) + (0 if child else 1)
                request = {'child': child, 'number': parent_number, 'users': users,
                           'tools': [tool.get('function', {}).get('name') for tool in body.get('tools', [])],
                           'streamed': threading.Event(), 'finished': threading.Event()}
                owner.requests.append(request)
                try:
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream')
                    self.end_headers()

                    def emit(delta, finish=None):
                        chunk = {'id': 'issue140-fixture', 'object': 'chat.completion.chunk', 'created': 1,
                                 'model': 'test-model', 'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}
                        self.wfile.write(('data: ' + json.dumps(chunk) + '\n\n').encode())
                        self.wfile.flush()

                    def finish(reason='stop'):
                        emit({}, reason)
                        self.wfile.write(b'data: [DONE]\n\n')
                        self.wfile.flush()

                    emit({'role': 'assistant'})
                    if child:
                        request['streamed'].set()
                        if not owner.child_release.wait(60):
                            raise AssertionError('Child gate was not released')
                        emit({'content': 'CHILD_REPORT_140'})
                        finish()
                    elif parent_number == 1:
                        call = {'index': 0, 'id': 'call-subagent-140', 'type': 'function', 'function': {
                            'name': 'subagent', 'arguments': json.dumps({
                                'prompt': CHILD_TASK, 'description': 'Background probe',
                                'subagent_type': 'general-purpose', 'run_in_background': True})}}
                        emit({'tool_calls': [call]})
                        request['streamed'].set()
                        finish('tool_calls')
                    elif parent_number == 2:
                        emit({'content': 'PARENT_TURN_DONE_140'})
                        request['streamed'].set()
                        finish()
                    elif parent_number == 3:
                        # The run Pi started for the child's report. Hold it open
                        # while the test observes the footer and sends a message.
                        emit({'content': 'HANDLING_CHILD_REPORT_140'})
                        request['streamed'].set()
                        if not owner.report_release.wait(60):
                            raise AssertionError('Report gate was not released')
                        if owner.closed.is_set():
                            return
                        emit({'content': ' REPORT_HANDLED_140'})
                        finish()
                    else:
                        emit({'content': 'FOLLOW_UP_ANSWERED_140'})
                        request['streamed'].set()
                        finish()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
                except Exception as error:
                    owner.errors.append(repr(error))
                finally:
                    request['finished'].set()

        self.server = Server(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def parent(self, number):
        return next((request for request in self.requests if not request['child'] and request['number'] == number), None)

    def child(self):
        return next((request for request in self.requests if request['child']), None)

    def close(self):
        self.closed.set()
        self.child_release.set()
        self.report_release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--record', type=Path, help='Write observed rows as JSON')
    parser.add_argument('--screenshot', type=Path, help='Save the composer footer while the child report is handled')
    parser.add_argument('--expect-bug', action='store_true',
                        help='Reproduce: require the stale Done footer and the busy prompt error')
    args = parser.parse_args()
    os.environ['UMEKO_LANGUAGE'] = 'zh' if args.screenshot else 'en'
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

    provider = ScriptedProvider()
    samples, violations, observed = [], [], {}
    app = engine = backend = window = None
    base = os.environ.get('UMEKO_TEST_ROOT')
    if base:
        Path(base).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='umeko-subagent-report-', dir=base) as sandbox, ExitStack() as mocks:
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
        # Observe native Pi run boundaries of every session, tagged by session id.
        observer = sandbox / 'observe-pi.mjs'
        native_module = ROOT / 'runtime/releases' / pi_runtime.RELEASE_NAME / 'node_modules/@earendil-works/pi-coding-agent/dist/core/agent-session.js'
        observer.write_text('''const {AgentSession} = await import(''' + json.dumps(native_module.as_uri()) + ''');
const original = AgentSession.prototype._emit;
AgentSession.prototype._emit = function(event) {
  if (['agent_start','agent_end','agent_settled'].includes(event.type))
    process.stdout.write(JSON.stringify({type:'pi_event', event:event.type,
      session:this.sessionManager?.getSessionId?.() || ''})+'\\n');
  return original.call(this, event);
};
''', encoding='utf-8')
        original_overrides = pi_sessions.npm_overrides
        node_options = os.environ.get('NODE_OPTIONS', '') + ' --import=' + observer.as_uri()
        mocks.enter_context(patch.object(pi_sessions, 'npm_overrides',
            lambda agent: {**original_overrides(agent), 'NODE_OPTIONS': node_options}))
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
                # The rendered footer and composer items, not backend properties.
                status = find('turnStatus')
                text = find('taskStatusText', status) if status is not None else None
                composer = find('composerTaskStatus')
                button = find('sendButton')
                row = {'index': len(samples), 'source': source,
                       'footerState': status.property('state') if status is not None else None,
                       'footerText': text.property('text') if text is not None else None,
                       'composerState': composer.property('state') if composer is not None else None,
                       'stopAction': bool(button.property('stopAction')) if button is not None else None,
                       'buttonEnabled': not button.property('disabled') if button is not None else None,
                       'phase': backend._view.phase}
                if event is not None:
                    row['event'] = {key: event[key] for key in ('type', 'event', 'session', 'role', 'stopReason', 'text', 'message') if key in event}
                samples.append(row)
                return row

            def on_event(record, event):
                if record is backend._view:
                    snapshot('pi' if event.get('type') == 'pi_event' else 'bridge', event)

            backend._pool.event.connect(on_event)
            loop = QEventLoop()

            def until(predicate, label, seconds=60):
                deadline = time.monotonic() + seconds
                while not predicate():
                    assert time.monotonic() < deadline, (label, samples[-10:], provider.errors)
                    assert not provider.errors, provider.errors
                    QTimer.singleShot(10, loop.quit)
                    loop.exec()

            def seen(kind, after=0, **fields):
                return next((row for row in samples[after:] if row.get('event', {}).get('type') == kind
                             and all(row['event'].get(key) == value for key, value in fields.items())), None)

            def bridge_events(after=0):
                return [row['event'] for row in samples[after:] if row['source'] == 'bridge']

            backend.newSession()
            assert backend.send('Delegate a background probe, then finish.'), 'Initial backend.send was rejected'
            until(lambda: provider.child() is not None and provider.child()['streamed'].is_set(), 'Background child started')
            until(lambda: seen('done') and not backend.busy and provider.parent(2) is not None
                  and provider.parent(2)['finished'].is_set(), 'Parent finished its own turn')
            parent_session = backend._view.id
            first = snapshot('parent-turn-done')
            observed['parentDone'] = first
            if first['footerState'] != 'finished' or first['stopAction']:
                violations.append('parent turn did not end as Done: ' + str(first))

            mark = len(samples)
            provider.child_release.set()
            until(lambda: provider.parent(3) is not None and provider.parent(3)['streamed'].is_set()
                  and seen('pi_event', mark, event='agent_start', session=parent_session)
                  and seen('delta', mark), 'Child report started a parent run')
            # Let the queued Qt/QML updates for this run settle on real events.
            until(lambda: any('HANDLING_CHILD_REPORT_140' in str(row.get('event', {}).get('text', ''))
                              for row in samples[mark:]), 'Report draft reached the desktop')
            during = snapshot('report-run-streaming')
            observed['reportRun'] = during
            if args.screenshot:
                # Screenshot only: let the button's 150 ms colour animation finish.
                settle = time.monotonic() + 0.4
                until(lambda: time.monotonic() > settle, 'Footer animation settled')
                grab_footer(window, find, args.screenshot)

            send_mark = len(samples)
            accepted = backend.send(USER_TEXT)
            snapshot('action-send-during-report')
            observed['sendAccepted'] = accepted
            if args.expect_bug:
                until(lambda: any(event.get('type') == 'error' and BUSY_ERROR in event.get('message', '')
                                  for event in bridge_events(send_mark)), 'Busy prompt error')
                observed['error'] = next(event['message'] for event in bridge_events(send_mark)
                                         if event.get('type') == 'error')
                provider.report_release.set()
                until(lambda: provider.parent(3)['finished'].is_set() and seen('pi_event', send_mark, event='agent_settled',
                                                                             session=parent_session), 'Report run ended')
                stale = during['footerState'] == 'finished' and not during['stopAction'] and during['phase'] == 'idle'
                if not stale:
                    violations.append('expected the stale Done footer while Pi processed the report: ' + str(during))
            else:
                assert during['footerState'] == 'running' and during['stopAction'] and during['buttonEnabled'],                     'Child report run is not shown as Running with an enabled Stop: ' + str(during)
                until(lambda: any(item.get('text') == USER_TEXT and item.get('mode') == 'followUp'
                                  for item in backend._view.queue), 'Message entered the follow-up queue')
                queued = snapshot('message-queued')
                if queued['footerState'] != 'running' or not queued['stopAction']:
                    violations.append('queued message changed the Running footer: ' + str(queued))
                provider.report_release.set()
                until(lambda: provider.parent(4) is not None and provider.parent(4)['finished'].is_set(),
                      'Queued message reached the model')
                if not any(USER_TEXT in text for text in provider.parent(4)['users']):
                    violations.append('follow-up request lacks the queued message: ' + str(provider.parent(4)['users']))
                until(lambda: seen('done', send_mark) and not backend.busy, 'Report run finished')
                final = snapshot('report-run-done')
                observed['final'] = final
                if final['footerState'] != 'finished' or final['stopAction']:
                    violations.append('report run did not end as Done: ' + str(final))
                errors = [event for event in bridge_events(send_mark) if event.get('type') == 'error']
                if errors:
                    violations.append('send during report produced errors: ' + str(errors))
                if not accepted:
                    violations.append('backend.send rejected the message during the report run')
            assert not provider.errors, provider.errors
            assert not warnings, '\n'.join(warnings)
        finally:
            if args.record:
                args.record.parent.mkdir(parents=True, exist_ok=True)
                args.record.write_text(json.dumps({'observed': observed, 'violations': violations,
                    'requests': [{key: value for key, value in request.items() if key in ('child', 'number', 'users')}
                                 for request in provider.requests], 'events': samples},
                    indent=2, ensure_ascii=False), encoding='utf-8')
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
    print('SUBAGENT_REPORT_STATUS ' + json.dumps(observed, ensure_ascii=False), flush=True)
    assert not violations, '\n'.join(violations)
    print('SUBAGENT_REPORT_STATUS_UI_OK' + (' (bug reproduced)' if args.expect_bug else ''), flush=True)


def grab_footer(window, find, path):
    from PySide6.QtCore import QPointF, QRect
    image = window.grabWindow()
    status = find('turnStatus')
    composer = find('sendButton')
    top = int(status.mapToScene(QPointF(0, 0)).y()) - 40 if status is not None else image.height() - 220
    bottom = int(composer.mapToScene(QPointF(0, composer.height())).y()) + 24 if composer is not None else image.height()
    top = max(0, top)
    bottom = min(image.height(), max(bottom, top + 120))
    path.parent.mkdir(parents=True, exist_ok=True)
    assert image.copy(QRect(0, top, image.width(), bottom - top)).save(str(path)), 'Footer screenshot was not saved'


if __name__ == '__main__':
    main()
