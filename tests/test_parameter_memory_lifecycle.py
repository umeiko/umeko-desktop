"""Offline rejection expiry and actual settings-slot invalidation paths."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch

from app.controller import Controller
from app.gateway import Gateway
from app.model_capabilities import normalize_model
from umeko_provider_sdk.compatibility import ParameterMemory, compatible_open

RUN_ROOT = Path('C:/UmekoTests/p124')
TTL = 7 * 86400
BODY = {'model': 'offline-model', 'temperature': .7, 'tool_choice': 'required'}
SCOPE = ('provider-a', 'https://offline.invalid/v1', 'offline-model')


class FakeClock:
    def __init__(self):
        self.value = 2_000_000_000.0

    def __call__(self):
        return self.value


class MemoryLifecycleTests(unittest.TestCase):
    def setUp(self):
        RUN_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=RUN_ROOT, prefix='followup_lifecycle_')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.clock = FakeClock()

    def memory(self, version='fixture-app-a'):
        return ParameterMemory(self.directory, clock=self.clock, app_version=version)

    def test_fresh_rejection_has_age_and_action_without_mutating_input(self):
        memory = self.memory()
        memory.remember(SCOPE, {'temperature', 'tool_choice'})
        self.clock.value += 86400
        original = copy.deepcopy(BODY)
        body, details = memory.apply_with_details(SCOPE, BODY, {'temperature', 'tool_choice'})
        self.assertEqual(BODY, original)
        self.assertNotIn('temperature', body)
        self.assertEqual(body['tool_choice'], 'auto')
        by_name = {row['parameter']: row for row in details}
        self.assertEqual(by_name['temperature']['action'], 'omitted')
        self.assertEqual(by_name['tool_choice']['action'], 'auto')
        self.assertEqual(by_name['temperature']['recordedAt'], self.clock.value - 86400)
        self.assertAlmostEqual(by_name['temperature']['ageDays'], 1)

    def test_ttl_equal_boundary_expires_and_resends(self):
        memory = self.memory()
        memory.remember(SCOPE, {'temperature'})
        self.clock.value += TTL
        body, details = memory.apply_with_details(SCOPE, BODY, {'temperature'})
        self.assertEqual(body, BODY)
        self.assertEqual(details, [])

    def test_default_clock_expires_instead_of_permanently_omitting_parameter(self):
        with patch('time.time', return_value=self.clock.value) as clock:
            memory = ParameterMemory(self.directory)
            memory.remember(SCOPE, {'temperature'})
            clock.return_value += TTL
            self.assertEqual(memory.apply(SCOPE, BODY, {'temperature'}), BODY)

    def test_rejection_remains_fresh_just_before_ttl(self):
        memory = self.memory()
        memory.remember(SCOPE, {'temperature'})
        self.clock.value += TTL - 1
        self.assertNotIn('temperature', memory.apply(SCOPE, BODY, {'temperature'}))

    def test_repeated_rejection_renews_timestamp(self):
        memory = self.memory()
        memory.remember(SCOPE, {'temperature'})
        self.clock.value += TTL - 1
        memory.remember(SCOPE, {'temperature'})
        renewed_at = self.clock.value
        self.clock.value += 2
        body, details = memory.apply_with_details(SCOPE, BODY, {'temperature'})
        self.assertNotIn('temperature', body)
        self.assertEqual(details[0]['recordedAt'], renewed_at)
        self.assertEqual(details[0]['ageDays'], 0)

    def test_same_app_version_preserves_unexpired_persisted_rejection(self):
        self.memory().remember(SCOPE, {'temperature'})
        self.clock.value += 3600
        self.assertNotIn('temperature', self.memory().apply(SCOPE, BODY, {'temperature'}))

    def test_app_version_change_discards_rejection(self):
        self.memory().remember(SCOPE, {'temperature'})
        changed = self.memory('fixture-app-b')
        self.assertEqual(changed.apply(SCOPE, BODY, {'temperature'}), BODY)

    def test_legacy_rejections_without_age_are_discarded(self):
        path = self.directory / 'provider-compatibility.json'
        path.write_text(json.dumps({'version': 1, 'rejections': {
            json.dumps(list(SCOPE)): ['temperature']}}), encoding='utf-8')
        memory = ParameterMemory(self.directory)
        self.assertEqual(memory.apply(SCOPE, BODY, {'temperature'}), BODY)

    def test_explicit_saved_parameters_survive_active_rejection(self):
        memory = self.memory()
        memory.remember(SCOPE, {'temperature', 'tool_choice'})
        self.assertEqual(memory.apply(SCOPE, BODY, ()), BODY)
        body, details = memory.apply_with_details(SCOPE, BODY, ())
        self.assertEqual(body, BODY)
        self.assertEqual(details, [])

    def test_clear_provider_covers_all_endpoints_and_models_keeps_other_provider(self):
        memory = self.memory()
        scopes = [SCOPE, (SCOPE[0], 'https://alternate.invalid/v1', 'other-model'),
                  ('provider-b', SCOPE[1], SCOPE[2])]
        for scope in scopes:
            memory.remember(scope, {'temperature'})
        memory.clear_provider('provider-a')
        for scope in scopes[:2]:
            self.assertEqual(memory.apply(scope, BODY, {'temperature'}), BODY)
        self.assertNotIn('temperature', memory.apply(scopes[2], BODY, {'temperature'}))

    def test_clear_all_discards_every_provider(self):
        memory = self.memory()
        memory.remember(SCOPE, {'temperature'})
        memory.remember(('provider-b', SCOPE[1], SCOPE[2]), {'temperature'})
        memory.clear_all()
        self.assertEqual(memory.apply(SCOPE, BODY, {'temperature'}), BODY)
        self.assertEqual(memory.apply(('provider-b', SCOPE[1], SCOPE[2]), BODY, {'temperature'}), BODY)


class SettingsSlotLifecycleTests(unittest.TestCase):
    """Real Controller slot bodies with UI/process adapters replaced locally."""
    def setUp(self):
        RUN_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=RUN_ROOT, prefix='followup_lifecycle_slots_')
        self.addCleanup(self.temp.cleanup)
        self.requests, self.refreshes, self.refresh_observations = [], [], []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                owner.requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                raw = b'{"ok":true}'
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        base = f'http://127.0.0.1:{self.server.server_port}/v1'
        providers = [{'id': provider, 'name': provider, 'api': 'openai', 'baseUrl': base,
                      'key': 'offline-placeholder', 'proxy': {'mode': 'direct', 'url': ''},
                      'models': [{'upstream': alias, 'alias': alias,
                                  **normalize_model({'reasoningLevels': ['manual-level'],
                                                     'reasoningFormat': 'qwen', 'reasoningFormatAuto': False})}]}
                     for provider, alias in [('provider-a', 'a-model'), ('provider-b', 'b-model')]]
        self.store = SimpleNamespace(directory=Path(self.temp.name), data={
            'providers': providers, 'selectedProvider': 'provider-a', 'selectedModel': 'a-model'},
            save=lambda: None)
        self.gateway = Gateway(self.store, None)
        self.scopes = [('provider-a', base, 'a-model'), ('provider-a', base + '/alternate', 'other-model'),
                       ('provider-b', base, 'b-model')]
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        signal = SimpleNamespace(emit=lambda *args: None)
        discovery = SimpleNamespace(model=self.model, refresh=self.refresh)
        self.controller = SimpleNamespace(store=self.store, gateway=self.gateway,
            _models_busy=lambda *args: False, _provider_plugins=SimpleNamespace(repair_selection=lambda *args: None),
            _restart_pi=lambda: None, changed=signal, toast=signal, _reasoning_discovery=discovery,
            adapter=None)
        self.controller._validate_model_mappings = lambda *args, **kwargs: Controller._validate_model_mappings(
            self.controller, *args, **kwargs)
        self.controller.redetectModelReasoning = lambda provider, alias: Controller.redetectModelReasoning(
            self.controller, provider, alias)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def model(self, provider, alias):
        row = self.gateway.provider(provider)
        return next((m for m in row['models'] if m['alias'] == alias), None) if row else None

    def refresh(self, provider, **kwargs):
        self.refreshes.append((provider, kwargs))
        scope = next(scope for scope in self.scopes if scope[0] == provider)
        self.refresh_observations.append((provider, self.gateway.compatibility.apply(
            scope, {'temperature': .7}, {'temperature'})))
        return True

    def prime(self):
        for scope in self.scopes:
            self.gateway.compatibility.remember(scope, {'temperature'})
        self.post(self.scopes[0])
        self.assertNotIn('temperature', self.requests[-1])

    def post(self, scope):
        request = urllib.request.Request(scope[1] + '/chat/completions',
            data=json.dumps({'model': scope[2], 'temperature': .7}).encode(),
            headers={'Content-Type': 'application/json'})
        with compatible_open(self.opener, request, memory=self.gateway.compatibility,
                             scope=scope, automatic={'temperature'}) as response:
            self.assertTrue(json.load(response)['ok'])

    def assert_provider_reset_and_next_request_resends(self):
        for scope in self.scopes[:2]:
            self.assertEqual(self.gateway.compatibility.apply(scope, {'temperature': .7}, {'temperature'}),
                             {'temperature': .7})
        self.assertNotIn('temperature', self.gateway.compatibility.apply(
            self.scopes[2], {'temperature': .7}, {'temperature'}))
        self.post(self.scopes[0])
        self.assertEqual(self.requests[-1]['temperature'], .7)
        self.assertEqual(self.model('provider-a', self.store.data['selectedModel'])['reasoningLevels'], ['manual-level'])

    def test_save_provider_even_same_connection_clears_only_its_rejections(self):
        self.prime()
        provider = self.gateway.provider('provider-a')
        with patch('app.controller.QTimer.singleShot', side_effect=lambda _, callback: callback()):
            self.assertTrue(Controller.saveProvider(self.controller, provider['id'], provider['name'],
                provider['api'], provider['baseUrl'], '', json.dumps(provider['models'])))
        self.assert_provider_reset_and_next_request_resends()

    def test_save_mappings_clears_changed_provider_and_keeps_unchanged_provider(self):
        self.prime()
        rows = [{'provider': p['id'], **copy.deepcopy(m)} for p in self.store.data['providers'] for m in p['models']]
        rows[0]['upstream'] = 'changed-upstream'
        self.assertTrue(Controller.saveMappings(self.controller, json.dumps(rows)))
        self.assert_provider_reset_and_next_request_resends()

    def test_refresh_provider_models_clears_before_refresh(self):
        self.prime()
        Controller.refreshProviderModels(self.controller, 'provider-a')
        self.assertEqual(self.refreshes[0][0], 'provider-a')
        self.assertEqual(self.refresh_observations[0], ('provider-a', {'temperature': .7}))
        self.assert_provider_reset_and_next_request_resends()

    def test_redetect_model_reasoning_clears_valid_provider(self):
        self.prime()
        self.assertTrue(Controller.redetectModelReasoning(self.controller, 'provider-a', 'a-model'))
        self.assertEqual(self.refreshes, [('provider-a', {'only': 'a-model'})])
        self.assertEqual(self.refresh_observations[0], ('provider-a', {'temperature': .7}))
        self.assert_provider_reset_and_next_request_resends()

    def test_redetect_selected_reasoning_delegates_and_clears_provider(self):
        self.prime()
        self.assertTrue(Controller.redetectReasoning(self.controller))
        self.assert_provider_reset_and_next_request_resends()


if __name__ == '__main__':
    unittest.main()
