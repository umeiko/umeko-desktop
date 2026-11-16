"""Python settings operations through the real dispatcher, without model calls."""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')

from PySide6.QtCore import QCoreApplication, QObject
from app.controller import Controller
from app.pi_sessions import SessionState


class FakeStartup(QObject):
    """Keep startup writes wholly inside this fixture."""
    def __init__(self):
        super().__init__()
        self.state = {'available': True, 'umeko': False, 'proxy': False}
        self.calls = []

    def setEnabled(self, umeko, proxy):
        self.calls.append((umeko, proxy))
        self.state.update(umeko=umeko, proxy=proxy)


class SettingsOperationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        base = Path(tempfile.gettempdir()) / 'umeko-settings-operations'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        profile, workspace, agent = (self.base / name for name in ('profile', 'workspace', 'agent'))
        for folder in (profile, workspace, agent):
            folder.mkdir()
        (profile / 'settings.json').write_text(json.dumps({
            'workspace': str(workspace), 'server': {'keys': []},
            'agent': {'agentDir': str(agent), 'outputLimitDefaultVersion': 1},
            'ui': {'language': 'en', 'lineSpacing': 'standard'}}), encoding='utf-8')
        self.startup = FakeStartup()
        self.patches = [
            patch.dict(os.environ, {'UMEKO_DATA_DIR': str(profile)}),
            patch('app.controller.Controller.loadNativeIndex', lambda self: None),
            patch('app.provider_plugins.BundledProviders.sync', return_value=[]),
            patch('app.login_session.LoginStartupSettings', return_value=self.startup),
            patch('app.controller.ReasoningDiscovery.sync_active'),
            patch('app.controller.ReasoningDiscovery.refresh'),
        ]
        for item in self.patches:
            item.start()
        self.addCleanup(self.stop_patches)
        self.b = Controller(ROOT)
        self.addCleanup(self.close_controller)
        self.b.store.data.update(providers=[{'id': 'test-provider', 'name': 'Test provider',
            'api': 'openai', 'baseUrl': 'http://127.0.0.1:1/v1', 'key': 'offline-fixture',
            'models': [{'upstream': 'test-model', 'alias': 'test-model',
                        'reasoningLevels': ['low', 'high'], 'reasoningLevelsAuto': False}]}],
            selectedProvider='test-provider', selectedModel='test-model')
        self.b._view.provider, self.b._view.model = 'test-provider', 'test-model'
        self.b._pool.records[self.b._view.key] = self.b._view
        self.control = self.b._umeko_control
        self.write = self.patch_object(self.b._pool, 'write')
        self.restart = self.patch_object(self.b, '_restart_pi')
        self.patch_object(self.b, '_command_pi', side_effect=AssertionError('No runtime launch allowed'))
        self.patch_object(self.b._dsh_runtime, '_start', side_effect=AssertionError('No dsh launch allowed'))

    def patch_object(self, target, name, **kwargs):
        item = patch.object(target, name, **kwargs)
        result = item.start()
        self.patches.append(item)
        return result

    def stop_patches(self):
        for item in reversed(self.patches):
            item.stop()

    def close_controller(self):
        self.control.timer.stop()
        for record in self.b._pool.records.values():
            record.process = None
            record.busy = False
        self.b.store.data['providers'] = []
        self.b.close()
        self.app.processEvents()

    def execute(self, operation, arguments=None, **kwargs):
        return self.control.execute({'operation': operation, 'arguments': arguments or {}}, **kwargs)

    def applied(self, operation, arguments=None, **kwargs):
        result = self.execute(operation, arguments, **kwargs)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['status'], 'applied', result)
        return result

    def rejected(self, operation, arguments):
        result = self.execute(operation, arguments)
        self.assertFalse(result['ok'], (operation, arguments, result))
        return result

    def persisted(self):
        return json.loads((self.b.store.directory / 'settings.json').read_text(encoding='utf-8'))

    def other_record(self, identifier='other-session'):
        record = SessionState(id=identifier, workspace=self.b._view.workspace,
            model='test-model', provider='test-provider')
        self.b._pool.records[record.key] = record
        return record

    def test_default_reasoning_persists_and_only_new_desktop_sessions_inherit(self):
        current = self.b._view
        current.reasoning_effort = 'low'
        self.applied('agent.defaultReasoning', {'value': 'high'})
        self.assertEqual(self.persisted()['ui']['reasoningEffort'], 'high')
        self.assertEqual(current.reasoning_effort, 'low')
        self.assertEqual(self.b._new_view().reasoning_effort, 'high')
        self.applied('agent.defaultReasoning', {'value': 'off'})
        self.assertEqual(self.b._new_view().reasoning_effort, 'off')
        self.assertEqual(current.reasoning_effort, 'low')
        self.write.assert_not_called()
        for value in ('ultra', None, True, 1):
            with self.subTest(value=value):
                self.rejected('agent.defaultReasoning', {'value': value})
        self.b.store.data['providers'][0]['models'][0]['reasoningLevels'] = []
        self.rejected('agent.defaultReasoning', {'value': 'high'})
        self.applied('agent.defaultReasoning', {'value': 'off'})

    def test_default_reasoning_save_failure_restores_previous_ui(self):
        previous = copy.deepcopy(self.b.store.data['ui'])
        with patch.object(self.b.store, 'save', side_effect=OSError('fixture save failed')):
            self.rejected('agent.defaultReasoning', {'value': 'high'})
        self.assertEqual(self.b.store.data['ui'], previous)

    def test_plugin_model_omitted_provider_uses_new_models_route(self):
        self.b.store.data['providers'].append({'id': 'other-provider', 'name': 'Test provider',
            'api': 'openai', 'baseUrl': 'http://127.0.0.1:1/v1', 'key': 'offline-fixture',
            'models': [{'upstream': 'other-model', 'alias': 'other-model',
                        'reasoningLevels': [], 'reasoningLevelsAuto': False}]})
        self.b.store.data['pluginSessionProfiles'] = {'sample': {'tasks': {
            'model': 'test-model', 'provider': 'test-provider', 'reasoningEffort': 'high'}}}
        self.applied('pluginSessions.setModel', {'plugin': 'sample', 'profile': 'tasks', 'model': 'other-model'})
        profile = self.b.store.data['pluginSessionProfiles']['sample']['tasks']
        self.assertEqual((profile['model'], profile['provider'], profile['reasoningEffort']),
                         ('other-model', 'other-provider', 'off'))

    def test_models_and_reasoning_are_registered_and_validate_before_mutation(self):
        listed = self.execute('operations.list')['operations']
        for operation in ('models.select', 'sessions.reasoning'):
            self.assertIn(operation, listed)
        invalid = [
            ('models.select', {'provider': 'test-provider', 'model': 1}),
            ('models.select', {'provider': False, 'model': 'test-model'}),
            ('models.select', {'provider': 'test-provider', 'model': 'test-model', 'sessionId': []}),
            ('models.select', {'provider': 'test-provider', 'model': 'test-model', 'extra': 1}),
            ('models.select', {'provider': 'test-provider', 'model': 'missing'}),
            ('sessions.reasoning', {'value': True}),
            ('sessions.reasoning', {'value': 'high', 'sessionId': 1}),
            ('sessions.reasoning', {'value': 'high', 'extra': 1}),
            ('sessions.reasoning', {'value': 'ultra'}),
        ]
        for operation, arguments in invalid:
            with self.subTest(operation=operation, arguments=arguments):
                self.rejected(operation, arguments)
        self.assertEqual((self.b._view.provider, self.b._view.model), ('test-provider', 'test-model'))
        self.assertEqual(self.b._view.reasoning_effort, 'off')
        self.write.assert_not_called()

    def test_current_explicit_and_caller_targets_are_respected(self):
        current, other = self.b._view, self.other_record()
        current.context_usage = {'used': 10}
        self.applied('models.select', {'provider': 'test-provider', 'model': 'test-model'})
        self.assertEqual(current.context_usage, {})
        self.applied('sessions.reasoning', {'value': 'high'})
        self.assertEqual(current.reasoning_effort, 'high')
        self.applied('sessions.reasoning', {'value': 'low', 'sessionId': other.id})
        self.assertEqual(other.reasoning_effort, 'low')
        self.assertEqual(current.reasoning_effort, 'high')
        self.applied('sessions.reasoning', {'value': 'off'}, caller=other)
        self.assertEqual(other.reasoning_effort, 'off')
        self.assertEqual(self.b.store.data['ui']['reasoningEffort'], 'high')
        self.write.assert_any_call(other, {'type': 'reasoning_effort', 'value': 'low'})
        self.rejected('sessions.reasoning', {'value': 'high', 'sessionId': 'missing'})

    def test_busy_model_and_effort_jobs_wait_then_apply_to_original_target(self):
        for operation, arguments in (
                ('models.select', {'provider': 'test-provider', 'model': 'test-model'}),
                ('sessions.reasoning', {'value': 'high'})):
            with self.subTest(operation=operation):
                target = self.other_record('busy-' + operation)
                target.busy = True
                result = self.execute(operation, {**arguments, 'sessionId': target.id})
                self.assertTrue(result['ok'], result)
                self.assertEqual(result['status'], 'queued')
                self.control.timer.stop()
                self.control._drain()
                self.assertEqual(self.control.jobs[result['jobId']]['status'], 'queued')
                target.busy = False
                self.control._drain()
                job = self.control.jobs[result['jobId']]
                self.assertEqual(job['status'], 'done', job)
                self.assertEqual(self.b._view.reasoning_effort, 'off')
                if operation == 'sessions.reasoning':
                    self.assertEqual(target.reasoning_effort, 'high')

    def test_line_spacing_and_session_cache_normal_and_invalid_values(self):
        self.applied('appearance.lineSpacing', {'spacing': 'relaxed'})
        self.assertEqual(self.b.lineSpacing, 'relaxed')
        self.b._appearance_save.stop()
        self.b._appearance_save.timeout.emit()
        self.assertEqual(self.persisted()['ui']['lineSpacing'], 'relaxed')
        for value in ('unknown', 1, None):
            self.rejected('appearance.lineSpacing', {'spacing': value})
        for value in (3, 0):
            self.applied('sessions.cache', {'size': value})
            self.assertEqual((self.b.store.data['ui']['sessionCacheSize'], self.b._pool.limit), (value, value))
        for value in (-1, 2147483648, True, 1.5, '3'):
            self.rejected('sessions.cache', {'size': value})

    def test_request_headers_validate_rows_and_persist_without_network(self):
        row = {'id': 'fixture-header', 'name': 'X-Fixture', 'value': 'offline', 'enabled': True}
        self.applied('network.requestHeaders', {'headers': [row]})
        self.assertIn(row, self.persisted()['requestHeaders'])
        for value in ({}, [dict(row, enabled='yes')], [dict(row, name='Host')],
                      [dict(row, value='bad\nheader')], [dict(row, name='')]):
            with self.subTest(value=value):
                self.rejected('network.requestHeaders', {'headers': value})

    def test_dsh_path_own_config_and_busy_queue_without_runtime(self):
        path = str(self.base / 'fake-dsh.exe')
        self.applied('dsh.path', {'path': path})
        self.assertEqual(self.b.dshRuntime.path, path)
        self.applied('dsh.useOwnConfig', {'enabled': True})
        saved = self.persisted()['dsh']
        self.assertEqual((saved['dshPath'], saved['useOwnConfig']), (path, True))
        self.rejected('dsh.path', {'path': 1})
        self.rejected('dsh.useOwnConfig', {'enabled': 'true'})
        self.b._dsh_runtime._busy = True
        queued = self.execute('dsh.useOwnConfig', {'enabled': False})
        self.control.timer.stop()
        self.assertEqual(queued['status'], 'queued')
        self.control._drain()
        self.assertTrue(self.b.dshRuntime.useOwnConfig)
        self.b._dsh_runtime._busy = False
        self.control._drain()
        self.assertEqual(self.control.jobs[queued['jobId']]['status'], 'done')
        self.assertFalse(self.b.dshRuntime.useOwnConfig)

    def test_startup_uses_fake_manager_and_rejects_types_or_unavailable(self):
        result = self.applied('desktop.startup', {'umeko': True, 'proxy': False})
        self.assertEqual(self.startup.calls, [(True, False)])
        self.assertEqual(result['result']['umeko'], True)
        self.rejected('desktop.startup', {'umeko': 1, 'proxy': False})
        self.rejected('desktop.startup', {'umeko': True, 'proxy': 'false'})
        self.startup.state.update(available=False, reason='fixture unavailable')
        self.rejected('desktop.startup', {'umeko': False, 'proxy': False})
        self.assertEqual(self.startup.calls, [(True, False)])

    def test_backend_choice_only_changes_empty_idle_session(self):
        self.applied('sessions.backend', {'value': 'dsh'})
        self.assertEqual(self.b.sessionBackend, 'dsh')
        self.applied('sessions.backend', {'value': 'pi'})
        for value in ('invalid', 1, None):
            self.rejected('sessions.backend', {'value': value})
        self.b._view.messages = [{'role': 'user', 'text': 'existing'}]
        self.rejected('sessions.backend', {'value': 'dsh'})

    def test_dsh_model_choice_sends_fake_pool_configuration(self):
        record = self.b._view
        record.backend, record.dsh_own_config, record.ready = 'dsh', True, True
        record.dsh_options = [{'id': 'model', 'category': 'model', 'currentValue': 'old',
            'options': [{'name': 'Test provider', 'options': [{'name': 'test-model', 'value': 'test-model'}]}]}]
        self.applied('sessions.dshModel', {'value': 'test-model'})
        self.write.assert_called_once_with(record, {'type': 'set_config', 'configId': 'model', 'value': 'test-model'})
        self.rejected('sessions.dshModel', {'value': 'missing'})
        self.rejected('sessions.dshModel', {'value': False})
        record.ready = False
        self.rejected('sessions.dshModel', {'value': 'test-model'})

    def test_document_preview_modes_persist_and_reject_type_or_range(self):
        self.applied('documents.previewMode', {'fileType': 'markdown', 'mode': 'source'})
        self.applied('documents.previewMode', {'fileType': 'html', 'mode': 'rendered'})
        modes = self.persisted()['ui']['documentPreviewModes']
        self.assertEqual((modes['markdown'], modes['html']), ('source', 'rendered'))
        for arguments in ({'fileType': 'pdf', 'mode': 'source'}, {'fileType': 'html', 'mode': 'bad'},
                          {'fileType': 1, 'mode': 'source'}, {'fileType': 'html', 'mode': False}):
            self.rejected('documents.previewMode', arguments)

    def test_agent_partial_settings_preserve_existing_values_and_permission_boundary(self):
        agent = self.b.store.data['agent']
        previous = copy.deepcopy(agent)
        self.applied('agent.save', {'config': {'maxContextImages': 5}})
        self.assertEqual(agent['maxContextImages'], 5)
        self.assertEqual(agent['autoCompaction'], previous['autoCompaction'])
        self.applied('agent.save', {'config': {'autoCompaction': not previous['autoCompaction']}})
        self.assertEqual(agent['maxContextImages'], 5)
        self.assertEqual(agent['autoCompaction'], not previous['autoCompaction'])
        self.rejected('agent.save', {'config': {'toolPermissionMode': 'ask'}})
        self.assertEqual(agent['toolPermissionMode'], previous['toolPermissionMode'])
        self.write.assert_not_called()
        persisted = self.persisted()['agent']
        self.assertEqual((persisted['maxContextImages'], persisted['toolPermissionMode']), (5, previous['toolPermissionMode']))
        for config in ({'maxContextImages': 0}, {'maxContextImages': True}, {'maxContextImages': '3'},
                       {'toolPermissionMode': 'invalid'}, {'toolPermissionMode': 1},
                       {'autoCompaction': 'yes'}, {'unknown': True}):
            self.rejected('agent.save', {'config': config})

    def test_agent_save_failure_rolls_back_and_does_not_broadcast_or_restart(self):
        previous = copy.deepcopy(self.b.store.data['agent'])
        with patch.object(self.b.store, 'save', side_effect=OSError('fixture save failed')):
            self.rejected('agent.save', {'config': {'maxContextImages': 7}})
        self.assertEqual(self.b.store.data['agent'], previous)
        self.write.assert_not_called()
        self.restart.assert_not_called()


if __name__ == '__main__':
    unittest.main()
