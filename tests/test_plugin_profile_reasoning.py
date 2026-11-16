"""Offline profile reasoning validation and application at input boundaries."""
import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from app.gateway import Gateway
from app.pi_sessions import SessionState
from app.plugin_sessions import (apply_session_policy, profile_reasoning_levels,
    profile_rows, session_policy, set_profile_model)


class ProfileReasoningTests(unittest.TestCase):
    def setUp(self):
        base = Path('C:/UmekoTests/issue160/profile-reasoning')
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.profile = {'workspace': self.temp.name, 'model': 'a', 'tools': ['read']}
        self.store = SimpleNamespace(data={
            'agent': {'toolPermissionMode': 'ask'},
            'providers': [{'id': 'provider-a', 'name': 'Fixture', 'api': 'openai', 'models': [
                {'alias': 'a', 'upstream': 'a', 'reasoningLevels': ['low', 'high'], 'reasoningLevelsAuto': False},
                {'alias': 'b', 'upstream': 'b', 'reasoningLevels': ['medium'], 'reasoningLevelsAuto': False},
                {'alias': 'plain', 'upstream': 'plain', 'reasoningLevels': [], 'reasoningLevelsAuto': False},
                {'alias': 'unknown', 'upstream': 'unknown', 'reasoningLevelsAuto': True}]}],
            'pluginSessionProfiles': {'fixture': {'tasks': self.profile}},
            'sessionMeta': {'owned': {'pluginSession': {'plugin': 'fixture', 'profile': 'tasks'}}}},
            save=Mock())
        self.gateway = Gateway.__new__(Gateway)
        self.gateway.store = self.store
        self.backend = SimpleNamespace(store=self.store, gateway=self.gateway,
            _pool=SimpleNamespace(retire=Mock(), write=Mock()))
        self.record = SessionState(id='owned')

    def set_effort(self, value, **kwargs):
        return set_profile_model(self.backend, 'fixture', 'tasks', reasoning_effort=value, **kwargs)

    def test_levels_use_real_model_configuration_and_rows_keep_legacy_absence(self):
        self.assertEqual(profile_reasoning_levels(self.backend, 'a'), ['low', 'high'])
        self.assertEqual(profile_reasoning_levels(self.backend, 'unknown'), [])
        row = profile_rows(self.backend)[0]
        self.assertEqual((row['reasoningEffort'], row['reasoningLevels']), ('', ['low', 'high']))
        self.assertNotIn('reasoningEffort', self.profile)

    def test_explicit_effort_is_strict_and_off_is_always_valid(self):
        original = copy.deepcopy(self.profile)
        for invalid in ('ultra', 'HIGH', ' high ', None, 1, []):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.set_effort(invalid)
            self.assertEqual(self.profile, original)
        self.set_effort('high')
        self.assertEqual(self.profile['reasoningEffort'], 'high')
        result = self.set_effort('off', model='plain')
        self.assertEqual(result['reasoningEffort'], 'off')
        with self.assertRaises(ValueError):
            self.set_effort('high')

    def test_policy_rejects_invalid_persisted_effort_and_unsupported_models(self):
        for model, effort in [('a', ''), ('a', None), ('a', 'ultra'), ('plain', 'low'), ('unknown', 'low')]:
            self.profile.update(model=model, reasoningEffort=effort)
            with self.subTest(model=model, effort=effort), self.assertRaises(ValueError):
                session_policy(self.backend, self.record)
        self.profile['reasoningEffort'] = 'off'
        self.assertEqual(session_policy(self.backend, self.record)['reasoningEffort'], 'off')

    def test_only_effort_changes_and_empty_values_preserve_fields(self):
        self.profile['provider'] = 'provider-a'
        original = copy.deepcopy(self.profile)
        self.set_effort('high')
        self.assertEqual(self.profile, {**original, 'reasoningEffort': 'high'})
        self.set_effort('', model='', provider='')
        self.assertEqual(self.profile, {**original, 'reasoningEffort': 'high'})

    def test_model_change_reconciles_old_effort_but_rejects_invalid_explicit_effort(self):
        self.profile['reasoningEffort'] = 'high'
        self.set_effort('', model='b')
        self.assertEqual(self.profile['reasoningEffort'], 'medium')
        previous = copy.deepcopy(self.profile)
        with self.assertRaises(ValueError):
            self.set_effort('high', model='plain')
        self.assertEqual(self.profile, previous)
        self.set_effort('', model='plain')
        self.assertEqual(self.profile['reasoningEffort'], 'off')

    def test_save_failure_rolls_back_model_provider_and_effort_including_absence(self):
        for old_fields in ({}, {'provider': 'provider-a', 'reasoningEffort': 'high'}):
            with self.subTest(old_fields=old_fields):
                self.profile.pop('provider', None)
                self.profile.pop('reasoningEffort', None)
                self.profile.update(model='a', **old_fields)
                original = copy.deepcopy(self.profile)
                self.store.save.side_effect = [None, OSError('fixture save failed')]
                with self.assertRaises(OSError):
                    self.set_effort('medium', model='b')
                self.assertEqual(self.profile, original)
        self.store.save.side_effect = None

    def test_save_failure_preserves_missing_model_field(self):
        self.profile.pop('model')
        original = copy.deepcopy(self.profile)
        self.store.save.side_effect = [None, RuntimeError('fixture save failed')]
        with self.assertRaises(RuntimeError):
            self.set_effort('low', model='a')
        self.assertEqual(self.profile, original)

    def test_new_session_applies_explicit_effort_and_absent_field_keeps_old_behavior(self):
        self.record.reasoning_effort = 'low'
        policy = apply_session_policy(self.backend, self.record)
        self.assertNotIn('reasoningEffort', policy)
        self.assertEqual(self.record.reasoning_effort, 'low')
        self.backend._pool.write.assert_not_called()
        self.profile['reasoningEffort'] = 'high'
        apply_session_policy(self.backend, self.record)
        self.assertEqual(self.record.reasoning_effort, 'high')
        self.backend._pool.write.assert_called_once_with(self.record, {'type': 'reasoning_effort', 'value': 'high'})

    def test_idle_effort_change_writes_without_retiring_process(self):
        self.profile['reasoningEffort'] = 'low'
        apply_session_policy(self.backend, self.record)
        self.backend._pool.write.reset_mock()
        self.record.process = object()
        self.profile['reasoningEffort'] = 'off'
        apply_session_policy(self.backend, self.record)
        self.backend._pool.retire.assert_not_called()
        self.backend._pool.write.assert_called_once_with(self.record, {'type': 'reasoning_effort', 'value': 'off'})

    def test_busy_session_keeps_effort_until_next_input_and_route_changes_retire(self):
        self.profile['reasoningEffort'] = 'low'
        apply_session_policy(self.backend, self.record)
        self.backend._pool.write.reset_mock()
        self.record.process = object()
        self.record.busy = True
        self.profile['reasoningEffort'] = 'high'
        apply_session_policy(self.backend, self.record)
        self.assertEqual(self.record.reasoning_effort, 'low')
        self.assertEqual(self.record._plugin_policy['reasoningEffort'], 'low')
        self.backend._pool.write.assert_not_called()
        self.backend._pool.retire.assert_not_called()
        self.record.busy = False
        apply_session_policy(self.backend, self.record)
        self.assertEqual(self.record.reasoning_effort, 'high')
        self.backend._pool.retire.assert_not_called()
        self.set_effort('', model='b')
        apply_session_policy(self.backend, self.record)
        self.backend._pool.retire.assert_called_once_with(self.record)
        self.assertEqual((self.record.model, self.record.reasoning_effort), ('b', 'medium'))


if __name__ == '__main__':
    unittest.main()
