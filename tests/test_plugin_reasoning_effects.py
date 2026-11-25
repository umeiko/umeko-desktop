"""Plugin policy/effect integration with fake routes; no model or runtime I/O."""
import copy
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.controller_reasoning import ReasoningDiscovery
from app.plugin_sessions import apply_session_policy, session_policy


class PluginReasoningEffectTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix='umeko-plugin-reasoning-')
        self.addCleanup(self.workspace.cleanup)
        self.model = {'upstream': 'plugin-upstream', 'alias': 'plugin-model',
            'reasoningLevels': ['low', 'high'], 'reasoningLevelsAuto': True,
            'reasoningFormat': 'openai-none', 'reasoningFormatAuto': True,
            'reasoningDetection': {'state': 'known', 'evidenceVersion': 1, 'levels': ['low', 'high']},
            'reasoningFormatDetection': {'state': 'known', 'evidenceVersion': 1}}
        self.provider = {'id': 'plugin-provider', 'api': 'openai', 'models': [self.model]}
        self.profile = {'workspace': self.workspace.name, 'model': 'plugin-model',
            'provider': 'plugin-provider', 'tools': ['read'], 'reasoningEffort': 'high'}
        self.record = SimpleNamespace(id='plugin-session', key='plugin-record', file='',
            workspace=self.workspace.name, model='plugin-model', provider='plugin-provider',
            reasoning_effort='high', busy=False, process=None, subagents_active=False)
        data = {'providers': [self.provider], 'agent': {'toolPermissionMode': 'ask'},
            'ui': {'reasoningEffort': 'medium'}, 'selectedProvider': 'desktop-provider',
            'selectedModel': 'desktop-model', 'pluginSessionProfiles': {'fixture': {'tasks': self.profile}},
            'sessionMeta': {'plugin-session': {'pluginSession': {'plugin': 'fixture', 'profile': 'tasks'}}}}
        gateway = SimpleNamespace(provider=Mock(return_value=self.provider),
            models=Mock(return_value=[{'id': 'plugin-model'}]),
            resolve=Mock(return_value=(self.provider, 'plugin-upstream')))
        self.backend = SimpleNamespace(store=SimpleNamespace(data=data, save=Mock()), gateway=gateway,
            _pool=SimpleNamespace(records={self.record.key: self.record}, write=Mock(), retire=Mock()),
            _reconcile_reasoning=Mock(), _write_pi=Mock(),
            reasoningDetectionChanged=Mock(), reasoningChanged=Mock())
        self.discovery = SimpleNamespace(c=self.backend, closed=False, jobs={},
            connection=ReasoningDiscovery.connection)
        self.discovery._plugin_owned = lambda record: ReasoningDiscovery._plugin_owned(self.discovery, record)
        self.discovery.send = lambda record: ReasoningDiscovery.send(self.discovery, record)
        self.discovery.notify = lambda save=False: ReasoningDiscovery.notify(self.discovery, save)

    def completed(self, levels=('low',), aliases=None):
        result = {'levels': {'state': 'known', 'source': 'effect', 'evidenceVersion': 1,
            'levels': list(levels), 'verified': True, 'aliases': aliases or {}},
            'format': {'state': 'known', 'source': 'effect', 'evidenceVersion': 1,
                'format': 'openai-none', 'verified': True, 'offVerified': True,
                'offFormat': 'qwen-switch', 'offSupported': True, 'status': 'on-off-verified'}}
        key = ('probe', 'plugin-provider', 'plugin-upstream')
        self.discovery.jobs[key] = (7, set())
        ReasoningDiscovery._finished(self.discovery, ('probe', copy.deepcopy(self.provider),
            'plugin-upstream', 7, result))

    def test_completed_effect_resolves_profile_alias_and_preserves_hybrid_off_route(self):
        self.profile['reasoningEffort'] = 'vendor-original'
        self.completed(levels=('vendor-representative',), aliases={'vendor-original': 'vendor-representative'})
        self.assertEqual(self.record.reasoning_effort, 'vendor-representative')
        self.assertEqual(self.profile['reasoningEffort'], 'vendor-original')
        self.assertEqual(self.model['reasoningFormat'], 'openai-none')
        self.assertEqual(self.model['reasoningFormatDetection']['offFormat'], 'qwen-switch')
        self.assertTrue(self.model['reasoningFormatDetection']['offVerified'])
        self.backend._reconcile_reasoning.assert_not_called()
        self.assertEqual((self.record.provider, self.record.model), ('plugin-provider', 'plugin-model'))
        self.assertEqual(self.backend.store.data['ui']['reasoningEffort'], 'medium')

    def test_busy_plugin_waits_for_next_input_after_effect_completion(self):
        self.record.busy = True
        self.record.process = object()
        self.completed(levels=('low',))
        self.assertEqual(self.record.reasoning_effort, 'high')
        self.backend._pool.write.assert_not_called()
        self.backend._write_pi.assert_not_called()
        self.backend._reconcile_reasoning.assert_not_called()
        self.record.busy = False
        self.record._plugin_policy = session_policy(self.backend, self.record)
        apply_session_policy(self.backend, self.record)
        self.assertEqual(self.record.reasoning_effort, 'low')
        self.backend._pool.write.assert_called_once_with(self.record,
            {'type': 'reasoning_effort', 'value': 'low'})

    def test_idle_plugin_applies_profile_once_and_explicit_off_stays_off(self):
        self.record.process = object()
        self.record._plugin_policy = session_policy(self.backend, self.record)
        self.profile['reasoningEffort'] = 'off'
        self.discovery.notify()
        self.assertEqual(self.record.reasoning_effort, 'off')
        self.backend._pool.write.assert_called_once_with(self.record,
            {'type': 'reasoning_effort', 'value': 'off'})
        self.backend._write_pi.assert_not_called()
        self.backend._pool.retire.assert_not_called()

    def test_manual_custom_levels_ignore_stale_automatic_aliases(self):
        self.model.update(reasoningLevels=['vendor-manual'], reasoningLevelsAuto=False)
        self.model['reasoningDetection']['aliases'] = {'vendor-manual': 'high'}
        self.profile['reasoningEffort'] = 'vendor-manual'
        self.assertEqual(session_policy(self.backend, self.record)['reasoningEffort'], 'vendor-manual')
        self.model.update(reasoningFormat='template-thinking', reasoningFormatAuto=False)
        self.completed(levels=('low',), aliases={'vendor-manual': 'low'})
        self.assertEqual(self.model['reasoningLevels'], ['vendor-manual'])
        self.assertEqual(self.model['reasoningFormat'], 'template-thinking')
        self.assertEqual(self.record.reasoning_effort, 'vendor-manual')

    def test_inherited_desktop_choice_uses_plugin_route_alias(self):
        self.profile.pop('reasoningEffort')
        self.backend.store.data['ui']['reasoningEffort'] = 'medium'
        self.model['reasoningDetection']['aliases'] = {'medium': 'high'}
        self.assertEqual(session_policy(self.backend, self.record)['reasoningEffort'], 'high')

    def test_ordinary_records_still_use_existing_reconciliation(self):
        ordinary = SimpleNamespace(id='ordinary-session', reasoning_effort='high')
        self.backend._pool.records['ordinary'] = ordinary
        def reconcile(record):
            record.reasoning_effort = 'low'
        self.backend._reconcile_reasoning.side_effect = reconcile
        self.discovery.notify()
        self.backend._reconcile_reasoning.assert_called_once_with(ordinary)
        self.backend._write_pi.assert_called_once_with({'type': 'reasoning_effort', 'value': 'low'}, ordinary)


if __name__ == '__main__':
    unittest.main()
