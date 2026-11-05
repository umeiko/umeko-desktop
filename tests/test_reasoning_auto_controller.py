"""Offline controller discovery lifecycle; no model transport or Node process."""
import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtGui import QGuiApplication

from app.controller import Controller
from app.model_capabilities import normalize_model
from app.provider_models import ModelWindows
from app.storage import Store

ROOT = Path(__file__).resolve().parents[1]


def detected(levels=('low', 'high'), format='chat-template', source='probe'):
    return {'levels': {'state': 'known', 'source': source, 'levels': list(levels), 'verified': True},
            'format': {'state': 'known', 'source': 'probe', 'format': format, 'verified': True}}


class ReasoningAutoControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.calls, self.catalog_calls, self.controllers = [], [], []
        self.result = detected()
        self.catalog = ModelWindows()
        self.started, self.release = threading.Event(), threading.Event()
        self.release.set()
        for target, kwargs in (
            ('app.provider_plugins.BundledProviders.sync', {'return_value': []}),
            ('app.controller.LocalServer', {}),
            ('app.controller.Controller._restart_pi', {'new': lambda self: None}),
            ('app.controller.Controller._write_pi', {'new': lambda self, payload, record=None: None}),
            ('app.controller_reasoning.fetch_model_windows', {'side_effect': self.fetch}),
            ('app.gateway.Gateway.detect_reasoning', {'side_effect': self.probe}),
        ):
            mock = patch(target, **kwargs)
            mock.start()
            self.addCleanup(mock.stop)
        self.env = patch.dict(os.environ, {'UMEKO_DATA_DIR': self.temp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.close_controllers)

    def close_controllers(self):
        self.release.set()
        for controller in self.controllers:
            controller.close()
        self.app.processEvents()

    def fetch(self, provider):
        self.catalog_calls.append(provider['id'])
        return copy.deepcopy(self.catalog)

    def probe(self, alias, provider, advertised_levels=None):
        self.calls.append((alias, provider, copy.deepcopy(advertised_levels), threading.get_ident()))
        self.started.set()
        if not self.release.wait(4):
            raise RuntimeError('fixture release deadline')
        result = copy.deepcopy(self.result)
        if advertised_levels is not None:
            result['levels'] = {'state': 'known', 'source': 'metadata',
                                'levels': list(advertised_levels), 'verified': True}
        return result

    def controller(self, rows=None, selected='model'):
        if rows is not None:
            store = Store()
            store.data['providers'] = [{'id': 'fixture', 'name': 'Fixture', 'api': 'openai',
                'baseUrl': 'https://fixture.invalid/v1', 'key': '',
                'models': [{'upstream': row.get('alias', 'model'), 'alias': row.get('alias', 'model'),
                            **normalize_model(row)} for row in rows]}]
            store.data.update(selectedProvider='fixture', selectedModel=selected)
            store.save()
        controller = Controller(ROOT)
        self.controllers.append(controller)
        return controller

    def until(self, predicate):
        deadline = time.monotonic() + 4
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertTrue(predicate(), 'controller event deadline exceeded')

    def settled(self, controller):
        self.until(lambda: not controller._reasoning_discovery.jobs
                   and controller.reasoningDetectionState not in ('unknown', 'probing'))

    def row(self, controller, alias='model'):
        return controller._reasoning_discovery.model('fixture', alias)

    def test_legacy_manual_order_and_zero_levels_survive_format_discovery(self):
        controller = self.controller([{'reasoningLevels': ['vendor-z', 'minimal', 'vendor-a']},
                                      {'alias': 'off-only', 'reasoningLevels': []}])
        self.settled(controller)
        self.assertEqual(controller.reasoningLevels, ['vendor-z', 'minimal', 'vendor-a'])
        self.assertEqual(controller.reasoningLevelsState, 'manual')
        self.assertEqual(controller.reasoningFormatState, 'known')
        self.assertFalse(self.row(controller)['reasoningLevelsAuto'])
        controller.selectModel('fixture', 'off-only')
        self.settled(controller)
        self.assertEqual(controller.reasoningLevels, [])
        self.assertEqual(controller.reasoningEffort, 'off')

    def test_adding_model_starts_background_detection_without_gating_chat_off(self):
        self.release.clear()
        controller = self.controller()
        self.assertTrue(controller.saveProvider('', 'Fixture', 'openai',
            'https://fixture.invalid/v1', 'synthetic-fixture', 'model'))
        provider = controller.store.data['providers'][-1]['id']
        controller.selectModel(provider, 'model')
        self.until(self.started.is_set)
        self.assertEqual(controller.reasoningLevels, [])
        self.assertEqual(controller.reasoningDetectionState, 'probing')
        self.assertEqual(controller.reasoningEffort, 'off')
        self.assertNotEqual(self.calls[0][3], threading.get_ident())
        with patch.object(controller, '_command_pi', return_value=True) as command:
            self.assertTrue(controller.send('one offline fake chat'))
            self.assertEqual(command.call_count, 1)
        self.release.set()
        self.settled(controller)
        self.assertEqual(controller.reasoningLevels, ['low', 'high'])
        self.assertEqual(controller.reasoningFormat, 'chat-template')

    def test_refresh_updates_levels_and_format_then_cache_survives_restart(self):
        controller = self.controller([{}])
        self.settled(controller)
        self.result = detected(['vendor-a', 'vendor-b'], 'qwen')
        controller.refreshProviderModels('fixture')
        self.settled(controller)
        self.assertEqual(controller.reasoningLevels, ['vendor-a', 'vendor-b'])
        self.assertEqual(controller.reasoningFormat, 'qwen')
        self.assertEqual(len(self.calls), 2)
        controller.close()
        self.controllers.remove(controller)
        restarted = self.controller()
        self.app.processEvents()
        self.assertEqual(restarted.reasoningLevels, ['vendor-a', 'vendor-b'])
        self.assertEqual(restarted.reasoningFormat, 'qwen')
        self.assertEqual(restarted.reasoningDetectionState, 'known')
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(len(self.catalog_calls), 2)

    def test_lazy_selected_model_runs_only_its_unknown_discovery(self):
        controller = self.controller([{'reasoningLevels': ['manual'], 'reasoningFormatAuto': False},
                                      {'alias': 'lazy'}])
        self.app.processEvents()
        self.assertEqual(self.calls, [])
        controller.selectModel('fixture', 'lazy')
        self.settled(controller)
        self.assertEqual([call[0] for call in self.calls], ['lazy'])
        self.assertEqual(self.row(controller)['reasoningLevels'], ['manual'])

    def test_metadata_owns_levels_but_format_is_still_probed(self):
        self.catalog.reasoning['model'] = ['metadata-custom', 'high']
        self.result = detected(['wrong-probe-level'], 'deepseek')
        controller = self.controller([{}])
        self.settled(controller)
        self.assertEqual(self.calls[0][2], ['metadata-custom', 'high'])
        self.assertEqual(controller.reasoningLevels, ['metadata-custom', 'high'])
        self.assertEqual(self.row(controller)['reasoningDetection']['source'], 'metadata')
        self.assertEqual(controller.reasoningFormat, 'deepseek')
        self.assertEqual(controller.reasoningLevelsState, 'known')
        self.assertEqual(controller.reasoningFormatState, 'known')

    def test_manual_settings_win_inflight_and_auto_toggles_reuse_cache(self):
        self.release.clear()
        controller = self.controller([{}])
        self.until(self.started.is_set)
        self.assertTrue(controller.setModelReasoningLevels('fixture', 'model', ['manual-z', 'manual-a'], False))
        self.assertTrue(controller.setModelReasoningFormat('fixture', 'model', 'qwen', False))
        self.release.set()
        self.until(lambda: not controller._reasoning_discovery.jobs)
        self.assertEqual(controller.reasoningLevels, ['manual-z', 'manual-a'])
        self.assertEqual(controller.reasoningFormat, 'qwen')
        self.assertEqual(controller.reasoningDetectionState, 'manual')
        self.assertTrue(controller.setModelReasoningLevels('fixture', 'model', [], True))
        self.assertTrue(controller.setModelReasoningFormat('fixture', 'model', 'openai', True))
        self.assertEqual(controller.reasoningLevels, ['low', 'high'])
        self.assertEqual(controller.reasoningFormat, 'chat-template')
        self.assertEqual(len(self.calls), 1)
        legacy = [{'provider': 'fixture', 'upstream': 'model', 'alias': 'model',
                   'reasoningLevels': ['new-z', 'new-a']}]
        self.assertTrue(controller.saveMappings(json.dumps(legacy)))
        self.assertFalse(self.row(controller)['reasoningLevelsAuto'])
        self.assertEqual(controller.reasoningLevels, ['new-z', 'new-a'])

    def test_rejection_removes_bad_level_reprobes_and_never_replays_chat(self):
        self.result = detected(['low', 'high', 'max'])
        controller = self.controller([{}])
        self.settled(controller)
        controller._view.id = 'fake-chat'
        self.assertTrue(controller.setReasoningEffort('max'))
        with patch.object(controller, '_command_pi', return_value=True) as command:
            self.assertTrue(controller.send('one fake chat'))
            controller._view.busy = True
            controller.gateway.reasoning_rejected('fixture', 'model', 'max', ['low', 'high'])
            self.until(lambda: len(self.calls) == 2 and not controller._reasoning_discovery.jobs)
            self.assertEqual(command.call_count, 1)
        self.assertEqual(controller.reasoningLevels, ['low', 'high'])
        self.assertEqual(controller.reasoningEffort, 'high')
        self.assertEqual(controller.store.data['ui']['reasoningEffort'], 'high')
        self.assertEqual(controller.store.data['sessionMeta']['fake-chat']['reasoningEffort'], 'high')
        saved = Store(Path(self.temp.name))
        self.assertEqual(saved.data['ui']['reasoningEffort'], 'high')
        self.assertIn('max', self.row(controller)['reasoningDetection']['rejected'])

    def test_connection_change_invalidates_only_automatic_dimensions(self):
        known = {'state': 'known', 'source': 'probe', 'verified': True}
        controller = self.controller([
            {'reasoningLevels': ['cached'], 'reasoningLevelsAuto': True,
             'reasoningDetection': {**known, 'levels': ['cached']},
             'reasoningFormat': 'qwen', 'reasoningFormatAuto': False},
            {'alias': 'manual-levels', 'reasoningLevels': ['keep-z', 'keep-a'],
             'reasoningFormat': 'deepseek', 'reasoningFormatAuto': True,
             'reasoningFormatDetection': {**known, 'format': 'deepseek'}},
        ])
        rows = copy.deepcopy(controller.store.data['providers'][0]['models'])
        self.assertTrue(controller.saveProvider('fixture', 'Fixture', 'openai',
            'https://changed.invalid/v1', 'synthetic-fixture', json.dumps(rows)))
        first, second = self.row(controller), self.row(controller, 'manual-levels')
        self.assertNotIn('reasoningLevels', first)
        self.assertIn(first['reasoningDetection']['state'], ('unknown', 'probing'))
        self.assertEqual(first['reasoningFormat'], 'qwen')
        self.assertFalse(first['reasoningFormatAuto'])
        self.assertEqual(second['reasoningLevels'], ['keep-z', 'keep-a'])
        self.assertFalse(second['reasoningLevelsAuto'])
        self.assertEqual(second['reasoningFormatDetection']['state'], 'unknown')
        self.assertEqual(second['reasoningFormat'], 'openai')

    def test_level_and_format_failure_states_are_independent(self):
        self.result = {'levels': {'state': 'known', 'source': 'probe', 'levels': [], 'verified': True},
                       'format': {'state': 'failed', 'error': 'unsupported fixture', 'verified': False}}
        controller = self.controller([{}])
        self.settled(controller)
        self.assertEqual(controller.reasoningLevelsState, 'known')
        self.assertEqual(controller.reasoningFormatState, 'failed')
        self.assertEqual(controller.reasoningDetectionState, 'failed')
        self.assertEqual(controller.reasoningLevels, [])
        self.assertTrue(controller.redetectModelReasoning('fixture', 'model'))
        self.assertFalse(controller.redetectModelReasoning('fixture', 'absent'))
        self.settled(controller)

    def test_off_rejection_invalidates_format_reprobes_without_replay_and_restarts(self):
        self.result['format']['offVerified'] = True
        controller = self.controller([{}])
        self.settled(controller)
        original_levels = list(controller.reasoningLevels)
        self.release.clear()
        self.started.clear()
        self.result = detected(original_levels, 'deepseek')
        self.result['format']['offVerified'] = True
        with patch.object(controller, '_command_pi', return_value=True) as command:
            self.assertTrue(controller.send('one fake chat with off'))
            controller._view.busy = True
            controller.gateway.reasoning_rejected('fixture', 'model', 'off', None)
            self.until(self.started.is_set)
            row = self.row(controller)
            self.assertEqual(row['reasoningFormatDetection']['state'], 'probing')
            self.assertFalse(row['reasoningFormatDetection']['offVerified'])
            self.assertEqual(row['reasoningLevels'], original_levels)
            self.assertNotIn('off', row['reasoningDetection'].get('rejected', []))
            self.assertNotEqual(row['reasoningDetection'].get('source'), 'error')
            self.release.set()
            self.until(lambda: len(self.calls) == 2 and not controller._reasoning_discovery.jobs)
            self.assertEqual(command.call_count, 1)
        self.assertEqual(controller.reasoningFormat, 'deepseek')
        self.assertTrue(self.row(controller)['reasoningFormatDetection']['offVerified'])
        self.assertNotIn('off', self.row(controller)['reasoningDetection'].get('rejected', []))
        controller.close()
        self.controllers.remove(controller)
        restarted = self.controller()
        self.app.processEvents()
        self.assertEqual(restarted.reasoningLevels, original_levels)
        self.assertEqual(restarted.reasoningFormat, 'deepseek')
        self.assertEqual(restarted.reasoningDetectionState, 'known')
        self.assertEqual(len(self.calls), 2)

    def test_current_reasoning_properties_expose_independent_manual_auto_choices(self):
        controller = self.controller([{}])
        self.settled(controller)
        meta = controller.metaObject()
        for name, expected_type in (('reasoningSettings', 'QVariantMap'),
                                    ('reasoningLevelsAuto', 'bool'), ('reasoningFormatAuto', 'bool')):
            self.assertEqual(meta.property(meta.indexOfProperty(name)).typeName(), expected_type)
        self.assertEqual(controller.reasoningSettings, controller.modelReasoningSettings('fixture', 'model'))
        self.assertTrue(controller.reasoningLevelsAuto)
        self.assertTrue(controller.reasoningFormatAuto)
        self.assertTrue(controller.setModelReasoningLevels('fixture', 'model', ['raw-custom'], False))
        self.assertFalse(controller.reasoningLevelsAuto)
        self.assertTrue(controller.reasoningFormatAuto)
        self.assertEqual(controller.reasoningSettings['reasoningLevels'], ['raw-custom'])
        self.assertEqual(controller.reasoningSettings['states'], {'levels': 'manual', 'format': 'known'})
        self.assertTrue(controller.setModelReasoningFormat('fixture', 'model', 'qwen', False))
        self.assertFalse(controller.reasoningFormatAuto)
        self.assertTrue(controller.setModelReasoningLevels('fixture', 'model', [], True))
        self.assertTrue(controller.reasoningLevelsAuto)
        self.assertFalse(controller.reasoningFormatAuto)
        self.assertEqual(controller.reasoningSettings['reasoningFormat'], 'qwen')
        self.assertEqual(controller.reasoningSettings['states'], {'levels': 'known', 'format': 'manual'})
        self.assertTrue(controller.setModelReasoningFormat('fixture', 'model', 'openai', True))
        self.assertTrue(controller.reasoningFormatAuto)
        self.assertEqual(controller.reasoningSettings['reasoningFormat'], 'chat-template')
        self.assertEqual(len(self.calls), 1)

    def test_manual_reasoning_force_refresh_updates_context_and_restarts_only_on_change(self):
        controller = self.controller([{'reasoningLevels': ['manual-z', 'manual-a'],
                                       'reasoningFormat': 'qwen', 'reasoningFormatAuto': False}])
        self.app.processEvents()
        self.catalog['model'] = 64000
        restarts = []
        with patch.object(controller, '_restart_pi', new=lambda: restarts.append(True)):
            controller.refreshProviderModels('fixture')
            self.until(lambda: len(self.catalog_calls) == 1 and not controller._reasoning_discovery.jobs)
            row = self.row(controller)
            self.assertEqual(row['providerContextWindow'], 64000)
            self.assertEqual(row['contextWindow'], 64000)
            self.assertEqual(row['reasoningLevels'], ['manual-z', 'manual-a'])
            self.assertEqual(row['reasoningFormat'], 'qwen')
            self.assertFalse(row['reasoningLevelsAuto'])
            self.assertFalse(row['reasoningFormatAuto'])
            self.assertEqual(self.calls, [])
            self.assertEqual(restarts, [True])
            # An unchanged catalog is a separate refresh outcome: it must not restart Pi.
            controller.refreshProviderModels('fixture')
            self.until(lambda: len(self.catalog_calls) == 2 and not controller._reasoning_discovery.jobs)
            self.assertEqual(restarts, [True])
            self.assertEqual(self.calls, [])

    def test_effort_clamp_reaches_live_session_before_manual_or_rejection_probe_finishes(self):
        controller = self.controller([{}])
        self.settled(controller)
        record = controller._view
        record.id = 'live-fixture'
        writes = []
        record.process = SimpleNamespace(write=lambda raw: writes.append(json.loads(raw)))
        try:
            with patch.object(controller, '_write_pi',
                    new=lambda payload, target=None: controller._pool.write(target or record, payload)), \
                    patch.object(controller, '_command_pi', return_value=True) as command:
                self.assertTrue(controller.setReasoningEffort('high'))
                writes.clear()
                self.assertTrue(controller.setModelReasoningLevels('fixture', 'model', ['low'], False))
                self.assertEqual(writes, [{'type': 'reasoning_effort', 'value': 'low'}])
                self.assertEqual(controller.reasoningEffort, 'low')
                self.assertEqual(Store(Path(self.temp.name)).data['sessionMeta']['live-fixture']['reasoningEffort'], 'low')
                self.assertEqual(len(self.calls), 1)
                self.assertFalse(controller._reasoning_discovery.jobs)

                self.assertTrue(controller.setModelReasoningLevels('fixture', 'model', ['low', 'high'], False))
                self.assertTrue(controller.setReasoningEffort('high'))
                self.assertTrue(controller.send('one live fake prompt'))
                record.busy = True
                writes.clear()
                self.release.clear()
                self.started.clear()
                controller.gateway.reasoning_rejected('fixture', 'model', 'high', ['low'])
                self.until(self.started.is_set)
                self.assertFalse(self.release.is_set())
                self.assertTrue(controller._reasoning_discovery.jobs)
                self.assertEqual(writes, [{'type': 'reasoning_effort', 'value': 'low'}])
                self.assertEqual(controller.reasoningEffort, 'low')
                self.assertEqual(controller.store.data['sessionMeta']['live-fixture']['reasoningEffort'], 'low')
                self.assertEqual(command.call_count, 1)
                self.release.set()
                self.until(lambda: not controller._reasoning_discovery.jobs)
        finally:
            record.process = None
            self.release.set()


if __name__ == '__main__':
    unittest.main()
