"""Real settings and Pi image_gen through native and custom protocols on loopback."""
import base64
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
temp = tempfile.TemporaryDirectory(prefix='umeko-image-settings-'); base = Path(temp.name)
os.environ.update(UMEKO_DATA_DIR=str(base/'profile'), PI_CODING_AGENT_DIR=str(base/'agent'), UMEKO_LANGUAGE='zh')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen'); os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QObject, Qt
from PySide6.QtTest import QTest
from app.storage import Store
from main import create_application

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAUAAAAC0CAIAAABqhmJGAAACJ0lEQVR4nO3TQQ0AIBDAsDOKHUSgFg98yJImFbDPZp0NRM33AuCZgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEGZgCDMwhBkYwgwMYQaGMANDmIEhzMAQZmAIMzCEGRjCDAxhBoYwA0OYgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEGZgCDMwhBkYwgwMYQaGMANDmIEhzMAQZmAIMzCEGRjCDAxhBoYwA0OYgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEGZgCDMwhBkYwgwMYQaGMANDmIEhzMAQZmAIMzCEGRjCDAxhBoYwA0OYgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEGZgCDMwhBkYwgwMYQaGMANDmIEhzMAQZmAIMzCEGRjCDAxhBoYwA0OYgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEGZgCDMwhBkYwgwMYQaGMANDmIEhzMAQZmAIMzCEGRjCDAxhBoYwA0OYgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEGZgCDMwhBkYwgwMYQaGMANDmIEhzMAQZmAIMzCEGRjCDAxhBoYwA0OYgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEGZgCDMwhBkYwgwMYQaGMANDmIEhzMAQZmAIMzCEGRjCDAxhBoYwA0OYgSHMwBBmYAgzMIQZGMIMDGEGhjADQ5iBIczAEHYBQnrwk3UEUloAAAAASUVORK5CYII=')
calls = []; chat_requests = []
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def reply(self, value, mime='application/json'):
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        self.send_response(200); self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        if self.path.endswith('/models'): return self.reply({'data': []})
        calls.append((self.path, dict(self.headers), None)); self.reply(PNG, 'image/png')
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path.endswith('/chat/completions'):
            chat_requests.append(body)
            done = any(m['role'] == 'tool' and m.get('tool_call_id') == 'image-call' for m in body['messages'])
            call = None if done else {'id': 'image-call', 'type': 'function', 'function': {'name': 'image_gen',
                'arguments': json.dumps({'prompt': 'A small orange cat', 'output_filename': 'generated.png'})}}
            message = {'role': 'assistant', 'content': 'Done.' if done else None}
            if call: message['tool_calls'] = [call]
            return self.reply({'id': 'fixture', 'model': 'text-fixture', 'choices': [{'index': 0, 'message': message, 'finish_reason': 'stop' if done else 'tool_calls'}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 10}})
        calls.append((self.path, dict(self.headers), body))
        url = f'http://127.0.0.1:{self.server.server_port}/result.png'
        if 'multimodal-generation' in self.path:
            self.reply({'output': {'choices': [{'message': {'content': [{'image': url}]}}]}})
        else:
            self.reply({'data': [{'url': url}]})

server = ThreadingHTTPServer(('127.0.0.1', 0), Handler); server.daemon_threads = True
worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
work = base/'work'; work.mkdir()
seed = Store(); seed.data['agent'].update(agentDir=str(base/'agent'), autoCompaction=False)
seed.data['workspace'] = str(work); seed.data['desktop']['webDisplay'] = 'external'
seed.data['providers'] = [{'id': 'chat', 'name': 'Local chat', 'api': 'openai', 'baseUrl': f'http://127.0.0.1:{server.server_port}/v1', 'key': 'fixture-chat-key',
    'models': [{'upstream': 'text-fixture', 'alias': 'text-fixture', 'vision': False, 'visionAuto': False,
                'reasoningLevels': [], 'reasoningLevelsAuto': False, 'reasoningFormat': 'openai', 'reasoningFormatAuto': False}]}]
seed.data.update(selectedProvider='chat', selectedModel='text-fixture'); seed.save()
seed.data['sessionMeta'] = {f'history-{i}': {'draft': 'Preserved draft '+str(i), 'viewport': {'index': i, 'offset': 24}} for i in range(1000)}
seed.save()
app = engine = b = None
output = ROOT/'build/image-providers-ui'; output.mkdir(parents=True, exist_ok=True)
try:
    with patch('app.controller.Controller.loadNativeIndex', lambda self: None):
        app, engine, b = create_application()
    window = engine.rootObjects()[0]; window.resize(1250, 1000)
    warnings = []; engine.warnings.connect(lambda rows: warnings.extend(row.toString() for row in rows))
    def find(name):
        pending = [window.contentItem()]
        while pending:
            item = pending.pop()
            if item.objectName() == name: return item
            pending.extend(item.childItems())
        return window.findChild(QObject, name)
    def wait(check, label):
        deadline = time.monotonic()+45
        while not check():
            assert time.monotonic() < deadline, label+' '+str(warnings)+' '+b.toolStatus
            QTest.qWait(20)
    def click(name):
        item = find(name); assert item is not None and item.isVisible() and item.isEnabled(), name
        QTest.qWait(80); window.grabWindow()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, item.mapToScene(item.boundingRect().center()).toPoint()); QTest.qWait(80)
    def open_providers():
        window.setProperty('page', 'settings'); window.setProperty('settingsTab', 0); QTest.qWait(100)
        wait(lambda: find('multimodalSettingsEntry') is not None, 'Settings did not load')
        if not find('multimodalSettings').isVisible(): click('multimodalSettingsEntry')
        # The image card is below the two auxiliary-vision switches.
        flick = find('settingsScroll').property('contentItem')
        target = find('manageImageProviders')
        flick.setProperty('contentY', max(0, target.mapToItem(flick, target.boundingRect().topLeft()).y()+flick.property('contentY')-150))
        QTest.qWait(100); click('manageImageProviders')
        wait(lambda: find('imageProvider_qwen-image').isVisible(), 'Provider picker did not open')

    # Existing unsaved speech inputs survive adding or activating an image account.
    open_providers()
    find('speechGenerationVoice').setProperty('text', 'Unsaved voice draft')
    for preset_id, name in [('volcengine-image', '火山方舟'), ('qwen-image', '阿里云百炼')]:
        assert find('imageProviderName_'+preset_id).property('text') == name
        wait(lambda: find('imageProviderLogo_'+preset_id).property('progress') == 1., 'Platform logo did not load')
    window.grabWindow().save(str(output/'providers-zh.png'))
    for index, (preset_id, path) in enumerate([('qwen-image', '/api/services/aigc/multimodal-generation/generation'), ('volcengine-image', '/api/images/generations'), ('openai-image', '/api/images/generations')]):
        if index:
            open_providers()
            find('speechGenerationVoice').setProperty('text', 'Unsaved voice draft')
        click('imageProvider_'+preset_id)
        key = find('imageProviderKey'); assert key.property('text') == ''
        link = find('imageProviderKeyLink').property('targetUrl')
        if preset_id == 'openai-image':
            assert not find('imageProviderKeyLink').isVisible()
            find('imageProviderCustomName').setProperty('text', 'My image service')
            find('imageProviderCustomUrl').setProperty('text', f'http://127.0.0.1:{server.server_port}/api')
            find('imageProviderCustomModel').setProperty('text', 'custom-image')
        else:
            assert link.startswith('https://') and ('bailian.console.aliyun.com' in link if preset_id == 'qwen-image' else 'ark.volcengine.com' in link)
        window.grabWindow().save(str(output/(preset_id+'-key.png')))
        key.setProperty('text', 'fixture-image-key')
        assert key.property('displayText') != 'fixture-image-key'
        click('saveImageProvider')
        wait(lambda: not find('imageProviderDialog').property('visible'), 'Saving did not close the dialog')
        assert find('speechGenerationVoice').property('text') == 'Unsaved voice draft'
        selection = b.store.data['multimodal']['image']; provider = b.gateway.provider(selection['providerId'])
        assert provider['presetId'] == preset_id
        assert find('imageGenerationProvider').property('currentIndex') > 0
        assert find('imageGenerationModel').property('currentIndex') > 0
        assert provider['id'] not in {row['providerID'] for row in b.gateway.models()}
        assert find('imageGenerationQuality').isVisible() == (preset_id == 'openai-image')
        if preset_id != 'openai-image':
            models = find('imageGenerationSettings').property('models').toVariant()
            assert len(models) == (4 if preset_id == 'qwen-image' else 6), models
            if preset_id == 'volcengine-image':
                card = find('imageGenerationSettings')
                card.setProperty('modelId', 'doubao-seedream-4-5-251128'); QTest.qWait(80)
                assert not find('imageGenerationCount').property('readOnly')
                assert card.property('formats').toVariant() == ['', 'jpeg']
                card.setProperty('modelId', selection['model']); QTest.qWait(80)
                assert find('imageGenerationCount').property('readOnly')
            click('imageGenerationModel')
            window.grabWindow().save(str(output/(preset_id+'-models.png')))
            QTest.keyClick(window, Qt.Key_Escape); QTest.qWait(80)
        # Loopback endpoint override is test-only; the UI saves official defaults.
        provider['baseUrl'] = f'http://127.0.0.1:{server.server_port}/api'; b.store.save()
        approvals = []
        def approve():
            if b.pendingApproval:
                approvals.append(dict(b.pendingApproval)); b.respondApproval(True)
        b.approvalChanged.connect(approve)
        window.setProperty('page', 'chat')
        if calls: b.newSession()
        assert b.send('Generate a small image with image_gen.')
        wait(lambda: not b.busy, 'Pi did not complete image generation')
        b.approvalChanged.disconnect(approve)
        assert len(approvals) == 1, approvals
        native = [call for call in calls if call[2] is not None][-1]
        assert native[0] == path, calls
        assert native[1]['Authorization'] == 'Bearer fixture-image-key'
        if preset_id == 'openai-image':
            assert native[2] == {'model': 'custom-image', 'prompt': 'A small orange cat', 'n': 1, 'output_format': 'png'}
        assert 'Authorization' not in calls[-1][1]
        wait(lambda: find('chatboxImage_image-call_0') is not None and find('chatboxImage_image-call_0').property('loaded'), 'Generated image did not load in chat')
        assert find('chatboxCard_image-call_0').isVisible()
        assert (work/'generated.png').is_file()
        assert all('fixture-image-key' not in json.dumps(body) for body in chat_requests)
        assert all(base64.b64encode(PNG).decode() not in json.dumps(body) for body in chat_requests)
        window.grabWindow().save(str(output/(preset_id+'-chat.png')))

    # Existing custom accounts can be edited independently and never refill keys.
    custom_id = b.store.data['multimodal']['image']['providerId']
    open_providers(); click('editImageProvider_'+custom_id)
    assert find('imageProviderKey').property('text') == ''
    assert find('imageProviderCustomName').property('text') == 'My image service'
    assert find('imageProviderCustomModel').property('text') == 'custom-image'
    for language, scale in [('zh', 1.), ('en', 2.)]:
        b.setLanguage(language); b.setFontScale(scale); QTest.qWait(200)
        viewport = find('imageProviderScroll')
        for name in ['imageProviderCustomName', 'imageProviderCustomUrl', 'imageProviderCustomModel', 'imageProviderKey', 'saveImageProvider']:
            item = find(name); position = item.mapToItem(viewport, item.boundingRect().topLeft())
            assert position.x() >= -.5 and position.x()+item.width() <= viewport.width()+.5, (language, name)
        window.grabWindow().save(str(output/('custom-'+language+'.png')))
    b.setLanguage('zh'); b.setFontScale(1.); QTest.qWait(100)
    find('imageProviderCustomName').setProperty('text', 'Renamed image service')
    click('saveImageProvider')
    assert b.gateway.provider(custom_id)['name'] == 'Renamed image service'
    open_providers(); click('editImageProvider_'+custom_id); click('removeImageProvider')
    assert b.gateway.provider(custom_id) is None
    click('closeImageProviderDialog')
    open_providers(); click('imageProvider_qwen-image')
    assert find('imageProviderKey').property('text') == ''
    for language, scale in [('zh', 1.), ('en', 2.)]:
        b.setLanguage(language); b.setFontScale(scale); QTest.qWait(200)
        viewport = find('imageProviderScroll')
        for name in ['imageProviderKey', 'imageProviderKeyLink', 'saveImageProvider', 'closeImageProviderDialog']:
            item = find(name); position = item.mapToItem(viewport, item.boundingRect().topLeft())
            assert position.x() >= -.5 and position.x()+item.width() <= viewport.width()+.5, (language, name, position.x(), item.width(), viewport.width())
        window.grabWindow().save(str(output/('key-'+language+'.png')))
    b.setLanguage('zh'); b.setFontScale(1.)
    click('removeImageProvider')
    assert all(p['presetId'] != 'qwen-image' for p in b.imageProviders)
    assert not b.store.data['multimodal']['image']['providerId']
    click('imageProvider_volcengine-image'); click('removeImageProvider')
    assert not b.imageProviders and not b.store.data['multimodal']['image']['providerId']
    assert b.store.data['sessionMeta']['history-999']['draft'] == 'Preserved draft 999'
    assert not warnings, '\n'.join(warnings)
    print('IMAGE_PROVIDERS_UI_OK: platform logos, separate model catalog, native and custom accounts, hidden keys, draft preservation, bilingual scaling, real Pi confirmation and all three image transports into chat')
finally:
    if b: b.close()
    if engine:
        import shiboken6
        shiboken6.delete(engine)
    server.shutdown(); server.server_close(); worker.join(); temp.cleanup()
