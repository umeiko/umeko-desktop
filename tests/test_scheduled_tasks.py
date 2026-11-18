from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time
from pathlib import Path
import json
import sqlite3
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase

SCRIPTS = Path(__file__).resolve().parents[1] / 'umeko-plugins/scheduled-tasks/scripts'
sys.path.insert(0, str(SCRIPTS))
from scheduled_tasks import Schedule, ScheduledTasks


def stamp(value):
    return int(datetime.fromisoformat(value).timestamp())


class CalendarTests(TestCase):
    def test_relative_oneshot_uses_server_clock_and_never_fires_early(self):
        now = stamp('2026-11-13T09:00:00+00:00')
        for value, unit, seconds in ((5,'minutes',300), (0.5,'hours',1800), (0.25,'days',21600), (0.255,'minutes',16)):
            schedule = Schedule.from_dict({'frequency':'once','delay_value':value,'delay_unit':unit}, now=now)
            self.assertEqual(schedule.next_after(now), now+seconds)
            self.assertIsNone(schedule.next_after(now+seconds))
            self.assertEqual(Schedule.from_dict(schedule.serialize()), schedule)
        with self.assertRaisesRegex(ValueError, 'not both'):
            Schedule.from_dict({'frequency':'once','delay_value':5,'delay_unit':'minutes','zone':'UTC'}, now=now)

    def test_decimal_intervals_in_all_three_units_and_exact_minimum(self):
        anchor = stamp('2026-11-13T09:00:00+00:00')
        for value, unit, seconds in (('0.25', 'minutes', 15), ('1.25', 'minutes', 75),
                                     ('0.5', 'hours', 1800), ('0.5', 'days', 43200),
                                     ('0.255', 'minutes', 15.3)):
            with self.subTest(value=value, unit=unit):
                schedule = Schedule('interval', interval_value=value, interval_unit=unit, anchor_at=anchor)
                due = schedule.next_after(anchor)
                self.assertAlmostEqual(due, anchor + seconds, places=6)
                for step in range(2, 200):
                    due = schedule.next_after(due)
                    self.assertAlmostEqual(due, anchor + seconds * step, places=6)
                self.assertEqual(Schedule.from_dict(schedule.serialize()), schedule)

    def test_short_nonfinite_or_unsupported_intervals_are_rejected(self):
        for value, unit in (('0.249999999', 'minutes'), ('0', 'days'), ('-1', 'hours'),
                            ('NaN', 'minutes'), ('Infinity', 'days'), ('abc', 'hours'),
                            (True, 'minutes'), ('20', 'seconds')):
            with self.subTest(value=value, unit=unit), self.assertRaises(ValueError):
                Schedule('interval', interval_value=value, interval_unit=unit, anchor_at=1)
    def test_weekdays_and_weekly_use_local_calendar(self):
        first = date(2026, 11, 13)  # Friday
        friday = stamp('2026-11-13T01:00:00+00:00')
        weekdays = Schedule('weekdays', first, time(9), 'Asia/Taipei')
        weekly = Schedule('weekly', first, time(9), 'Asia/Taipei')
        self.assertEqual(weekdays.next_after(friday), stamp('2026-11-16T01:00:00+00:00'))
        self.assertEqual(weekly.next_after(friday), stamp('2026-11-20T01:00:00+00:00'))
        self.assertEqual(Schedule.from_dict(weekly.serialize()), weekly)

    def test_dst_gap_advances_by_offset_change(self):
        schedule = Schedule('daily', date(2026, 3, 8), time(2, 30), 'America/New_York')
        due = schedule.next_after(stamp('2026-03-08T00:00:00+00:00'))
        self.assertEqual(due, stamp('2026-03-08T07:30:00+00:00'))
        self.assertEqual(schedule.next_after(due), stamp('2026-03-09T06:30:00+00:00'))

    def test_dst_overlap_uses_earlier_occurrence_only(self):
        schedule = Schedule('daily', date(2026, 11, 1), time(1, 30), 'America/New_York')
        due = schedule.next_after(stamp('2026-11-01T00:00:00+00:00'))
        self.assertEqual(due, stamp('2026-11-01T05:30:00+00:00'))
        self.assertEqual(schedule.next_after(due), stamp('2026-11-02T06:30:00+00:00'))


class ScheduledTasksTests(TestCase):
    due = stamp('2026-11-13T09:00:00+00:00')

    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.database = Path(temp.name) / 'scheduled.sqlite3'
        self.store = ScheduledTasks(self.database)

    def save(self, *, name='Report', frequency='once', message='Draft the weekly report', enabled=True, task_id=None):
        return self.store.save(name=name, message=message, profile='reports',
                               schedule=Schedule(frequency, date(2026, 11, 13), time(9), 'UTC'),
                               enabled=enabled, now=self.due - 60, task_id=task_id)

    def test_color_index_survives_rename_pause_and_reopen(self):
        first = self.save(name='Zebra')
        second = self.save(name='Apple')
        before = {task['id']: task['color_index'] for task in self.store.tasks()}
        self.assertEqual(before, {first: 0, second: 1})
        self.save(name='Aardvark', enabled=False, task_id=first)
        reopened = ScheduledTasks(self.database)
        self.assertEqual([task['id'] for task in reopened.tasks()], [first, second])
        self.assertEqual({task['id']: task['color_index'] for task in reopened.tasks()}, before)

    def test_concurrent_dispatch_claims_one_occurrence(self):
        task = self.save()
        self.assertEqual(self.store.claim_due(self.due - 1, eligible_since=self.due - 60), [])
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: self.store.claim_due(self.due, eligible_since=self.due), range(2)))
        self.assertEqual(sum(map(len, results)), 1)
        self.assertEqual(len(self.store.history(task)), 1)
        self.assertIsNone(self.store.tasks()[0]['next_at'])
        self.assertFalse(self.store.tasks()[0]['enabled'])

    def test_manual_run_keeps_schedule_and_edit_keeps_history_snapshot(self):
        task = self.save()
        first = self.store.claim_manual(task, self.due - 30)
        self.assertEqual(self.store.tasks()[0]['next_at'], self.due)
        self.store.set_session(first['id'], 'isolated-session')
        self.assertTrue(self.store.finish(first['id'], 'completed', self.due - 25))
        self.save(message='Updated message', task_id=task)
        scheduled, = self.store.claim_due(self.due, eligible_since=self.due)
        self.assertNotEqual(first['id'], scheduled['id'])
        new, old = self.store.history(task)
        self.assertEqual(new['snapshot']['message'], 'Updated message')
        self.assertEqual(old['snapshot']['message'], 'Draft the weekly report')
        self.assertEqual(old['session_id'], 'isolated-session')

    def test_pending_run_causes_skip_without_consuming_future_recurrence(self):
        task = self.save(frequency='daily')
        running = self.store.claim_manual(task, self.due - 1)
        with self.assertRaisesRegex(ValueError, 'already running'):
            self.store.claim_manual(task, self.due)
        self.assertEqual(self.store.claim_due(self.due, eligible_since=self.due), [])
        skipped, previous = self.store.history(task)
        self.assertEqual((skipped['state'], skipped['detail']), ('skipped', 'previous_run_active'))
        self.assertEqual(previous['id'], running['id'])
        self.assertEqual(self.store.tasks()[0]['next_at'], self.due + 86400)

    def test_startup_records_missed_without_replaying_interrupted_run(self):
        task = self.save(frequency='daily')
        original, = self.store.claim_due(self.due, eligible_since=self.due)
        reopened = ScheduledTasks(self.database)
        startup = self.due + 86405
        reopened.recover(startup)
        self.assertEqual(reopened.claim_due(startup, eligible_since=startup), [])
        missed, interrupted = reopened.history(task)
        self.assertEqual(missed['state'], 'missed')
        self.assertEqual(interrupted['state'], 'interrupted')
        self.assertEqual(interrupted['id'], original['id'])
        self.assertFalse(reopened.finish(original['id'], 'completed', startup))

    def test_pause_and_resume_only_considers_future_times(self):
        task = self.save(frequency='daily')
        self.store.set_enabled(task, False, self.due - 10)
        self.assertEqual(self.store.claim_due(self.due, eligible_since=self.due), [])
        self.store.set_enabled(task, True, self.due + 60)
        self.assertEqual(self.store.tasks()[0]['next_at'], self.due + 86400)
        self.assertEqual(self.store.history(task), [])

    def scoped(self, owner, *, enabled=False, task_id=None):
        return self.store.save(name='Timer', message='Check progress',
            schedule=Schedule('interval', interval_value='0.25', interval_unit='minutes', anchor_at=self.due),
            enabled=enabled, now=self.due, owner=owner, task_id=task_id)

    def test_quota_is_atomic_includes_disabled_and_is_per_conversation(self):
        def create(_):
            try:return self.scoped('one')
            except ValueError:return None
        with ThreadPoolExecutor(max_workers=8) as workers:
            created = [key for key in workers.map(create, range(8)) if key]
        self.assertEqual(len(created), 5)
        other = self.scoped('two')
        self.assertEqual(len(self.store.tasks(owner='two')), 1)
        with self.assertRaises(KeyError):self.store.delete(other, owner='one')
        with self.assertRaises(KeyError):self.store.set_enabled(other, True, self.due, owner='one')
        with self.assertRaises(KeyError):self.store.history(other, owner='one')
        with self.assertRaises(KeyError):self.scoped('one', task_id=other)
        self.store.delete(created[0], owner='one')
        self.scoped('one')
        self.assertEqual(len(self.store.tasks(owner='one')), 5)

    def test_global_visibility_quota_and_mutations_across_conversations(self):
        owner = 'session:one'
        task = self.store.save(name='Shared report', message='Report', owner=owner, source={'id':'one'},
            target='agent:'+'a'*32, schedule=Schedule('interval', interval_value='1', anchor_at=self.due),
            enabled=False, now=self.due)
        self.assertEqual([row['id'] for row in self.store.tasks(owner='session:two')], [task])
        for _ in range(4):self.scoped('session:two')
        with self.assertRaisesRegex(ValueError, '5'):self.scoped('session:two')
        # A global timer must fit every conversation, including an already full one.
        with self.assertRaisesRegex(ValueError, '5'):
            self.store.save(name='Another global', message='No room', owner=owner, target='agent:'+'b'*32,
                schedule=Schedule('interval', anchor_at=self.due), enabled=False, now=self.due)
        self.store.set_enabled(task, True, self.due, owner='session:two')
        self.assertTrue(self.store.tasks(owner=owner)[0]['enabled'])
        self.store.delete(task, owner='session:two')
        self.assertEqual(self.store.tasks(owner=owner), [])
        self.scoped('session:two')
        self.assertEqual(len(self.store.tasks(owner='session:two')), 5)

    def test_missing_global_target_pauses_without_losing_task_or_runs(self):
        task = self.store.save(name='Old report', message='Keep', owner='one', target='agent:'+'a'*32,
            schedule=Schedule('interval', interval_value='1', anchor_at=self.due), enabled=True, now=self.due)
        run = self.store.claim_manual(task, self.due, owner='two')
        self.store.finish(run['id'], 'delivered', self.due)
        self.store.reconcile_global_targets([])
        row, = self.store.tasks(owner='two')
        self.assertEqual((row['id'], row['enabled'], row['next_at'], row['target']), (task, 0, None, 'agent:'+'a'*32))
        self.assertEqual(len(self.store.history(task, owner='two')), 1)
        reopened = ScheduledTasks(self.database)
        self.assertEqual(reopened.tasks(owner='three'), [row])
        self.assertEqual(reopened.claim_due(self.due+300, eligible_since=self.due), [])

    def test_new_global_target_cannot_oversubscribe_another_full_conversation(self):
        for _ in range(5):self.scoped('full')
        with self.assertRaisesRegex(ValueError, '5'):
            self.store.save(name='Global', message='Keep every view bounded', owner='empty', target='agent:'+'a'*32,
                schedule=Schedule('interval', anchor_at=self.due), enabled=False, now=self.due)
        self.assertEqual(self.store.tasks(owner='empty'), [])

    def test_draft_promotion_preserves_quota_and_saved_source_across_restart(self):
        draft = {'token': 'draft-token', 'id': '', 'workspace': '/project'}
        owner, source = self.store.bind_session(draft)
        for _ in range(5):self.scoped(owner)
        native = {**draft, 'id': 'native-one'}
        owner, source = self.store.bind_session(native)
        reopened = ScheduledTasks(self.database)
        self.assertEqual(len(reopened.tasks(owner=owner)), 5)
        self.assertTrue(all(row['source']['id'] == 'native-one' for row in reopened.tasks(owner=owner)))
        old_owner, source = reopened.bind_session(draft)
        self.assertEqual(old_owner, owner)
        self.assertEqual(source['id'], 'native-one')
        with self.assertRaises(ValueError):self.scoped(owner)

    def test_interval_reenable_waits_a_full_period_and_backlog_is_bounded(self):
        task = self.scoped('one', enabled=True)
        first, = self.store.claim_due(self.due + 15, eligible_since=self.due)
        self.store.finish(first['id'], 'delivered', self.due + 16)
        self.store.set_enabled(task, False, self.due + 20, owner='one')
        self.store.set_enabled(task, True, self.due + 100, owner='one')
        self.assertEqual(self.store.tasks(owner='one')[0]['next_at'], self.due + 115)
        startup = self.due + 86400 * 300
        self.store.claim_due(startup, eligible_since=startup)
        self.assertGreater(self.store.tasks(owner='one')[0]['next_at'], startup)
        self.assertLessEqual(len(self.store.history(task)), 33)

    def test_delete_during_delivery_stops_future_trigger_and_keeps_receipt_history(self):
        task = self.scoped('one', enabled=True)
        run, = self.store.claim_due(self.due + 15, eligible_since=self.due)
        self.store.delete(task, owner='one')
        self.assertEqual(self.store.tasks(owner='one'), [])
        self.assertEqual(self.store.claim_due(self.due + 30, eligible_since=self.due), [])
        self.assertTrue(self.store.finish(run['id'], 'delivered', self.due + 16))
        self.assertEqual(self.store.history(task)[0]['state'], 'delivered')

    def test_reusable_slot_is_atomic_and_preserves_history_across_restart(self):
        def create(now):
            return self.store.save(name='Wake up', message='Current task', owner='one',
                schedule=Schedule.from_dict({'frequency':'once','delay_value':5,'delay_unit':'minutes'}, now=now),
                enabled=True, now=now, model_oneshot=True)
        for _ in range(4):self.scoped('one')
        key = create(self.due)
        run, = self.store.claim_due(self.due+300, eligible_since=self.due)
        self.store.finish(run['id'], 'delivered', self.due+301)
        self.store = ScheduledTasks(self.database)
        def attempt(_):
            try:return create(self.due+302)
            except ValueError:return None
        with ThreadPoolExecutor(max_workers=8) as workers:
            results = [value for value in workers.map(attempt, range(8)) if value]
        self.assertEqual(results, [key])
        self.assertEqual(len(self.store.tasks(owner='one')), 5)
        self.assertEqual(self.store.history(key)[0]['id'], run['id'])

    def test_legacy_unmarked_rows_are_migrated_without_becoming_reusable(self):
        legacy = self.database.with_name('legacy.sqlite3')
        with sqlite3.connect(legacy) as db:
            db.execute('''CREATE TABLE schedules (id TEXT PRIMARY KEY, name TEXT NOT NULL,
                message TEXT NOT NULL, profile TEXT NOT NULL, schedule TEXT NOT NULL,
                enabled INTEGER NOT NULL, next_at INTEGER)''')
            db.execute('INSERT INTO schedules VALUES (?,?,?,?,?,?,?)',
                ('legacy', 'Existing timer', 'Preserve this', '',
                 json.dumps(Schedule('once', date(2026,11,13), time(9),'UTC').serialize()), 0, None))
        migrated = ScheduledTasks(legacy)
        current = migrated.save(name='New wake-up', message='Resume', enabled=True,
            schedule=Schedule.from_dict({'frequency':'once','delay_value':5,'delay_unit':'minutes'}, now=self.due),
            now=self.due, model_oneshot=True)
        self.assertNotEqual(current, 'legacy')
        old = next(row for row in migrated.tasks() if row['id']=='legacy')
        self.assertEqual((old['message'], old['model_oneshot']), ('Preserve this', 0))
