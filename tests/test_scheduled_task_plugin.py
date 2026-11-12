"""Timer Agent methods use the calling session, not IDs supplied by the model."""
import importlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'plugin-runtime'))
from umeko_plugin_sdk import Context, PluginError
from umeko_plugin_sdk.packages import validate_config
package = types.ModuleType('_scheduled_plugin_tests')
package.__path__ = [str(ROOT/'umeko-plugins/scheduled-tasks/scripts')]
sys.modules[package.__name__] = package
Plugin = importlib.import_module(package.__name__ + '.plugin').ScheduledTasksPlugin


class ScheduledTaskPluginTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.context = Context(ROOT/'umeko-plugins/scheduled-tasks', Path(temp.name), {}, {}, [], lifecycle='application')
        self.context.request_session = {'id': 'one', 'token': 'token-one', 'workspace': '/one',
                                       'timerTargets': [{'id': 'main', 'name': 'Main'}, {'id': 'agent:'+'a'*32, 'name': 'Connected'}]}
        self.plugin = Plugin(self.context)
        self.addCleanup(self.plugin.close)
        self.schema = json.loads((ROOT/'umeko-plugins/scheduled-tasks/manifest.json').read_text(encoding='utf-8'))['agent']['methods']

    def call(self, method, args):
        validate_config(args, self.schema[method]['parameters'])
        return self.plugin.handle(method, args)

    def create(self, **extra):
        return self.call('create', dict(name='Check progress', message='Summarize current progress', enabled=False,
            schedule={'frequency': 'interval', 'interval_value': 0.25, 'interval_unit': 'minutes'}, **extra))['task_id']

    def test_agent_create_list_enable_disable_delete_and_quota(self):
        keys = [self.create() for _ in range(5)]
        with self.assertRaisesRegex(PluginError, '5'):self.create()
        self.assertEqual(len(self.call('list', {})['tasks']), 5)
        self.call('enable', {'task_id': keys[0]})
        task = next(row for row in self.call('list', {})['tasks'] if row['id'] == keys[0])
        self.assertTrue(task['enabled'])
        self.assertGreaterEqual(task['next_at'], self.plugin.now() + 14)
        self.call('disable', {'task_id': keys[0]})
        self.call('delete', {'task_id': keys[0]})
        self.create()
        self.assertEqual(len(self.call('list', {})['tasks']), 5)

    def test_foreground_switch_cannot_redirect_agent_owner_or_access_another_session(self):
        key = self.create()
        original = self.context.request_session
        self.context.session = {'token': 'visible-elsewhere', 'id': 'visible', 'workspace': '/visible'}
        self.assertEqual(self.call('list', {})['tasks'][0]['id'], key)
        self.context.request_session = {**original, 'token': 'token-two', 'id': 'two'}
        self.assertEqual(self.call('list', {})['tasks'], [])
        for operation in ('enable', 'disable', 'delete', 'history'):
            with self.subTest(operation=operation), self.assertRaises(PluginError):self.call(operation, {'task_id': key})
        self.context.request_session = original
        self.assertEqual(self.call('list', {})['tasks'][0]['id'], key)

    def test_connected_targets_only_and_all_short_intervals_rejected(self):
        self.create(target='agent:'+'a'*32)
        with self.assertRaisesRegex(PluginError, 'Agent Bus'):self.create(target='agent:'+'b'*32)
        for value in (0, -1, 0.249999):
            args = dict(name='Invalid', message='No dispatch', schedule={'frequency':'interval', 'interval_value':value, 'interval_unit':'minutes'})
            with self.subTest(value=value), self.assertRaises(PluginError):self.call('create', args)
        self.assertEqual(len(self.call('list', {})['tasks']), 1)
