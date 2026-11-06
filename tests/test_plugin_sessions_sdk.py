"""Focused transport and example tests; no application, provider or model startup."""
import importlib.util
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'plugin-runtime'))
from umeko_plugin_sdk import Context, PluginError
from umeko_plugin_sdk.packages import validate
from umeko_plugin_sdk.sessions import OPERATIONS


class PluginSessionSdkTests(unittest.TestCase):
    def make_context(self, folder, emit, **overrides):
        values = dict(package_dir=Path(folder), state_dir=Path(folder), config={}, session={},
            permissions=['sessions.manage'], emit=emit, lifecycle='application',
            host_capabilities={'operations': {name: {'permission': 'sessions.manage'} for name in OPERATIONS}})
        values.update(overrides)
        return Context(**values)

    def background(self, call):
        result = queue.Queue()
        def run():
            try:result.put((True, call()))
            except Exception as error:result.put((False, error))
        thread = threading.Thread(target=run)
        thread.start()
        return thread, result

    def test_immediate_response_is_registered_before_emit_and_copied(self):
        with tempfile.TemporaryDirectory() as folder:
            frames = []
            native_value = {'handle': 'h', 'sessionId': 's', 'created': True}
            def emit(frame):
                frames.append(frame)
                request = frame['arguments']
                context._dispatch_host_event('host.response', {'requestId': request['id'],
                    'operation': request['operation'], 'ok': True, 'result': native_value})
                native_value['sessionId'] = 'mutated-after-delivery'
            context = self.make_context(folder, emit)
            thread, result = self.background(lambda: context.sessions.acquire('task-1', profile='tasks'))
            thread.join(2)
            ok, value = result.get(timeout=1)
            self.assertTrue(ok, value)
            self.assertEqual(value, {'handle': 'h', 'sessionId': 's', 'created': True})
            self.assertEqual(frames[0]['arguments']['session'], {})
            self.assertEqual(frames[0]['arguments']['arguments'], {'namespace': 'default',
                'externalKey': 'task-1', 'createIfMissing': True, 'profile': 'tasks'})

    def test_helpers_reject_reader_thread_and_raw_requests_keep_other_bindings(self):
        with tempfile.TemporaryDirectory() as folder:
            frames = []
            context = self.make_context(folder, frames.append)
            with self.assertRaisesRegex(PluginError, 'background thread'):
                context.sessions.wait('h', 'r')
            identifier = context.request_host('sessions.subscribe', {'handle': 'h'})
            self.assertEqual(frames[0]['arguments']['id'], identifier)
            context.host_capabilities['operations']['pi.status'] = {'permission': 'pi.read'}
            context.permissions.append('pi.read')
            with self.assertRaises(PluginError):context.request_host('pi.status')
            context.request_host('pi.status', session={'token': 'front', 'id': 'f', 'workspace': folder})
            self.assertEqual(frames[-1]['arguments']['session']['token'], 'front')
            context.lifecycle = 'session'
            with self.assertRaisesRegex(PluginError, 'application lifecycle'):
                context.request_host('sessions.subscribe', {'handle': 'h'})
            context.lifecycle = 'application'
            context.permissions.remove('sessions.manage')
            with self.assertRaises(PluginError):context.request_host('sessions.subscribe', {'handle': 'h'})

    def test_close_wakes_pending_terminal_wait_without_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            requested = threading.Event()
            context = self.make_context(folder, lambda frame: requested.set())
            thread, result = self.background(lambda: context.sessions.wait('h', 'run-1'))
            self.assertTrue(requested.wait(1))
            context.close()
            thread.join(2)
            ok, error = result.get(timeout=1)
            self.assertFalse(ok)
            self.assertIsInstance(error, PluginError)
            self.assertIn('stopping', str(error))
            self.assertEqual(context.sessions._pending, {})

    def test_timeout_does_not_send_cancel_and_host_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            frames = []
            context = self.make_context(folder, frames.append)
            thread, result = self.background(lambda: context.sessions.wait('h', 'r', timeout=0))
            thread.join(2)
            ok, error = result.get(timeout=1)
            self.assertFalse(ok)
            self.assertIn('not cancelled', str(error))
            self.assertEqual([x['arguments']['operation'] for x in frames], ['sessions.wait'])
            request = frames[0]['arguments']
            context._dispatch_host_event('host.response', {'requestId': request['id'],
                'operation': request['operation'], 'ok': True, 'result': {'status': 'completed'}})
            self.assertEqual(context.sessions._pending, {})
            def fail(frame):
                request = frame['arguments']
                context._dispatch_host_event('host.response', {'requestId': request['id'],
                    'operation': request['operation'], 'ok': False, 'error': 'profile denied'})
            context.emit = fail
            thread, result = self.background(lambda: context.sessions.acquire('x', profile='missing'))
            thread.join(2)
            ok, error = result.get(timeout=1)
            self.assertFalse(ok)
            self.assertEqual(str(error), 'profile denied')

    def test_all_helper_arguments_match_service_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            frames = []
            def emit(frame):
                request = frame['arguments'];frames.append(request)
                context._dispatch_host_event('host.response', {'requestId': request['id'],
                    'operation': request['operation'], 'ok': True, 'result': {}})
            context = self.make_context(folder, emit)
            def task():
                service = context.sessions
                service.submit('h', 'input-1', 'Hello')
                service.subscribe('h');service.wait('h', 'run-1')
                service.cancel('h');service.cancel('h', 'run-2')
                service.history('h');service.history('h', 10)
                service.register_approval_handler('h')
                service.respond_approval('h', 'approval-1', 'unhandled')
                service.release('h')
            thread, result = self.background(task)
            thread.join(2)
            ok, value = result.get(timeout=1)
            self.assertTrue(ok, value)
            self.assertEqual([(x['operation'], x['arguments']) for x in frames], [
                ('sessions.submit', {'handle': 'h', 'requestId': 'input-1', 'content': 'Hello'}),
                ('sessions.subscribe', {'handle': 'h'}), ('sessions.wait', {'handle': 'h', 'runId': 'run-1'}),
                ('sessions.cancel', {'handle': 'h'}), ('sessions.cancel', {'handle': 'h', 'runId': 'run-2'}),
                ('sessions.history', {'handle': 'h'}), ('sessions.history', {'handle': 'h', 'limit': 10}),
                ('approvals.registerHandler', {'handle': 'h'}),
                ('approvals.respond', {'handle': 'h', 'requestId': 'approval-1', 'decision': 'unhandled'}),
                ('sessions.release', {'handle': 'h'}),
            ])

    def test_complete_example_runs_one_task_without_front_chat(self):
        example = ROOT / 'plugin-runtime/examples/session-task-service'
        manifest, defaults, _ = validate(example)
        self.assertEqual(manifest['permissions'], ['sessions.manage'])
        spec = importlib.util.spec_from_file_location('session_task_example_test', example / 'scripts/plugin.py')
        module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            frames = []
            replies = {'sessions.acquire': {'handle': 'h', 'sessionId': 's', 'created': True},
                'sessions.subscribe': {'subscribed': True},
                'sessions.submit': {'runId': 'r', 'disposition': 'started'},
                'sessions.wait': {'runId': 'r', 'status': 'completed', 'assistantMessages': ['Done']},
                'sessions.release': {'released': True}}
            def emit(frame):
                request = frame['arguments'];frames.append(request)
                context._dispatch_host_event('host.response', {'requestId': request['id'],
                    'operation': request['operation'], 'ok': True, 'result': replies[request['operation']]})
            config = {**defaults, 'externalKey': 'restart-task', 'oneShot': True}
            context = self.make_context(folder, emit, config=config)
            plugin = module.create_plugin(context)
            plugin.thread.join(2)
            self.assertFalse(plugin.thread.is_alive())
            self.assertEqual([x['operation'] for x in frames], list(replies))
            self.assertTrue(all(x['session'] == {} for x in frames))
            value = plugin.handle('status', {})
            self.assertEqual(value['status'], 'completed')
            self.assertEqual(value['assistantMessages'], ['Done'])
            self.assertEqual(value['externalKey'], 'restart-task')
            self.assertEqual(json.loads((Path(folder) / 'latest-task.json').read_text(encoding='utf-8')), value)
            plugin.close()


if __name__ == '__main__':unittest.main()
