"""Offline QQ normalized-message contract using the real Umeko SDK wire helpers."""
import copy
import importlib.util
from pathlib import Path
import queue
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'plugin-runtime'))
from umeko_plugin_sdk import Context, PluginError
from umeko_plugin_sdk.packages import validate
from umeko_plugin_sdk.sessions import OPERATIONS
PACKAGE = ROOT / 'plugin-runtime/examples/qq-session-adapter'
spec = importlib.util.spec_from_file_location('qq_adapter_example', PACKAGE / 'scripts/plugin.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def message(sender='alice', identifier='m1', text='合成测试'):
    return {'kind': 'c2c', 'senderId': sender, 'messageId': identifier, 'content': text,
            'replyTarget': {'scope': 'c2c', 'targetId': sender, 'msgId': identifier}}


class MemoryTransport:
    def __init__(self):
        self.sent = []
        self.fail = False

    def send_text(self, target, text):
        self.sent.append((copy.deepcopy(target), text))
        if self.fail:
            raise OSError('synthetic uncertain send')


class WireHost:
    """Synthetic host, not a model runtime; records every real SDK request."""
    def __init__(self):
        self.frames, self.mapping, self.leases, self.runs = [], {}, {}, {}
        self.terminal_status = 'completed'
        self.wrong_run = False
        self.before_terminal = None
        self.messages_override = None
        self.fail_submit = False
        self.context = None

    def emit(self, frame):
        request = copy.deepcopy(frame['arguments'])
        op, args = request['operation'], request['arguments']
        self.frames.append(request)
        if op == 'sessions.acquire':
            key = (args['namespace'], args['externalKey'])
            created = key not in self.mapping
            session = self.mapping.setdefault(key, 's' + str(len(self.mapping)))
            handle = 'h' + str(len(self.frames))
            self.leases[handle] = session
            value = {'handle': handle, 'sessionId': session, 'created': created}
        elif op == 'sessions.submit':
            if self.fail_submit:
                raise RuntimeError('synthetic uncertain submit')
            run = 'r' + str(len(self.runs))
            self.runs[run] = args['content']
            value = {'runId': run, 'disposition': 'queued'}
        elif op == 'sessions.wait':
            if self.before_terminal:
                self.before_terminal()
            value = {'runId': 'wrong' if self.wrong_run else args['runId'],
                     'status': self.terminal_status,
                     'assistantMessages': (self.messages_override if self.messages_override is not None
                                           else ['回复：' + self.runs[args['runId']]])}
        elif op == 'sessions.release':
            self.leases.pop(args['handle'])
            value = {'released': True}
        else:
            raise AssertionError('Unexpected host operation: ' + op)
        self.context._dispatch_host_event('host.response', {'requestId': request['id'],
            'operation': op, 'ok': True, 'result': value})


class QQAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.host, self.transport = WireHost(), MemoryTransport()
        self.context = Context(package_dir=PACKAGE, state_dir=Path(self.temp.name), config={},
            session={'id': 'foreground-never-used'}, permissions=['sessions.manage'],
            lifecycle='application', emit=self.host.emit,
            host_capabilities={'operations': {op: {'permission': 'sessions.manage'} for op in OPERATIONS}})
        self.host.context = self.context
        self.addCleanup(self.context.close)
        self.adapter = self.new_adapter()
        # A future accidental socket use must fail; these tests need no network.
        self.network = patch('socket.socket', side_effect=AssertionError('Network forbidden'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def new_adapter(self, account='synthetic-account', **kwargs):
        return module.Adapter(self.context.sessions, self.transport, account=account,
                              profile='approved-test-profile', allowed_senders=('alice', 'bob'), **kwargs)

    def run_call(self, call):
        results = queue.Queue()
        def invoke():
            try:
                results.put((True, call()))
            except Exception as error:
                results.put((False, error))
        thread = threading.Thread(target=invoke, daemon=True)
        thread.start()
        thread.join(2)
        self.assertFalse(thread.is_alive(), 'background helper deadlocked')
        ok, result = results.get_nowait()
        if not ok:
            raise result
        return result

    def receive(self, value=None, adapter=None):
        return self.run_call(lambda: (adapter or self.adapter).receive(value or message()))

    def test_reply_waits_for_exact_run_and_preserves_captured_target(self):
        self.host.before_terminal = lambda: self.assertEqual(self.transport.sent, [])
        self.assertEqual(self.receive(), {'status': 'completed', 'runId': 'r0', 'replied': True})
        self.assertEqual(self.transport.sent, [(message()['replyTarget'], '回复：合成测试')])
        self.assertEqual([f['operation'] for f in self.host.frames],
                         ['sessions.acquire', 'sessions.submit', 'sessions.wait', 'sessions.release'])
        self.assertTrue(all(f['session'] == {} for f in self.host.frames))
        self.assertFalse(self.host.leases)

    def test_distinct_senders_and_accounts_have_distinct_sessions(self):
        self.receive()
        self.receive(message('bob'))
        self.receive(adapter=self.new_adapter(account='second-account'))
        self.assertEqual(len(self.host.mapping), 3)
        self.assertEqual([target['targetId'] for target, text in self.transport.sent], ['alice', 'bob', 'alice'])

    def test_recreated_adapter_reacquires_mapping_but_never_reuses_handle(self):
        self.receive()
        self.receive(message(identifier='m2'), self.new_adapter())
        self.assertEqual(len(self.host.mapping), 1)
        acquired = [f['arguments']['handle'] for f in self.host.frames if f['operation'] == 'sessions.submit']
        self.assertEqual(len(set(acquired)), 2)

    def test_duplicate_suppression_and_bounded_retention(self):
        adapter = self.new_adapter(capacity=2)
        self.receive(adapter=adapter)
        self.assertEqual(self.receive(adapter=adapter)['status'], 'duplicate')
        for key in ('m2', 'm3'):
            self.receive(message(identifier=key), adapter)
        self.assertEqual(len(adapter.seen), 2)
        self.assertEqual(len(self.transport.sent), 3)

    def test_duplicate_concurrent_callback_submits_once(self):
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.adapter.receive(message()))) for _ in range(8)]
        for t in threads:t.start()
        for t in threads:t.join(2)
        self.assertEqual(len(results), 8)
        self.assertEqual(len(self.transport.sent), 1)
        self.assertEqual(sum(x['status'] == 'duplicate' for x in results), 7)

    def test_uncertain_send_is_not_replayed(self):
        self.transport.fail = True
        with self.assertRaises(OSError):self.receive()
        self.assertEqual(self.receive()['status'], 'duplicate')
        self.assertEqual(len(self.transport.sent), 1)
        self.assertFalse(self.host.leases)

    def test_uncertain_submit_is_not_replayed(self):
        self.host.fail_submit = True
        with self.assertRaises(RuntimeError):self.receive()
        self.assertEqual(self.receive()['status'], 'duplicate')
        self.assertFalse(self.transport.sent)
        self.assertFalse(self.host.leases)

    def test_wrong_terminal_run_never_sends(self):
        self.host.wrong_run = True
        with self.assertRaisesRegex(ValueError, 'run identity'):self.receive()
        self.assertFalse(self.transport.sent)
        self.assertFalse(self.host.leases)

    def test_failed_cancelled_runs_do_not_send_partial_or_error_details(self):
        for status in ('failed', 'cancelled'):
            self.host.terminal_status = status
            self.assertEqual(self.receive(message(identifier=status))['status'], status)
        self.assertFalse(self.transport.sent)

    def test_stop_during_wait_suppresses_completion_and_new_work(self):
        self.host.before_terminal = self.adapter.stop
        self.assertEqual(self.receive()['status'], 'stopped')
        self.assertEqual(self.receive(message(identifier='later'))['status'], 'stopped')
        self.assertFalse(self.transport.sent)
        self.assertFalse(self.host.leases)

    def test_untrusted_sender_and_empty_allowlist_deny_without_host_requests(self):
        self.assertEqual(self.receive(message('mallory'))['status'], 'denied')
        adapter = module.Adapter(self.context.sessions, self.transport, account='a', profile='p')
        self.assertEqual(self.receive(adapter=adapter)['status'], 'denied')
        self.assertFalse(self.host.frames)

    def test_invalid_scope_target_and_payload_rejected_before_side_effects(self):
        bad = []
        for key, value in [('kind', 'group'), ('senderIsBot', True), ('content', ''),
                           ('content', '中' * 3000), ('messageId', ''), ('attachments', [{}]), ('msgElements', [{}])]:
            entry = message();entry[key] = value;bad.append(entry)
        for key, value in [('scope', 'group'), ('targetId', 'other'), ('msgId', 'other')]:
            entry = message();entry['replyTarget'][key] = value;bad.append(entry)
        for entry in bad:
            with self.subTest(entry=entry), self.assertRaises(ValueError):self.receive(entry)
        self.assertFalse(self.host.frames)

    def test_empty_final_does_not_invent_a_reply(self):
        self.host.messages_override = []
        self.assertFalse(self.receive()['replied'])
        self.assertFalse(self.transport.sent)

    def test_malformed_final_is_not_forwarded(self):
        self.host.messages_override = [{'text': 'not the SDK terminal schema'}]
        with self.assertRaisesRegex(ValueError, 'assistant messages'):self.receive()
        self.assertFalse(self.transport.sent)
        self.assertFalse(self.host.leases)

    def test_owner_stop_and_context_close_wake_pending_wait(self):
        def shutdown():
            self.adapter.stop()
            self.context.close()
        self.host.before_terminal = shutdown
        # The host reply may arrive after Context.close; no late output is sent.
        with self.assertRaises(PluginError):self.receive()
        self.assertFalse(self.transport.sent)
        self.assertTrue(self.context.cancelled.is_set())

    def test_reader_thread_is_rejected_by_real_sdk(self):
        with self.assertRaisesRegex(PluginError, 'background thread'):
            self.adapter.receive(message())
        self.assertFalse(self.host.frames)

    def test_package_valid_and_factory_inert(self):
        manifest, defaults, schema = validate(PACKAGE)
        self.assertEqual(manifest['permissions'], ['sessions.manage'])
        self.assertEqual(manifest['lifecycle'], 'application')
        plugin = module.create_plugin(self.context)
        self.assertEqual(plugin.handle('status', {}),
                         {'mode': 'offline', 'connected': False, 'acceptsMessages': False})
        with self.assertRaises(PluginError):plugin.handle('receive', message())
        self.assertFalse(self.host.frames)


if __name__ == '__main__':
    unittest.main()
