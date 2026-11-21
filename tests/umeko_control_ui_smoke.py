"""Exercise live desktop mutations, queued changes and caller ownership."""
import json
import os
import sys
import tempfile
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch
import copy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
profile = Path(tempfile.mkdtemp(prefix='umeko-control-ui-'))
os.environ['UMEKO_DATA_DIR'] = str(profile / 'data')
os.environ['PI_CODING_AGENT_DIR'] = str(profile / 'agent')
os.environ['HOME'] = str(profile)
os.environ['XDG_CONFIG_HOME'] = str(profile / 'config')
os.environ['XDG_DATA_HOME'] = str(profile / 'xdg-data')
os.environ['UMEKO_LANGUAGE'] = 'zh'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtTest import QTest
from main import create_application

# Synthetic secrets never enter the OS credential store. No provider discovery.
fixtures = ExitStack()
fixtures.enter_context(patch('app.storage.protect', side_effect=lambda value, *a, **kw: value))
app, engine, backend = create_application()
fixtures.enter_context(patch.object(backend._reasoning_discovery, 'refresh', new=lambda *a, **kw: False))
# Capture native messages without starting a model or issuing provider requests.
native_writes = []
fixtures.enter_context(patch.object(backend._pool, 'write', side_effect=lambda record, payload: native_writes.append((record, payload))))
window = engine.rootObjects()[0]
api = backend._umeko_control


def call(operation, arguments=None, caller=None):
    result = api.execute({'operation': operation, 'arguments': arguments or {}}, caller)
    assert result['ok'], result
    return result


try:
    QTest.qWait(180)
    targets = {'backend': backend, 'plugins': backend.providerPlugins,
               'management': backend.piManagement, 'about': backend.appAbout,
               'dsh': backend.dshRuntime, 'startup': backend.loginStartup,
               'documents': backend.documentPreview}
    for operation, spec in api.operations.items():
        if spec['target'] in ('widgets', 'global-agents'):
            # These families dispatch through hosts, not a method per manifest row.
            host = (backend.desktopPlugins.bridge if spec['target'] == 'widgets'
                    else backend.desktopPlugins.global_agents)
            arguments = {field[0]: copy.deepcopy(field[2]) if len(field) > 2 else
                         {'string': 'fixture', 'boolean': False, 'integer': 1,
                          'json': {}}[field[1]] for field in spec['args']}
            with patch.object(host, 'execute', return_value={'fixture': operation}) as dispatch:
                assert call(operation, arguments, backend._view)['fixture'] == operation
                expected = (operation, arguments, backend._view)
                if spec['target'] == 'widgets': expected += (api,)
                dispatch.assert_called_once_with(*expected)
        else:
            assert spec['target'] in targets, (operation, spec)
            assert callable(getattr(targets[spec['target']], spec['method'], None)), operation
    # The native installation guard must reject before any installer is called.
    with patch.object(backend.piManagement, 'installPackage') as install:
        assert not api.execute({'operation': 'extensions.install',
                                'arguments': {'source': 'fixture'}})['ok']
        install.assert_not_called()
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
    added = call('providers.save', {'name': 'Control API', 'api': 'openai', 'baseUrl': 'http://127.0.0.1:1/v1', 'key': 'fixture-only-key',
                                  'models': [{'upstream': 'control-model', 'alias': 'control-model', 'reasoningLevels': ['high'],
                                              'reasoningLevelsAuto': False, 'reasoningFormat': 'openai',
                                              'reasoningFormatAuto': False}]}, owner)
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
    assert viewer is not owner
    viewer_effort = viewer.reasoning_effort
    owner_effort = owner.reasoning_effort
    reasoning_ticket = call('sessions.reasoning', {'value': 'high'}, owner)
    assert reasoning_ticket['status'] == 'queued'
    assert owner.reasoning_effort == owner_effort and viewer.reasoning_effort == viewer_effort
    owner.busy = False
    for _ in range(50):
        QTest.qWait(50)
        jobs = call('jobs.get')['jobs']
        if all(job['status'] in ('done', 'failed') for job in jobs): break
    assert {job['id'] for job in jobs} == {t['jobId'] for t in (ticket, model_ticket, reasoning_ticket)}
    assert all(job['status'] == 'done' and job['result']['ok'] for job in jobs), jobs
    assert owner.reasoning_effort == 'high' and viewer.reasoning_effort == viewer_effort
    assert any(record is owner and payload == {'type': 'reasoning_effort', 'value': 'high'}
               for record, payload in native_writes)
    assert backend.config['agent']['instructions'] == 'CONTROL_APPLIED_AFTER_IDLE'
    assert owner.provider == identifier and owner.model == 'control-model'
    assert backend._view is viewer, 'Queued change switched the visible chat'
    # A queued validation failure must terminate, not mutate another caller.
    owner.busy = True
    failed_ticket = call('sessions.reasoning', {'value': 'fixture-invalid'}, owner)
    assert failed_ticket['status'] == 'queued'
    owner.busy = False
    for _ in range(50):
        QTest.qWait(50)
        failed = call('jobs.get', {'id': failed_ticket['jobId']})['jobs'][0]
        if failed['status'] in ('done', 'failed'): break
    assert failed['status'] == 'failed' and not failed['result']['ok'], failed
    assert owner.reasoning_effort == 'high' and viewer.reasoning_effort == viewer_effort
    assert backend._view is viewer
    replies = []
    original = backend._pool.write
    backend._pool.write = lambda record, payload: replies.append((record, payload))
    try: backend._handle_pi_event(owner, {'type': 'umeko_request', 'id': 'fixture-request', 'operation': 'appearance.language', 'arguments': {'language': 'zh'}})
    finally: backend._pool.write = original
    assert replies[0][0] is owner and replies[0][1]['result']['ok']
    assert backend.language == 'zh'
    assert call('sessions.list')['sessions'][0]['id'] == owner.id
    # Assert deletion routing only; do not delete files or retire real sessions.
    with patch.object(backend, 'deleteSession') as delete:
        call('sessions.delete', {'id': owner.id})
        delete.assert_called_once_with(owner.id)
    assert call('sessions.list')['sessions'][0]['id'] == owner.id
    call('themes.select', {'id': 'light'})
    call('themes.remove', {'id': 'custom:control'})
    assert not backend.customThemes
    print('UMEKO_CONTROL_UI_OK: live providers/theme/settings, deferred jobs, background caller and deletion routing')
finally:
    backend.close(); window.hide()
    import shiboken6
    shiboken6.delete(engine)
    fixtures.close()
