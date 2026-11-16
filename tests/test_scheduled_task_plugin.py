"""Timer Agent methods use the calling session, not IDs supplied by the model."""
import importlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'plugin-runtime'))
from umeko_plugin_sdk import Context, PluginError
from umeko_plugin_sdk.packages import validate, validate_config
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

    def test_global_timer_shared_but_main_timer_private_and_source_preserved(self):
        self.stop_scheduler()
        target = 'agent:'+'a'*32
        self.context.request_session['timerGlobalTargets'] = [{'id':target,'name':'Connected'}]
        key = self.create(target=target)
        private = self.create()
        source = self.context.request_session
        self.context.request_session = {**source, 'id':'two', 'token':'token-two', 'workspace':'/two',
                                       'timerTargets':[{'id':'main','name':'Main'}]}
        task, = self.call('list', {})['tasks']
        self.assertEqual((task['id'], task['global'], task['target_missing'], task['target_name']), (key, True, False, 'Connected'))
        self.plugin.handle('save', dict(task_id=key, name='Shared renamed', message='Keep origin', enabled=False,
            target=target, schedule={'frequency':'interval','interval_value':1,'interval_unit':'hours'}))
        updated, = self.call('list', {})['tasks']
        self.assertEqual(updated['source']['id'], 'one')
        self.assertEqual(updated['owner'], 'session:one')
        self.call('enable', {'task_id':key})
        with self.assertRaises(PluginError):self.call('delete', {'task_id':private})
        self.plugin.on_event('scheduledTasks.targetsChanged', {'global_targets':[]})
        self.context.request_session['timerGlobalTargets'] = []
        missing, = self.call('list', {})['tasks']
        self.assertEqual((missing['enabled'], missing['next_at'], missing['target_missing']), (0, None, True))
        self.assertEqual(missing['target_name'], '无 / None')
        for operation in ('enable','run'):
            with self.subTest(operation=operation), self.assertRaises(PluginError):self.plugin.handle(operation, {'task_id':key})
        self.call('delete', {'task_id':key})
        self.assertEqual(self.call('list', {})['tasks'], [])

    def test_rebinding_global_to_main_transfers_private_ownership_without_losing_history(self):
        self.stop_scheduler()
        key = self.create(target='agent:'+'a'*32)
        run = self.plugin.store.claim_manual(key, self.plugin.now(), owner='session:one')
        self.plugin.store.finish(run['id'], 'delivered', self.plugin.now())
        source = self.context.request_session
        self.context.request_session = {**source, 'id':'two','token':'token-two','workspace':'/two'}
        self.plugin.handle('save', dict(task_id=key, name='Now private', message='Deliver here', target='main',
            enabled=False, schedule={'frequency':'interval','interval_value':1,'interval_unit':'hours'}))
        task, = self.call('list', {})['tasks']
        self.assertFalse(task['global'])
        self.assertEqual((task['owner'],task['source']['id']), ('session:two','two'))
        self.assertEqual(self.call('history', {'task_id':key})['runs'][0]['snapshot']['target'], 'agent:'+'a'*32)
        self.context.request_session = source
        self.assertEqual(self.call('list', {})['tasks'], [])
        with self.assertRaises(PluginError):self.call('history', {'task_id':key})

    @unittest.skipUnless(hasattr(__import__('time'), 'tzset'), 'Process TZ requires tzset')
    def test_next_label_uses_system_zone_instead_of_saved_schedule_zone(self):
        import os, time
        self.stop_scheduler()
        self.plugin.handle('save', dict(name='Local display', message='Same instant', enabled=True,
            schedule={'frequency':'once','first_date':'2030-01-01','local_time':'04:00','zone':'America/Los_Angeles'}))
        try:
            for zone, expected in (('Asia/Shanghai','2030-01-01 20:00:00'), ('America/New_York','2030-01-01 07:00:00')):
                with patch.dict(os.environ, {'TZ':zone}):
                    time.tzset()
                    row, = self.call('list', {})['tasks']
                    self.assertTrue(row['next_label'].startswith(expected), row['next_label'])
                    self.assertEqual(row['schedule']['zone'], 'America/Los_Angeles')
        finally:time.tzset()

    def test_connected_targets_only_and_all_short_intervals_rejected(self):
        self.create(target='agent:'+'a'*32)
        with self.assertRaisesRegex(PluginError, 'Agent Bus'):self.create(target='agent:'+'b'*32)
        for value in (0, -1, 0.249999):
            args = dict(name='Invalid', message='No dispatch', schedule={'frequency':'interval', 'interval_value':value, 'interval_unit':'minutes'})
            with self.subTest(value=value), self.assertRaises(PluginError):self.call('create', args)
        self.assertEqual(len(self.call('list', {})['tasks']), 1)

    def stop_scheduler(self):
        self.context.cancelled.set()
        self.plugin.commands.put(('stop', None))
        self.plugin.thread.join(timeout=2)
        self.assertFalse(self.plugin.thread.is_alive())

    def countdown(self, **extra):
        return dict(name='Wake up', message='Resume work', enabled=True,
            schedule={'frequency':'once', 'delay_value':5, 'delay_unit':'minutes'}, **extra)

    def test_injected_example_arms_now_and_reuses_only_finished_slot_at_quota(self):
        self.stop_scheduler()
        manifest = validate(ROOT/'umeko-plugins/scheduled-tasks')[0]
        text = manifest['agent']['prompt']
        calls = [json.JSONDecoder().raw_decode(part)[0] for part in text.split('umeko_desktop(')[1:]]
        self.assertEqual(calls[0], {'operation':'widgets.docs','arguments':{'id':'scheduled-tasks'}})
        example = calls[1]
        self.assertEqual((example['operation'], example['arguments']['id']), ('widgets.call', 'scheduled-tasks'))
        args = example['arguments']['arguments']
        self.assertEqual(args['schedule'], {'frequency':'once','delay_value':5,'delay_unit':'minutes'})
        now = self.plugin.now()
        with patch.object(self.plugin, 'now', return_value=now):
            for _ in range(4):self.create()
            key = self.call(example['arguments']['method'], args)['task_id']
        original = next(row for row in self.call('list', {})['tasks'] if row['id']==key)
        self.assertEqual((original['enabled'], original['next_at'], original['model_oneshot']), (1, now+300, 1))
        run, = self.plugin.store.claim_due(now+300, eligible_since=now)
        # A claimed delivery is still running even though its schedule expired.
        with patch.object(self.plugin, 'now', return_value=now+301), self.assertRaisesRegex(PluginError, '5'):
            self.call('create', self.countdown())
        self.plugin.store.finish(run['id'], 'delivered', now+301)
        with patch.object(self.plugin, 'now', return_value=now+302):
            replacement = self.call('create', self.countdown(target='agent:'+'a'*32))['task_id']
        self.assertEqual(replacement, key)
        tasks = self.call('list', {})['tasks']
        self.assertEqual(len(tasks), 5)
        updated = next(row for row in tasks if row['id']==key)
        self.assertEqual((updated['next_at'], updated['target'], updated['color_index']),
                         (now+602, 'agent:'+'a'*32, original['color_index']))
        history = self.call('history', {'task_id':key})['runs']
        self.assertEqual((len(history), history[0]['snapshot']['message'], history[0]['snapshot']['target']),
                         (1, args['message'], 'main'))

    def test_disabled_manual_edited_and_interval_timers_are_not_reused(self):
        self.stop_scheduler()
        now = self.plugin.now()
        with patch.object(self.plugin, 'now', return_value=now):
            manual = self.plugin.handle('save', self.countdown())['task_id']
            disabled = self.countdown();disabled['enabled']=False
            self.call('create', disabled)
            paused = self.call('create', self.countdown())['task_id']
            self.call('disable', {'task_id':paused})
            edited = self.call('create', self.countdown())['task_id']
            self.plugin.handle('save', dict(self.countdown(), task_id=edited))
            self.create()
        for run in self.plugin.store.claim_due(now+300, eligible_since=now):
            self.plugin.store.finish(run['id'], 'delivered', now+301)
        before = self.call('list', {})['tasks']
        self.assertTrue(all(not row['model_oneshot'] for row in before))
        with patch.object(self.plugin, 'now', return_value=now+302), self.assertRaisesRegex(PluginError, '5'):
            self.call('create', self.countdown())
        self.assertEqual(self.call('list', {})['tasks'], before)
        self.context.request_session = {**self.context.request_session, 'id':'two', 'token':'token-two'}
        with patch.object(self.plugin, 'now', return_value=now+302):
            other = self.call('create', self.countdown())['task_id']
        self.assertNotEqual(other, manual)

    def test_armed_model_timer_is_preserved_and_bad_countdowns_are_rejected(self):
        self.stop_scheduler()
        first = self.call('create', self.countdown())['task_id']
        second = self.call('create', self.countdown())['task_id']
        self.assertNotEqual(first, second)
        for delay in (0, -1, 0.249999, float('nan'), True):
            args = self.countdown();args['schedule']['delay_value']=delay
            with self.subTest(delay=delay), self.assertRaises(PluginError):self.call('create', args)
        self.assertEqual(len(self.call('list', {})['tasks']), 2)
