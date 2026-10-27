"""Exercise live desktop mutations, queued changes and caller ownership."""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['UMEKO_DATA_DIR'] = tempfile.mkdtemp(prefix='umeko-control-ui-')
os.environ['UMEKO_LANGUAGE'] = 'zh'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QObject
from PySide6.QtTest import QTest
from main import create_application

app, engine, backend = create_application()
window = engine.rootObjects()[0]
api = backend._umeko_control


def call(operation, arguments=None, caller=None):
    result = api.execute({'operation': operation, 'arguments': arguments or {}}, caller)
    assert result['ok'], result
    return result


try:
    QTest.qWait(180)
    targets = {'backend': backend, 'plugins': backend.providerPlugins, 'management': backend.piManagement, 'about': backend.appAbout}
    for operation, spec in api.operations.items():
        assert callable(getattr(targets[spec['target']], spec['method'], None)), operation
    assert Path(call('help')['entry']).name == 'README.md'
    call('appearance.fontScale', {'scale': 1.25})
    QTest.qWait(100)
    assert backend.fontScale == 1.25
    call('appearance.language', {'language': 'en'})
    assert backend.language == 'en'
    assert not api.execute({'operation': 'appearance.fontScale', 'arguments': {'scale': True}})['ok']
    assert not api.execute({'operation': 'appearance.language', 'arguments': {'language': 'xx'}})['ok']
    assert not api.execute({'operation': '__getattribute__'})['ok']
    assert not api.execute({'operation': 'providers.remove', 'arguments': {'id': 'missing'}})['ok']
    theme = Path(os.environ['UMEKO_DATA_DIR'])/'fixture-theme.json'
    previous_color = window.color()
    theme.write_text(json.dumps({'format': 'umeko-theme', 'version': 1, 'id': 'control', 'name': 'Control', 'base': 'dark', 'colors': {'accent': '#9CAFFF'}}))
    call('themes.import', {'path': str(theme)})
    QTest.qWait(100)
    assert backend.config['theme'] == 'custom:control' and window.color() != previous_color
    assert any(t['id'] == 'custom:control' for t in call('themes.list')['themes'])
    owner = backend._view
    owner.id = 'control-owner'
    backend._sessions.append({'id': owner.id, 'title': 'Owner', 'workspace': owner.workspace, 'file': ''})
    owner.busy = True
    added = call('providers.save', {'name': 'Control API', 'api': 'openai', 'baseUrl': 'https://api.example.com/v1', 'key': 'fixture-only-key',
                                  'models': [{'upstream': 'control-model', 'alias': 'control-model'}]}, owner)
    identifier = added['createdProviderIds'][0]
    assert 'fixture-only-key' not in json.dumps(call('settings.get'))
    assert call('settings.get')['config']['agent']['maxTokens'] > 0
    ticket = call('agent.save', {'config': {'instructions': 'CONTROL_APPLIED_AFTER_IDLE'}}, owner)
    assert ticket['status'] == 'queued'
    assert backend.config['agent']['instructions'] == ''
    model_ticket = call('models.select', {'provider': identifier, 'model': 'control-model'}, owner)
    assert model_ticket['status'] == 'queued'
    backend.newSession()
    viewer = backend._view
    call('sessions.reasoning', {'value': 'high'}, owner)
    assert owner.reasoning_effort == 'high' and viewer.reasoning_effort == 'off'
    owner.busy = False
    for _ in range(50):
        QTest.qWait(50)
        jobs = call('jobs.get')['jobs']
        if all(job['status'] != 'queued' for job in jobs): break
    assert all(job['status'] == 'completed' for job in jobs), jobs
    assert backend.config['agent']['instructions'] == 'CONTROL_APPLIED_AFTER_IDLE'
    assert owner.provider == identifier and owner.model == 'control-model'
    assert backend._view is viewer, 'Queued change switched the visible chat'
    replies = []
    original = backend._pool.write
    backend._pool.write = lambda record, payload: replies.append((record, payload))
    try: backend._handle_pi_event(owner, {'type': 'umeko_request', 'id': 'fixture-request', 'operation': 'appearance.language', 'arguments': {'language': 'zh'}})
    finally: backend._pool.write = original
    assert replies[0][0] is owner and replies[0][1]['result']['ok']
    assert backend.language == 'zh'
    assert call('sessions.list')['sessions'][0]['id'] == owner.id
    call('sessions.delete', {'id': owner.id})
    assert not call('sessions.list')['sessions']
    call('themes.select', {'id': 'light'})
    call('themes.remove', {'id': 'custom:control'})
    assert not backend.customThemes
    print('UMEKO_CONTROL_UI_OK: live providers/theme/settings, deferred jobs, background caller and deletion')
finally:
    backend.close(); window.hide()
    import shiboken6
    shiboken6.delete(engine)
