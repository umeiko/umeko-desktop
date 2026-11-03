"""Windowless Pi -> gateway -> fake video jobs, progress, Stop and history.

The fake job advances by request count. Events gate screenshots/cancellation;
deadlines only bound hung fixtures and no assertions measure elapsed time.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_QUICK_BACKEND'] = 'software'
from PySide6.QtCore import Q_ARG, QCoreApplication, QMetaObject
from app.storage import Store
from app.transcripts import preview
from tests.multimodal_ui_smoke import find, screenshot, until

VIDEO = b'\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom'


class FakeProvider(BaseHTTPRequestHandler):
    requests = []
    polls = 0
    release = threading.Event()
    deleted = threading.Event()

    def log_message(self, *_):
        pass

    def respond(self, value, mime='application/json'):
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        try:
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.requests.append(('POST', self.path, body))
        if self.path == '/v1/videos':
            return self.respond({'id': 'video-test', 'status': 'queued', 'progress': 0})
        assert self.path == '/v1/chat/completions', self.path
        completed = any(m['role'] == 'tool' for m in body['messages'])
        language = 'zh' if '中文' in json.dumps(body['messages'], ensure_ascii=False) else 'en'
        call = {'id': 'video-call', 'type': 'function', 'function': {'name': 'video_gen', 'arguments': json.dumps({
            'prompt': 'A quiet garden in the morning', 'output_filename': 'garden.mp4'})}}
        message = {'role': 'assistant', 'content': '视频已生成，点击文件卡片打开。' if language == 'zh' else 'Your video is ready. Click the file card to open it.'} if completed else {
            'role': 'assistant', 'content': None, 'tool_calls': [call]}
        self.respond({'id': 'local-completion', 'object': 'chat.completion', 'created': 1, 'model': 'test-video-model',
                      'choices': [{'index': 0, 'message': message, 'finish_reason': 'stop' if completed else 'tool_calls'}],
                      'usage': {'prompt_tokens': 20, 'completion_tokens': 20, 'total_tokens': 40}})

    def do_GET(self):
        self.requests.append(('GET', self.path, None))
        if self.path.endswith('/content'):
            return self.respond(VIDEO, 'video/mp4')
        assert self.path == '/v1/videos/video-test', self.path
        type(self).polls += 1
        if self.polls == 1:
            return self.respond({'id': 'video-test', 'status': 'in_progress', 'progress': 35})
        if not self.release.wait(30):
            raise TimeoutError('Fixture progress was not released')
        self.respond({'id': 'video-test', 'status': 'completed', 'progress': 100})

    def do_DELETE(self):
        self.requests.append(('DELETE', self.path, None))
        self.deleted.set()
        self.respond({'id': 'video-test', 'deleted': True})


def tools(backend):
    return [tool for row in backend.displayMessages for activity in row.get('activity', [])
            if activity['kind'] == 'tools' for tool in activity['tools']]


def media(backend):
    return [item for row in backend.displayMessages for activity in row.get('activity', [])
            if activity['kind'] == 'media' for item in activity['items']]


def run():
    with tempfile.TemporaryDirectory(prefix='umeko-video-ui-') as task_temp:
        profile = Path(task_temp).resolve()
        os.environ['UMEKO_DATA_DIR'] = str(profile)
        os.environ['PI_CODING_AGENT_DIR'] = str(profile / 'agent')
        store = Store(profile)
        store.data['agent'].update(agentDir=str(profile / 'agent'), autoCompaction=False)
        store.data['server']['port'] = 0
        store.save()
        server = ThreadingHTTPServer(('127.0.0.1', 0), FakeProvider)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        from app.generation import generate
        # Only the test injects zero interval. Product defaults remain unchanged.
        with patch('app.provider_plugins.BundledProviders.sync', return_value=[]), \
                patch('app.tray.QSystemTrayIcon.isSystemTrayAvailable', return_value=False), \
                patch('app.tray.QSystemTrayIcon.showMessage'), \
                patch('app.controller.QDesktopServices.openUrl', return_value=True) as open_file, \
                patch('app.generation.generate', side_effect=lambda gateway, body, progress=None, **kw:
                      generate(gateway, body, progress, poll_interval=0)):
            from main import create_application
            app, engine, backend = create_application()
            window = engine.rootObjects()[0]
            warnings, approvals = [], []
            engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
            approved = True

            def approve():
                if backend.pendingApproval:
                    approvals.append(dict(backend.pendingApproval))
                    backend.respondApproval(approved)
            backend.approvalChanged.connect(approve)
            try:
                workspace = profile / 'workspace'
                workspace.mkdir()
                backend.store.data['workspace'] = str(workspace)
                backend._view.workspace = str(workspace)
                assert backend.saveProvider('', 'Test provider', 'openai',
                    f'http://127.0.0.1:{server.server_port}/v1', 'local-test-key', 'test-video-model')
                provider = backend.store.data['providers'][0]
                provider['proxy'] = {'mode': 'direct', 'url': ''}
                backend.changed.emit()
                window.resize(1320, 2000)
                window.setProperty('page', 'settings')
                window.setProperty('settingsTab', 0)
                QMetaObject.invokeMethod(find(window, 'multimodalSettingsEntry'), 'clicked')
                until(lambda: find(window, 'videoGenerationSettings').isVisible(), lambda: str(warnings))
                QMetaObject.invokeMethod(find(window, 'videoGenerationProvider'), 'activated', Q_ARG(int, 1))
                QMetaObject.invokeMethod(find(window, 'videoGenerationModel'), 'activated', Q_ARG(int, 1))
                find(window, 'videoGenerationSeconds').setProperty('text', '8')
                find(window, 'videoGenerationSize').setProperty('text', '1280x720')
                QMetaObject.invokeMethod(find(window, 'saveMultimodalSettings'), 'clicked')
                assert backend.store.data['multimodal']['video'] == {
                    'providerId': provider['id'], 'model': 'test-video-model', 'seconds': '8', 'size': '1280x720'}
                assert Store(profile).data['multimodal'] == backend.store.data['multimodal']
                capture = '--screenshots' in sys.argv
                images = ROOT / 'docs/images'
                for language in ('zh', 'en'):
                    backend.setLanguage(language)
                    window.setProperty('page', 'settings')
                    if not find(window, 'multimodalSettings').isVisible():
                        QMetaObject.invokeMethod(find(window, 'multimodalSettingsEntry'), 'clicked')
                    until(lambda: find(window, 'multimodalSettings').isVisible(), lambda: str(warnings))
                    QCoreApplication.processEvents()
                    assert find(window, 'videoGenerationProvider').property('displayText') == 'Test provider'
                    assert find(window, 'videoGenerationModel').property('displayText') == 'test-video-model'
                    if capture:
                        screenshot(window, images / f'multimodal-models-{language}.png')
                    window.setProperty('page', 'chat')
                    window.resize(1320, 860)
                    backend.newSession()
                    backend._view.workspace = str(workspace)
                    FakeProvider.requests.clear()
                    FakeProvider.polls = 0
                    FakeProvider.release.clear()
                    approvals.clear()
                    prompt = '请生成一段花园视频，用中文回复。' if language == 'zh' else 'Generate a garden video.'
                    assert backend.send(prompt)
                    until(lambda: any(t.get('video', {}).get('progress') == 35 for t in tools(backend)),
                          lambda: repr({'status': backend.toolStatus, 'warnings': warnings,
                                        'requests': [(method, url) for method, url, _ in FakeProvider.requests],
                                        'messages': backend.displayMessages, 'approvals': approvals}))
                    assert backend.busy
                    assert len(approvals) == 1
                    assert 'Test provider' in approvals[0]['detail']
                    assert not media(backend)
                    summaries = []
                    def visit(item):
                        if item.objectName() == 'toolHistorySummary':
                            summaries.append(item.property('text'))
                        for child in item.childItems():
                            visit(child)
                    QCoreApplication.processEvents()
                    visit(window.contentItem())
                    assert any('35%' in value and ('生成中' if language == 'zh' else 'Generating') in value for value in summaries), summaries
                    if capture:
                        screenshot(window, images / f'multimodal-video-running-{language}.png')
                    FakeProvider.release.set()
                    until(lambda: not backend.busy, lambda: backend.toolStatus + '; ' + str(warnings))
                    saved = media(backend)
                    assert len(saved) == 1 and saved[0]['kind'] == 'file', saved
                    path = Path(saved[0]['path'])
                    assert path.parent == workspace and path.read_bytes() == VIDEO
                    assert path.name == ('garden.mp4' if language == 'zh' else 'garden-2.mp4')
                    create = [body for method, url, body in FakeProvider.requests if method == 'POST' and url == '/v1/videos']
                    assert create == [{'model': 'test-video-model', 'prompt': 'A quiet garden in the morning', 'seconds': '8', 'size': '1280x720'}], create
                    assert FakeProvider.polls == 2
                    backend._view.messages, backend._view.tree = preview(backend._view.file)
                    backend.chatChanged.emit()
                    assert [i['path'] for i in media(backend)] == [str(path)]
                    assert find(window, 'chatboxCard_video-call_0').isVisible()
                    if capture:
                        screenshot(window, images / f'multimodal-video-finished-{language}.png')
                    window.resize(1320, 2000)

                # Denial through the actual Pi dialog prevents every video request.
                approved = False
                backend.newSession()
                backend._view.workspace = str(workspace)
                FakeProvider.requests.clear()
                approvals.clear()
                assert backend.send('Generate a garden video, once.')
                until(lambda: not backend.busy, lambda: backend.toolStatus)
                assert len(approvals) == 1
                assert not any(url.startswith('/v1/videos') for _, url, _ in FakeProvider.requests)
                assert not media(backend)

                # Stop at a real progress update, then let a late completion arrive.
                approved = True
                backend.newSession()
                backend._view.workspace = str(workspace)
                FakeProvider.requests.clear()
                FakeProvider.polls = 0
                FakeProvider.deleted.clear()
                FakeProvider.release.clear()
                assert backend.send('Generate another garden video.')
                until(lambda: any(t.get('video', {}).get('progress') == 35 for t in tools(backend)), lambda: backend.toolStatus)
                backend.stop()
                until(lambda: not backend.busy and FakeProvider.deleted.is_set(), lambda: backend.toolStatus)
                poll_count = FakeProvider.polls
                FakeProvider.release.set()
                assert backend._view.cancelled
                assert not media(backend)
                assert sorted(p.name for p in workspace.iterdir()) == ['garden-2.mp4', 'garden.mp4']
                assert FakeProvider.polls == poll_count
                assert not any(url.endswith('/content') for _, url, _ in FakeProvider.requests)
                assert not open_file.called, 'No file or player may open automatically'
                # Explicit open follows the existing file-card system association path.
                backend.openChatboxPath(str(workspace / 'garden.mp4'), False)
                assert open_file.call_count == 1
                assert not warnings, warnings
                print('VIDEO_UI_OK: bilingual configured settings; actual Pi approval/denial; progress; saved collision; history; Stop+DELETE; no autoplay')
            finally:
                FakeProvider.release.set()
                backend.close()
                window.hide()
                import shiboken6
                shiboken6.delete(engine)
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == '__main__':
    run()
