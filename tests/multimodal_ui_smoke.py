"""Offscreen settings and real Pi -> private gateway -> local fake provider round trip.

Assertions follow saved state and completion events, never animation/frame timing.
Run with --screenshots to capture the documented Chinese and English examples.
"""
import base64
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')

from PySide6.QtCore import Q_ARG, QBuffer, QByteArray, QCoreApplication, QEventLoop, QIODevice, QMetaObject, QTimer, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from app.multimodal_settings import DEFAULTS
from app.storage import Store
from app.transcripts import preview


def until(predicate, detail):
    def ready():
        try:
            return predicate()
        except AssertionError:
            return False
    if ready():
        return
    loop = QEventLoop()
    tick = QTimer()
    tick.setInterval(0)
    tick.timeout.connect(lambda: loop.quit() if ready() else None)
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    tick.start()
    deadline.start(60000)
    loop.exec()
    tick.stop()
    deadline.stop()
    assert ready(), detail()


def find(window, name):
    stack = [window.contentItem()]
    while stack:
        item = stack.pop()
        if item.objectName() == name:
            return item
        stack.extend(item.childItems())
    raise AssertionError('Missing QML item: ' + name)


def screenshot(window, destination):
    # Documentation only: let existing visual transitions finish before capture.
    # Test assertions never use this delay or depend on animation pacing.
    loop = QEventLoop()
    QTimer.singleShot(500, loop.quit)
    window.requestUpdate()
    loop.exec()
    if not window.grabWindow().save(str(destination)):
        raise OSError('Could not save documentation screenshot')


def image_fixture():
    image = QImage(640, 240, QImage.Format_RGB32)
    image.fill(QColor('#e7f1ed'))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor('#b4cfc1'))
    painter.drawEllipse(390, 25, 160, 160)
    painter.setBrush(QColor('#577e6c'))
    painter.drawRoundedRect(50, 115, 520, 90, 24, 24)
    painter.setBrush(QColor('#d9bca0'))
    painter.drawRoundedRect(85, 55, 150, 125, 24, 24)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    assert image.save(buffer, 'PNG')
    return bytes(data)


def audio_fixture():
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as sound:
        sound.setnchannels(1)
        sound.setsampwidth(2)
        sound.setframerate(8000)
        sound.writeframes(b'\0\0' * 800)
    return buffer.getvalue()


class FakeProvider(BaseHTTPRequestHandler):
    image = b''
    audio = audio_fixture()
    generated = []
    model_requests = []
    releases = {}

    def log_message(self, *_):
        pass

    def respond(self, data, content_type='application/json'):
        if not isinstance(data, bytes):
            data = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path == '/v1/images/generations':
            self.generated.append(('image', body))
            assert self.releases['image'].wait(45)
            return self.respond({'data': [{'b64_json': base64.b64encode(self.image).decode()}]})
        if self.path == '/v1/audio/speech':
            self.generated.append(('speech', body))
            assert self.releases['speech'].wait(45)
            return self.respond(self.audio, 'audio/wav')
        assert self.path == '/v1/chat/completions', self.path
        self.model_requests.append(body)
        completed = {m.get('tool_call_id') for m in body['messages'] if m['role'] == 'tool'}
        if 'image-call' not in completed:
            call = {'id': 'image-call', 'name': 'image_gen', 'arguments': {'prompt': 'A calm green studio illustration', 'output_filename': 'generated-image.png'}}
        elif 'voice-call' not in completed:
            call = {'id': 'voice-call', 'name': 'voice_gen', 'arguments': {'text': 'Welcome to your creative workspace.', 'format': 'wav', 'output_filename': 'generated-voice.wav'}}
        else:
            call = None
        text = '图片和语音文件已生成，可以点击下方文件查看。' if '中文' in json.dumps(body['messages'], ensure_ascii=False) else 'The image and voice file are ready. Open them from the cards below.'
        message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': call['id'], 'type': 'function', 'function': {'name': call['name'], 'arguments': json.dumps(call['arguments'])}}]} if call else {'role': 'assistant', 'content': text}
        self.respond({'id': 'local-completion', 'object': 'chat.completion', 'created': 1, 'model': 'test-image-model',
                      'choices': [{'index': 0, 'message': message, 'finish_reason': 'tool_calls' if call else 'stop'}],
                      'usage': {'prompt_tokens': 20, 'completion_tokens': 20, 'total_tokens': 40}})


def run():
    with tempfile.TemporaryDirectory(prefix='umeko-multimodal-ui-') as temporary_profile:
        profile = str(Path(temporary_profile).resolve())
        os.environ['UMEKO_DATA_DIR'] = profile
        store = Store(Path(profile))
        store.data['agent'].update(agentDir=str(Path(profile) / 'agent'), autoCompaction=False)
        store.data['server']['port'] = 0
        store.save()
        server = ThreadingHTTPServer(('127.0.0.1', 0), FakeProvider)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        with patch('app.provider_plugins.BundledProviders.sync', return_value=[]), \
                patch('app.tray.QSystemTrayIcon.isSystemTrayAvailable', return_value=False), \
                patch('app.tray.QSystemTrayIcon.showMessage'), \
                patch('app.controller.QDesktopServices.openUrl', return_value=True):
            from main import create_application
            app, engine, backend = create_application()
        window = engine.rootObjects()[0]
        warnings = []
        engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
        FakeProvider.image = image_fixture()
        approvals = []
        def approve():
            if backend.pendingApproval:
                approvals.append(dict(backend.pendingApproval))
                backend.respondApproval(True)
        backend.approvalChanged.connect(approve)
        try:
            window.resize(1320, 1200)
            base_url = f'http://127.0.0.1:{server.server_port}/v1'
            assert backend.saveProvider('', 'Chat LLM', 'openai', base_url, 'local-test-key', 'test-image-model')
            backend.store.data['providers'][0]['proxy'] = {'mode': 'direct', 'url': ''}
            workspace = Path(profile) / 'workspace'
            workspace.mkdir()
            backend.store.data['workspace'] = str(workspace)
            backend._view.workspace = str(workspace)
            backend.changed.emit()
            window.setProperty('page', 'settings')
            window.setProperty('settingsTab', 0)
            assert QMetaObject.invokeMethod(find(window, 'multimodalSettingsEntry'), 'clicked')
            until(lambda: find(window, 'multimodalSettings').isVisible(), lambda: str(warnings))

            def click(name):
                control = find(window, name)
                assert control.isVisible() and QMetaObject.invokeMethod(control, 'clicked'), name
                QCoreApplication.processEvents()

            def category(kind):
                click('multimodalCategory_' + kind)
                name = 'auxiliaryVisionModel' if kind == 'vision' else kind + 'GenerationModel'
                until(lambda: find(window, name).isVisible(), lambda: str(warnings))

            assert not find(window, 'apiProvidersSection').isVisible()
            for kind in ('vision', 'image', 'speech', 'video'):
                assert find(window, 'multimodalCategory_' + kind).isVisible()
                category(kind)
                if kind != 'vision':
                    assert find(window, kind + 'GenerationModel').property('count') == 1
                click('backMultimodalSettings')

            assert backend.saveCustomMultimodalProvider('image', json.dumps({
                'name': 'Test provider', 'baseUrl': base_url, 'model': 'test-image-model', 'key': 'local-test-key'}))
            assert backend.saveCustomMultimodalProvider('speech', json.dumps({
                'name': 'Test provider', 'baseUrl': base_url, 'model': 'test-voice-model', 'key': 'local-test-key'}))
            providers_by_kind = {p['api']: p for p in backend.store.data['providers'] if p['api'] in ('image', 'speech')}
            for provider in providers_by_kind.values():
                provider['proxy'] = {'mode': 'direct', 'url': ''}
            backend.changed.emit()

            category('image')
            picker = find(window, 'imageGenerationModel')
            assert picker.property('count') == 2
            assert QMetaObject.invokeMethod(picker, 'activated', Q_ARG(int, 1))
            size = find(window, 'imageGenerationSize')
            size.setProperty('text', '640x240')
            assert backend.saveAuxiliaryVision('{"autoAnalyze":false}')
            assert size.property('text') == '640x240', 'Vision changes must preserve the image draft'
            size.setProperty('text', '')
            click('saveMultimodalSettings')
            assert backend.store.data['multimodal']['image']['model'] == 'test-image-model'
            click('backMultimodalSettings')

            category('speech')
            picker = find(window, 'speechGenerationModel')
            assert picker.property('count') == 2
            assert QMetaObject.invokeMethod(picker, 'activated', Q_ARG(int, 1))
            click('saveMultimodalSettings')
            assert backend.store.data['multimodal']['speech']['voice'] == ''
            find(window, 'speechGenerationVoice').setProperty('text', 'test-voice')
            click('saveMultimodalSettings')
            assert backend.store.data['multimodal']['speech']['voice'] == 'test-voice'
            assert Store(Path(profile)).data['multimodal'] == backend.store.data['multimodal']
            click('backMultimodalSettings')
            click('backMultimodalSettings')
            assert find(window, 'apiProvidersSection').isVisible()
            screenshot_dir = ROOT / 'docs/images'
            screenshot_dir.mkdir(exist_ok=True)
            capture = '--screenshots' in sys.argv
            for language in ('zh', 'en'):
                backend.setLanguage(language)
                window.setProperty('page', 'settings')
                if not find(window, 'multimodalSettings').isVisible():
                    assert QMetaObject.invokeMethod(find(window, 'multimodalSettingsEntry'), 'clicked')
                until(lambda: find(window, 'multimodalSettings').isVisible(), lambda: str(warnings))
                QCoreApplication.processEvents()
                for kind in ('image', 'speech'):
                    category(kind)
                    card = find(window, kind + 'GenerationSettings')
                    picker = find(window, kind + 'GenerationModel')
                    assert card.property('providerId') == providers_by_kind[kind]['id']
                    assert card.property('modelId') == backend.store.data['multimodal'][kind]['model']
                    assert picker.property('displayText').endswith(' · Test provider')
                    if kind == 'speech':
                        assert find(window, 'speechGenerationVoice').property('text') == 'test-voice'
                    click('backMultimodalSettings')
                if capture:
                    window.resize(1320, 1700)
                    screenshot(window, screenshot_dir / f'multimodal-models-{language}.png')
                    window.resize(1320, 1200)
                window.setProperty('page', 'chat')
                if language == 'en':
                    backend.newSession()
                    backend._view.workspace = str(workspace)
                FakeProvider.generated.clear()
                FakeProvider.model_requests.clear()
                FakeProvider.releases = {kind: threading.Event() for kind in ('image', 'speech')}
                approvals.clear()
                prompt = '请生成一张图片和一段语音，并用中文回复。' if language == 'zh' else 'Create an image and a voice file for this workspace.'
                assert backend.send(prompt)
                def card_visible(name):
                    try:
                        return find(window, name).isVisible()
                    except AssertionError:
                        return False
                for kind, call in (('image', 'image-call'), ('speech', 'voice-call')):
                    card = 'chatboxGenerating_' + call
                    spinner = 'chatboxGeneratingSpinner_' + call
                    until(lambda: card_visible(card), lambda: backend.toolStatus + '; ' + str(warnings))
                    assert find(window, spinner).property('running')
                    assert find(window, card).width() < 260
                    label = find(window, card).property('label')
                    expected = (('正在生成语音…' if kind == 'speech' else '正在生成图片…') if language == 'zh'
                                else ('Generating audio…' if kind == 'speech' else 'Generating image…'))
                    assert label == expected
                    if language == 'zh' and kind == 'image' and os.environ.get('UMEKO_GENERATION_PREVIEW'):
                        screenshot(window, Path(os.environ['UMEKO_GENERATION_PREVIEW']))
                    FakeProvider.releases[kind].set()
                    until(lambda: not card_visible(card), lambda: str(warnings))
                until(lambda: not backend.busy, lambda: backend.toolStatus + '; ' + str(warnings))
                assert len(approvals) == 2, approvals
                assert all(a['method'] == 'confirm' and 'Test provider' in a['detail'] for a in approvals)
                assert [kind for kind, _ in FakeProvider.generated] == ['image', 'speech'], FakeProvider.generated
                assert FakeProvider.generated[0][1]['model'] == 'test-image-model'
                assert FakeProvider.generated[1][1]['model'] == 'test-voice-model'
                media = [item for row in backend.displayMessages for activity in row.get('activity', [])
                         if activity['kind'] == 'media' for item in activity['items']]
                assert {item['kind'] for item in media} == {'image', 'audio'}, media
                assert all(Path(item['path']).is_file() and Path(item['path']).parent == workspace for item in media)
                # Real provider context receives paths and no base64 or image blocks.
                last = FakeProvider.model_requests[-1]
                assert all(not isinstance(m.get('content'), list) or all(c.get('type') != 'image_url' for c in m['content']) for m in last['messages'])
                assert not any(base64.b64encode(FakeProvider.image).decode() in json.dumps(m) for m in last['messages'])
                until(lambda: find(window, 'chatboxImage_image-call_0').property('loaded'), lambda: str(warnings))
                assert find(window, 'chatboxCard_image-call_0').isVisible()
                assert find(window, 'chatboxCard_voice-call_0').isVisible()
                assert find(window, 'chatboxAudioPlay_voice-call_0').isVisible()
                assert find(window, 'chatboxAudioSeek_voice-call_0').isVisible()
                assert find(window, 'chatboxAudioVolumeButton_voice-call_0').isVisible()
                backend._view.messages, backend._view.tree = preview(backend._view.file)
                backend.chatChanged.emit()
                restored = [item for row in backend.displayMessages for activity in row.get('activity', [])
                            if activity['kind'] == 'media' for item in activity['items']]
                assert [item['path'] for item in restored] == [item['path'] for item in media]
                if capture:
                    window.resize(1320, 860)
                    screenshot(window, screenshot_dir / f'multimodal-chat-{language}.png')
                    window.resize(1320, 1200)
            backend.newSession()
            record = backend._view
            for outcome in ('error', 'exit'):
                call = 'pending-' + outcome
                tool_event = {'type': 'tool', 'id': call, 'name': 'voice_gen', 'state': 'running'}
                backend._handle_pi_event(record, tool_event)
                assert not card_visible('chatboxGenerating_' + call), 'Waiting for approval is not generating'
                backend._handle_pi_event(record, {**tool_event, 'generationPending': True})
                until(lambda: card_visible('chatboxGenerating_' + call), lambda: str(warnings))
                if outcome == 'exit':
                    backend._handle_pi_event(record, {'type': 'exit'})
                else:
                    backend._handle_pi_event(record, {**tool_event, 'state': 'error', 'result': 'Cancelled'})
                until(lambda: not card_visible('chatboxGenerating_' + call), lambda: str(warnings))
            assert not warnings, warnings
            print('MULTIMODAL_UI_OK: bilingual settings, default models, Pi confirmations, image/audio results and pending-card cleanup')
        finally:
            for gate in FakeProvider.releases.values(): gate.set()
            backend.close()
            window.hide()
            import shiboken6
            shiboken6.delete(engine)
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    run()
