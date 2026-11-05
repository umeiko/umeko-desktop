"""Plugin-owned native sessions; isolated profiles and deterministic Pi events."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')

from PySide6.QtCore import QCoreApplication, QTimer
from app.controller import Controller


def pump_until(app, predicate, label, seconds=12):
    """Deadline is a hang guard; assertions depend on events, never elapsed time."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        value = predicate()
        if value:
            return value
        time.sleep(.005)
    raise AssertionError(label)


def isolated_settings(base):
    profile, workspace, agent = (base / name for name in ('profile', 'workspace', 'agent'))
    for folder in (profile, workspace, agent):
        folder.mkdir(parents=True, exist_ok=True)
    (profile / 'settings.json').write_text(json.dumps({
        'agent': {'agentDir': str(agent), 'outputLimitDefaultVersion': 1},
        'server': {'keys': []}, 'workspace': str(workspace),
        'ui': {'language': 'en', 'lineSpacing': 'standard'},
    }), encoding='utf-8')
    return profile, workspace


def controller():
    # The fixture owns every session; native discovery must not inspect ~/.pi.
    with patch('app.controller.Controller.loadNativeIndex', lambda self: None), \
            patch('app.provider_plugins.BundledProviders.sync', return_value=[]):
        return Controller(ROOT)


class PluginSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='umeko-plugin-sessions-')
        self.base = Path(self.temp.name).resolve()
        profile, self.workspace = isolated_settings(self.base)
        self.environment = patch.dict(os.environ, {'UMEKO_DATA_DIR': str(profile)})
        self.environment.start()
        self.b = controller()
        self.addCleanup(self.cleanup)
        self.b.store.data.update(providers=[{'id': 'test-provider', 'name': 'Test provider',
            'api': 'openai', 'baseUrl': 'http://127.0.0.1:1/v1', 'key': 'offline-fixture',
            'models': [{'upstream': 'test-model', 'alias': 'test-model'}]}],
            selectedProvider='test-provider', selectedModel='test-model')
        self.m = self.b.desktopPlugins
        self.answers, self.frames, self.commands = {}, [], []
        self.m.hostResponse.connect(lambda owner, key, value: self.answers.__setitem__((owner, key), value))
        original_send = self.m.send

        def send(owner, frame):
            if owner.startswith('fixture-'):
                self.frames.append((owner, frame))
            else:
                original_send(owner, frame)

        self.send_patch = patch.object(self.m, 'send', side_effect=send)
        self.send_patch.start()
        self.command_patch = patch.object(self.b, '_command_pi', side_effect=self.command)
        self.command_patch.start()
        self.install_owner('fixture-channel')
        self.install_owner('fixture-other')
        self.selected = self.b._view

    def cleanup(self):
        self.command_patch.stop()
        self.send_patch.stop()
        self.b.store.data['providers'] = []
        self.b.close()
        self.app.processEvents()
        self.environment.stop()
        self.temp.cleanup()

    def install_owner(self, owner, *, lifecycle='application', permissions=None):
        self.m.entries[owner] = {'id': owner, 'name': owner, 'version': '1.0.0',
            'lifecycle': lifecycle, 'permissions': permissions if permissions is not None else ['sessions.manage']}
        self.m.settings.setdefault('enabled', {})[owner] = True
        self.m.workers[owner] = {'service': SimpleNamespace(stop=lambda: None), 'ready': True,
            'pending': set(), 'token': self.m.application_token}
        self.b.store.data.setdefault('pluginSessionProfiles', {})[owner] = {'tasks': {
            'workspace': str(self.workspace), 'model': 'test-model', 'provider': 'test-provider',
            'tools': ['read'], 'permissionMode': 'ask', 'allowApprovals': True}}

    def request(self, operation, arguments=None, *, owner='fixture-channel', wait=True):
        key = uuid.uuid4().hex
        accepted = self.m._host_services.request_for(owner, {'id': key, 'operation': operation,
            'arguments': arguments or {}, 'session': dict(self.m._session)})
        self.assertEqual(accepted, key)
        if not wait:
            return owner, key
        return pump_until(self.app, lambda: self.answers.get((owner, key)), operation + ' did not reply')

    def result(self, operation, arguments=None, **kwargs):
        value = self.request(operation, arguments, **kwargs)
        self.assertTrue(value.get('ok'), value)
        return value['result']

    def acquire(self, key='channel-one', **kwargs):
        return self.result('sessions.acquire', {'namespace': 'default', 'externalKey': key,
            'createIfMissing': True, 'profile': 'tasks'}, **kwargs)

    def command(self, action, record=None, **payload):
        record.action, record.busy = action, True
        if action == 'plugin-session-acquire':
            previous = record.id
            record.id = uuid.uuid4().hex
            record.file = str(self.base / (record.id + '.jsonl'))
            Path(record.file).write_text(json.dumps({'type': 'session', 'version': 3,
                'id': record.id, 'timestamp': '2026-01-01T00:00:00Z',
                'cwd': record.workspace}) + '\n', encoding='utf-8')
            self.b.store.data['sessionMeta'][record.id] = self.b.store.data['sessionMeta'].pop(previous)
            QTimer.singleShot(0, lambda: self.emit(record, {'type': 'done'}))
            return True
        self.commands.append((action, record, payload))
        if action == 'prompt':
            record.messages.append({'role': 'user', 'text': payload.get('text', '')})
        return True

    def emit(self, record, event):
        self.b._pool.event.emit(record, event)
        self.app.processEvents()

    def finish(self, record, text):
        self.emit(record, {'type': 'assistant_start'})
        self.emit(record, {'type': 'message', 'role': 'assistant', 'text': text})
        self.emit(record, {'type': 'done'})

    def events(self, handle):
        return [frame['arguments']['data'] for _, frame in self.frames
                if frame.get('arguments', {}).get('name') == 'sessions.event'
                and frame['arguments']['data'].get('handle') == handle]

    def test_acquire_uses_distinct_native_sessions_host_profile_and_stable_mapping(self):
        one, two = self.acquire(), self.acquire('channel-two')
        self.assertNotEqual(one['sessionId'], two['sessionId'])
        self.assertTrue(one['created'])
        again = self.acquire()
        self.assertEqual(one['sessionId'], again['sessionId'])
        self.assertFalse(again['created'])
        self.assertEqual({one['sessionId'], two['sessionId']},
            {row['id'] for row in self.b.sessions} & {one['sessionId'], two['sessionId']})
        record = self.b._pool.find(one['sessionId'])
        self.assertEqual((record.workspace, record.model, record.provider),
            (str(self.workspace), 'test-model', 'test-provider'))
        self.assertIs(self.b._view, self.selected)
        self.assertFalse(self.commands)
        self.b.store.save()
        persisted = json.loads((self.b.store.directory / 'settings.json').read_text(encoding='utf-8'))
        self.assertTrue(persisted.get('pluginSessions'))
        self.assertIn('pluginSession', persisted['sessionMeta'][one['sessionId']])

    def test_application_permission_profile_and_foreign_handle_boundaries(self):
        handle = self.acquire()['handle']
        denied = self.request('sessions.history', {'handle': handle}, owner='fixture-other')
        self.assertFalse(denied['ok'])
        self.install_owner('fixture-session', lifecycle='session')
        self.assertFalse(self.request('sessions.acquire', {'namespace': 'default', 'externalKey': 'x',
            'profile': 'tasks', 'createIfMissing': True}, owner='fixture-session')['ok'])
        self.install_owner('fixture-denied', permissions=[])
        self.assertFalse(self.request('sessions.acquire', {'namespace': 'default', 'externalKey': 'x',
            'profile': 'tasks', 'createIfMissing': True}, owner='fixture-denied')['ok'])
        self.assertFalse(self.request('sessions.acquire', {'namespace': 'default', 'externalKey': 'x',
            'profile': 'missing', 'createIfMissing': True})['ok'])
        self.assertFalse(self.request('sessions.acquire', {'namespace': 'default', 'externalKey': 'x',
            'profile': 'tasks', 'createIfMissing': True, 'workspace': str(self.base)})['ok'])

    def test_busy_submit_is_a_separate_run_with_scoped_replies_and_wait(self):
        owned = self.acquire()
        handle = owned['handle']
        self.result('sessions.subscribe', {'handle': handle})
        one = self.result('sessions.submit', {'handle': handle, 'requestId': 'first', 'content': 'one'})
        two = self.result('sessions.submit', {'handle': handle, 'requestId': 'second', 'content': 'two'})
        self.assertEqual((one['disposition'], two['disposition']), ('started', 'queued'))
        self.assertNotEqual(one['runId'], two['runId'])
        self.assertEqual(len(self.commands), 1)
        waiter = self.request('sessions.wait', {'handle': handle, 'runId': two['runId']}, wait=False)
        self.app.processEvents()
        self.assertNotIn(waiter, self.answers)
        record = self.b._pool.find(owned['sessionId'])
        self.finish(record, 'first reply')
        pump_until(self.app, lambda: len(self.commands) == 2, 'Queued run did not start')
        self.assertEqual([row[2]['text'] for row in self.commands], ['one', 'two'])
        self.finish(record, 'second reply')
        terminal = pump_until(self.app, lambda: self.answers.get(waiter), 'Run waiter did not finish')
        self.assertTrue(terminal['ok'], terminal)
        self.assertEqual(terminal['result']['status'], 'completed')
        ends = [event for event in self.events(handle) if event['type'] == 'turn_end']
        self.assertEqual([event['runId'] for event in ends], [one['runId'], two['runId']])
        for event, text in zip(ends, ('first reply', 'second reply')):
            self.assertIn(text, json.dumps(event))
            self.assertEqual(event['sessionId'], owned['sessionId'])
        self.assertIs(self.b._view, self.selected)

    def test_cancel_queued_run_has_its_own_terminal_and_never_executes(self):
        owned = self.acquire()
        handle = owned['handle']
        first = self.result('sessions.submit', {'handle': handle, 'requestId': 'one', 'content': 'one'})
        second = self.result('sessions.submit', {'handle': handle, 'requestId': 'two', 'content': 'two'})
        self.result('sessions.cancel', {'handle': handle, 'runId': second['runId']})
        terminal = self.result('sessions.wait', {'handle': handle, 'runId': second['runId']})
        self.assertEqual(terminal['status'], 'cancelled')
        self.finish(self.b._pool.find(owned['sessionId']), 'first reply')
        self.assertEqual(len(self.commands), 1)
        self.assertEqual(self.result('sessions.wait', {'handle': handle, 'runId': first['runId']})['status'], 'completed')
        self.result('sessions.release', {'handle': handle})
        self.assertFalse(self.request('sessions.history', {'handle': handle})['ok'])

    def test_queued_turn_reapplies_the_current_desktop_tool_ceiling(self):
        profile = self.b.store.data['pluginSessionProfiles']['fixture-channel']['tasks']
        profile['tools'] = ['read', 'write']
        owned = self.acquire()
        handle = owned['handle']
        record = self.b._pool.find(owned['sessionId'])
        self.result('sessions.submit', {'handle': handle, 'requestId': 'first', 'content': 'first'})
        self.result('sessions.submit', {'handle': handle, 'requestId': 'queued', 'content': 'queued'})
        self.assertEqual(record._plugin_policy['allowedTools'], ['read', 'write'])
        profile['tools'] = ['read']
        self.finish(record, 'first reply')
        pump_until(self.app, lambda: len(self.commands) == 2, 'Queued turn did not start')
        self.assertEqual(record._plugin_policy['allowedTools'], ['read'])

    def approval(self, record, identifier):
        event = {'type': 'ui_request', 'id': identifier, 'method': 'confirm',
            'title': 'Fixture permission', 'message': 'Allow offline fixture tool?'}
        self.emit(record, event)
        return event

    def test_plugin_approval_answer_is_scoped_and_duplicate_or_late_replies_are_rejected(self):
        owned, unrelated = self.acquire(), self.acquire('unrelated')
        handle, other = owned['handle'], unrelated['handle']
        self.result('approvals.registerHandler', {'handle': handle})
        self.result('approvals.registerHandler', {'handle': other})
        run = self.result('sessions.submit', {'handle': handle, 'requestId': 'approval', 'content': 'ask'})
        record = self.b._pool.find(owned['sessionId'])
        with patch.object(self.b._pool, 'write') as write:
            self.approval(record, 'approve-one')
            requests = [event for event in self.events(handle) if event['type'] == 'approval_request']
            self.assertEqual(requests[-1]['runId'], run['runId'])
            self.assertFalse(record.approval)
            self.assertFalse(self.result('approvals.respond', {'handle': other,
                'requestId': 'approve-one', 'decision': 'allow'})['accepted'])
            self.assertTrue(self.result('approvals.respond', {'handle': handle,
                'requestId': 'approve-one', 'decision': 'allow'})['accepted'])
            write.assert_called_once_with(record, {'type': 'ui_response', 'id': 'approve-one', 'value': True})
            self.assertFalse(self.result('approvals.respond', {'handle': handle,
                'requestId': 'approve-one', 'decision': 'deny'})['accepted'])
            self.assertEqual(write.call_count, 1)
        self.assertIs(self.b._view, self.selected)

    def test_unhandled_and_grace_timeout_use_normal_desktop_approval_then_deadline_denies(self):
        owned = self.acquire()
        handle = owned['handle']
        record = self.b._pool.find(owned['sessionId'])
        self.result('approvals.registerHandler', {'handle': handle})
        service = self.m._host_services._sessions
        with patch.object(self.b._pool, 'write') as write:
            event = self.approval(record, 'unhandled')
            self.assertTrue(self.result('approvals.respond', {'handle': handle,
                'requestId': 'unhandled', 'decision': 'unhandled'})['accepted'])
            self.assertEqual(record.approval, event)
            self.assertIs(self.b._view, self.selected)
            self.b._view = record  # Simulate the user selecting the waiting native chat.
            self.assertEqual(self.b.pendingApproval, event)
            service.approvals['unhandled']['deadline'].timeout.emit()
            self.assertFalse(self.b.pendingApproval)
            self.assertEqual(write.call_args.args[1], {'type': 'ui_response', 'id': 'unhandled', 'value': False})
            self.b._view = self.selected
            event = self.approval(record, 'grace')
            service.approvals['grace']['grace'].timeout.emit()
            self.assertEqual(record.approval, event)
            self.assertFalse(self.result('approvals.respond', {'handle': handle,
                'requestId': 'grace', 'decision': 'allow'})['accepted'])
            service.approvals['grace']['deadline'].timeout.emit()

    def test_profile_approval_default_is_desktop_only(self):
        self.b.store.data['pluginSessionProfiles']['fixture-channel']['tasks'].pop('allowApprovals')
        owned = self.acquire()
        handle = owned['handle']
        self.assertFalse(self.request('approvals.registerHandler', {'handle': handle})['ok'])
        record = self.b._pool.find(owned['sessionId'])
        with patch.object(self.b._pool, 'write'):
            event = self.approval(record, 'desktop-only')
            self.assertEqual(record.approval, event)
            self.assertFalse(any(row['type'] == 'approval_request' for row in self.events(handle)))
            self.m._host_services._sessions.approvals['desktop-only']['deadline'].timeout.emit()

    def test_plugin_session_cannot_gain_a_whole_session_dangerous_approval(self):
        owned = self.acquire()
        record = self.b._pool.find(owned['sessionId'])
        meta = self.b.store.data['sessionMeta'][record.id]
        meta['dangerousAllowed'] = True  # Even an older persisted grant is ineffective.
        self.assertFalse(self.b._dangerous_allowed(record))
        self.b._view = record
        record.approval = {'id': 'dangerous', 'method': 'confirm', 'dangerCategory': 1}
        try:
            self.assertFalse(self.b.dangerousAllowed)
            self.assertFalse(self.b.canGrantDangerousApproval)
            meta.pop('dangerousAllowed')
            self.b.grantDangerousApproval()
            self.assertNotIn('dangerousAllowed', meta)
            self.assertEqual(record.approval['id'], 'dangerous')
        finally:
            record.approval = {}
            self.b._view = self.selected

    def test_handler_stop_preserves_desktop_approval_and_cancels_only_queued_run(self):
        owned = self.acquire()
        handle = owned['handle']
        self.result('approvals.registerHandler', {'handle': handle})
        first = self.result('sessions.submit', {'handle': handle, 'requestId': 'active', 'content': 'active'})
        queued = self.result('sessions.submit', {'handle': handle, 'requestId': 'queued', 'content': 'queued'})
        record = self.b._pool.find(owned['sessionId'])
        service = self.m._host_services._sessions
        with patch.object(self.b._pool, 'write') as write:
            event = self.approval(record, 'handler-stopped')
            self.m._host_services.stop('fixture-channel')
            self.assertEqual(record.approval, event)
            self.assertIs(self.b._view, self.selected)
            self.assertNotIn(handle, service.handles)
            self.assertEqual(service.runs[queued['runId']]['status'], 'cancelled')
            self.assertEqual(service.runs[first['runId']]['status'], 'running')
            self.assertEqual(service.active[record.key], first['runId'])
            write.assert_not_called()
            service.approvals['handler-stopped']['deadline'].timeout.emit()
            write.assert_called_once_with(record, {
                'type': 'ui_response', 'id': 'handler-stopped', 'value': False})
            self.assertFalse(record.approval)
            self.emit(record, {'type': 'done'})
            self.assertEqual(service.runs[first['runId']]['status'], 'completed')
            self.assertNotIn(record.key, service.active)
            self.assertEqual(len(self.commands), 1)


if __name__ == '__main__':
    unittest.main()
