from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase

SCRIPTS = Path(__file__).resolve().parents[1] / 'umeko-plugins/scheduled-tasks/scripts'
sys.path.insert(0, str(SCRIPTS))
from scheduled_tasks import Schedule, ScheduledTasks


def stamp(value):
    return int(datetime.fromisoformat(value).timestamp())


class CalendarTests(TestCase):
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
