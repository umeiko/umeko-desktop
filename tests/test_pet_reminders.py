"""Offline reminder regressions with an injected wall clock and timer queue."""
import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication

from app.pet_reminders import PetReminders


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 2, 8, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)

    def at(self, seconds):
        return (self.now + timedelta(seconds=seconds)).isoformat()


class TimerHandle:
    def __init__(self, milliseconds, callback):
        self.milliseconds = milliseconds
        self.callback = callback
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def fire(self):
        # Deliberately allow an already queued, cancelled callback to run.
        self.callback()


class Timer:
    def __init__(self):
        self.handles = []

    def call_later(self, milliseconds, callback):
        handle = TimerHandle(milliseconds, callback)
        self.handles.append(handle)
        return handle

    @property
    def latest(self):
        return self.handles[-1]


class ReminderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'profile' / 'desktop-plugins' / 'state' / 'desktop-pet'
        self.clock = Clock()
        self.timer = Timer()
        self.visible = True
        self.enabled = True
        self.requests = []
        self.service = self.make()

    def make(self, directory=None, timer=None):
        service = PetReminders(directory or self.directory, clock=self.clock,
                               timer=timer or self.timer, visible=lambda: self.visible,
                               notifications=lambda: self.enabled)
        service.due.connect(lambda items: self.requests.append(copy.deepcopy(items)))
        self.addCleanup(service.close)
        return service

    def create(self, seconds=None, title='取快递', notes='', service=None):
        args = {'title': title, 'notes': notes}
        if seconds is not None:
            args['dueAt'] = self.clock.at(seconds)
        return (service or self.service).handle('createItem', args)['item']

    def get(self, item, service=None):
        return (service or self.service).handle('getItem', {'id': item['id']})['item']

    def update(self, item, **args):
        return self.service.handle('updateItem', {'id': item['id'], **args})['item']

    def disk(self):
        return json.loads(self.service.path.read_text(encoding='utf-8'))

    def test_offline_crud_roundtrip_plain_text_and_result_isolation(self):
        with patch('socket.create_connection', side_effect=AssertionError('network access')):
            self.service.start()
            item = self.create(title='  <b>取快递</b>  ', notes='<script>plain text</script>')
            self.assertEqual(item['title'], '<b>取快递</b>')
            self.assertIsNone(item['dueAt'])
            self.assertEqual(item['occurrence'], 0)
            self.assertEqual(self.timer.handles, [])
            item['title'] = 'caller mutation'
            original = self.get(item)
            self.assertEqual(original['title'], '<b>取快递</b>')
            edited = self.update(item, title='收快递', notes='带取件码')
            self.assertEqual(edited['revision'], 2)
            self.assertEqual(edited['occurrence'], 0)
            self.assertEqual(self.disk()['items'][0]['notes'], '带取件码')
            completed = self.service.handle('completeItem', {'id': item['id']})['item']
            self.assertTrue(completed['completed'])
            self.assertEqual(self.service.handle('completeItem', {'id': item['id']})['item'], completed)
            self.assertEqual(self.service.handle('listItems', {})['items'], [])
            self.assertEqual(len(self.service.handle('listItems', {'status': 'completed'})['items']), 1)
            self.assertEqual(self.service.handle('deleteItem', {'id': item['id']}), {'deletedId': item['id']})
            self.assertEqual(self.disk()['items'], [])
            self.assertEqual(self.requests, [])

    def test_normal_due_once_and_processing_is_durable_before_emit(self):
        item = self.create(5)
        at_emit = []
        self.service.due.connect(lambda _: at_emit.append(self.disk()['items'][0]))
        self.service.start()
        self.assertEqual(self.timer.latest.milliseconds, 5000)
        old = self.timer.latest
        self.clock.advance(4)
        old.fire()
        self.assertEqual(self.requests, [])
        self.clock.advance(1)
        self.timer.latest.fire()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(at_emit[0]['notificationOutcome'], 'presentation_requested')
        self.assertEqual(at_emit[0]['firedOccurrence'], 1)
        self.assertFalse(at_emit[0]['completed'])
        old.fire()
        self.service.check()
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(self.get(item)['overdue'])
        self.assertEqual(self.service.summary(), {'openCount': 1, 'overdueCount': 1, 'nextDueAt': None, 'error': ''})

    def test_restart_collects_missed_items_once_and_does_not_repeat_processed_items(self):
        first = self.create(2)
        second = self.create(4)
        self.service.close()
        self.clock.advance(10)
        recovered = self.make(timer=Timer())
        recovered.start()
        self.assertEqual({row['id'] for row in self.requests[0]}, {first['id'], second['id']})
        self.assertEqual(len(self.requests), 1)
        recovered.close()
        again = self.make(timer=Timer())
        again.start()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(again.summary()['overdueCount'], 2)

    def test_crash_after_claim_before_presentation_does_not_replay(self):
        self.create(0)
        original_write = self.service._write

        class SimulatedCrash(BaseException):
            pass

        def interrupted(items):
            original_write(items)
            raise SimulatedCrash()

        with patch.object(self.service, '_write', interrupted):
            with self.assertRaises(SimulatedCrash):
                self.service.start()
        self.assertEqual(self.disk()['items'][0]['notificationOutcome'], 'claimed')
        self.assertEqual(self.requests, [])
        self.service.close()
        recovered = self.make(timer=Timer())
        recovered.start()
        self.assertEqual(self.requests, [])
        self.assertEqual(recovered.summary()['openCount'], 1)
        self.assertEqual(recovered.summary()['overdueCount'], 1)

    def test_sleep_forward_backward_clock_and_sixty_second_ceiling(self):
        first = self.create(120)
        second = self.create(180)
        self.service.start()
        self.assertEqual(self.timer.latest.milliseconds, 60000)
        self.clock.advance(-300)
        self.timer.latest.fire()
        self.assertEqual(self.timer.latest.milliseconds, 60000)
        self.clock.advance(600)
        self.timer.latest.fire()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual([row['id'] for row in self.requests[0]], [first['id'], second['id']])
        self.clock.advance(-600)
        self.service.check()
        self.clock.advance(600)
        self.service.check()
        self.assertEqual(len(self.requests), 1)

    def test_reschedule_invalidates_queued_callback_and_past_time_fires_once(self):
        item = self.create(5)
        self.service.start()
        old = self.timer.latest
        changed = self.update(item, dueAt=self.clock.at(20))
        self.assertEqual(changed['occurrence'], 2)
        self.assertTrue(old.cancelled)
        self.clock.advance(5)
        old.fire()
        self.assertEqual(self.requests, [])
        self.clock.advance(15)
        self.timer.latest.fire()
        self.assertEqual(len(self.requests), 1)
        changed = self.update(item, dueAt=self.clock.at(-2))
        self.assertEqual(changed['occurrence'], 3)
        self.assertEqual(len(self.requests), 2)
        self.service.check()
        self.assertEqual(len(self.requests), 2)

    def test_text_edit_keeps_processed_occurrence_and_equivalent_offsets_are_noop(self):
        item = self.create(0)
        self.service.start()
        first = self.get(item)
        edited = self.update(item, title='改标题', notes='新备注')
        self.assertEqual(edited['revision'], first['revision'] + 1)
        self.assertEqual(edited['occurrence'], first['occurrence'])
        self.assertEqual(edited['firedOccurrence'], first['firedOccurrence'])
        self.assertEqual(edited['processedAt'], first['processedAt'])
        same = self.update(item, dueAt='2026-11-02T16:00:00+08:00')
        self.assertEqual(same, edited)
        self.assertEqual(len(self.requests), 1)

    def test_clear_time_and_first_set_of_time(self):
        item = self.create()
        first = self.update(item, dueAt=self.clock.at(2))
        self.assertEqual(first['occurrence'], 1)
        self.service.start()
        old = self.timer.latest
        cleared = self.update(item, dueAt=None)
        self.assertEqual(cleared['occurrence'], 2)
        self.assertIsNone(cleared['firedOccurrence'])
        self.clock.advance(3)
        old.fire()
        self.service.check()
        self.assertEqual(self.requests, [])
        self.assertIsNone(self.service.summary()['nextDueAt'])

    def test_completion_and_deletion_cancel_pending_callbacks(self):
        first = self.create(2)
        second = self.create(2)
        self.service.start()
        old = self.timer.latest
        self.service.handle('completeItem', {'id': first['id']})
        self.service.handle('deleteItem', {'id': second['id']})
        self.clock.advance(3)
        old.fire()
        self.service.check()
        self.assertEqual(self.requests, [])
        self.assertEqual(self.service.summary()['openCount'], 0)
        self.assertEqual(len(self.disk()['items']), 1)

    def test_clear_due_at_alias_for_existing_widget_schema(self):
        item = self.create(10)
        cleared = self.service.handle('updateItem', {'id': item['id'], 'clearDueAt': True})['item']
        self.assertIsNone(cleared['dueAt'])
        self.assertEqual(cleared['occurrence'], 2)
        for args in ({'clearDueAt': 1}, {'clearDueAt': True, 'dueAt': self.clock.at(10)},
                     {'clearDueAt': False}):
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    self.service.handle('updateItem', {'id': item['id'], **args})

    def test_hidden_and_preference_off_record_distinct_outcomes_without_replay(self):
        self.visible = False
        hidden = self.create(0)
        self.service.start()
        self.assertEqual(self.get(hidden)['notificationOutcome'], 'suppressed_hidden')
        self.visible = True
        self.service.check()
        self.enabled = False
        disabled = self.create(0)
        self.assertEqual(self.get(disabled)['notificationOutcome'], 'suppressed_preference')
        self.enabled = True
        self.service.check()
        self.service.close()
        recovered = self.make(timer=Timer())
        recovered.start()
        self.assertEqual(self.requests, [])
        self.assertEqual(recovered.summary()['overdueCount'], 2)

    def test_stop_ignores_queued_callback_and_enable_recovers_once(self):
        self.create(2)
        self.service.start()
        old = self.timer.latest
        self.service.stop()
        self.assertTrue(old.cancelled)
        self.clock.advance(5)
        old.fire()
        self.service.check()
        self.assertEqual(self.requests, [])
        self.service.start()
        self.assertEqual(len(self.requests), 1)
        self.service.close()
        self.service.start()
        self.assertFalse(self.service.running)

    def test_batch_is_claimed_in_one_snapshot_then_one_presentation_request(self):
        later = self.create(2, title='later')
        first = self.create(1, title='first')
        original = self.service._write
        snapshots = []

        def record(items):
            snapshots.append(copy.deepcopy(items))
            original(items)

        self.clock.advance(3)
        with patch.object(self.service, '_write', record):
            self.service.start()
        self.assertEqual(len(snapshots), 2)
        self.assertTrue(all(row['notificationOutcome'] == 'claimed' for row in snapshots[0]))
        self.assertTrue(all(row['notificationOutcome'] == 'presentation_requested' for row in snapshots[1]))
        self.assertEqual([row['id'] for row in self.requests[0]], [first['id'], later['id']])

    def test_failed_edit_retains_original_state_file_and_timer(self):
        item = self.create(5)
        self.service.start()
        old = self.timer.latest
        before = self.service.path.read_text(encoding='utf-8')
        with patch('app.pet_reminders.os.replace', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(ValueError, 'disk full'):
                self.update(item, title='must not publish', dueAt=self.clock.at(10))
        self.assertEqual(self.get(item)['revision'], 1)
        self.assertEqual(self.service.path.read_text(encoding='utf-8'), before)
        self.assertFalse(old.cancelled)
        self.assertIn('disk full', self.service.summary()['error'])
        self.assertEqual(list(self.directory.glob('.reminders-*.tmp')), [])
        self.clock.advance(5)
        old.fire()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0][0]['title'], item['title'])

    def test_due_write_failure_pauses_without_display_then_successful_edit_recovers(self):
        item = self.create(2)
        self.service.start()
        old = self.timer.latest
        self.clock.advance(2)
        with patch.object(self.service, '_write', side_effect=OSError('read-only')) as write:
            old.fire()
            self.service.check()
            self.assertEqual(write.call_count, 1)
        self.assertEqual(self.requests, [])
        self.assertIsNone(self.get(item)['firedOccurrence'])
        self.assertIn('read-only', self.service.summary()['error'])
        self.update(item, title='retry after successful write')
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.service.summary()['error'], '')

    def test_presentation_metadata_failure_preserves_claim_and_does_not_replay(self):
        self.create(0)
        original = self.service._write
        calls = []

        def write(items):
            calls.append(items)
            if len(calls) == 2:
                raise OSError('second write failed')
            original(items)

        with patch.object(self.service, '_write', write):
            self.service.start()
        self.assertEqual(self.requests, [])
        self.assertEqual(self.disk()['items'][0]['notificationOutcome'], 'claimed')
        self.service.close()
        recovered = self.make(timer=Timer())
        recovered.start()
        self.assertEqual(self.requests, [])

    def test_fsync_failure_does_not_publish_or_leave_temp_file(self):
        with patch('app.pet_reminders.os.fsync', side_effect=OSError('sync failed')):
            with self.assertRaisesRegex(ValueError, 'sync failed'):
                self.create()
        self.assertFalse(self.service.path.exists())
        self.assertEqual(self.service.handle('listItems', {})['items'], [])
        self.assertEqual(list(self.directory.glob('.reminders-*.tmp')), [])

    def test_invalid_file_or_version_is_preserved_and_writes_are_refused(self):
        self.directory.mkdir(parents=True)
        for content in ('{broken', '{"schemaVersion": 2, "items": []}',
                        '{"schemaVersion": true, "items": []}',
                        '{"schemaVersion": 1, "items": [{}]}'):
            with self.subTest(content=content):
                self.service.path.write_text(content, encoding='utf-8')
                invalid = self.make(timer=Timer())
                invalid.start()
                self.assertIn('Cannot load', invalid.summary()['error'])
                with self.assertRaises(ValueError):
                    self.create(service=invalid)
                self.assertEqual(self.service.path.read_text(encoding='utf-8'), content)
                invalid.close()

    def test_load_io_and_non_utf8_errors_are_exposed(self):
        self.directory.mkdir(parents=True)
        self.service.path.write_bytes(b'\xff')
        invalid = self.make(timer=Timer())
        self.assertIn('Cannot load', invalid.summary()['error'])
        with patch.object(Path, 'read_text', side_effect=PermissionError('denied')):
            denied = self.make(timer=Timer())
        self.assertIn('denied', denied.summary()['error'])

    def test_stored_field_validation_and_duplicate_ids(self):
        self.create(10)
        good = self.disk()
        changes = ({'completed': 0}, {'revision': True}, {'occurrence': 0},
                   {'firedOccurrence': 5}, {'notificationOutcome': 'seen'},
                   {'dueAt': '2026-11-02T08:00:10'}, {'id': 'not-a-uuid'})
        for change in changes:
            value = copy.deepcopy(good)
            value['items'][0].update(change)
            with self.subTest(change=change):
                self.service.path.write_text(json.dumps(value), encoding='utf-8')
                invalid = self.make(timer=Timer())
                self.assertTrue(invalid.summary()['error'])
        good['items'].append(copy.deepcopy(good['items'][0]))
        self.service.path.write_text(json.dumps(good), encoding='utf-8')
        duplicate = self.make(timer=Timer())
        self.assertIn('Duplicate', duplicate.summary()['error'])

    def test_strict_rpc_parameters_dates_and_nonexistent_ids(self):
        item = self.create(5)
        self.service.start()
        old = self.timer.latest
        cases = [('noSuchMethod', {}), ('listItems', []), ('listItems', {'status': None}),
                 ('listItems', {'status': 'bad'}), ('listItems', {'unexpected': True}),
                 ('createItem', {}), ('createItem', {'title': ' '}),
                 ('createItem', {'title': 'a' * 201}), ('createItem', {'title': 123}),
                 ('createItem', {'title': 'ok', 'notes': None}),
                 ('createItem', {'title': 'ok', 'notes': 'a' * 2001}),
                 ('createItem', {'title': 'ok', 'completed': True}),
                 ('updateItem', {'id': item['id']}),
                 ('updateItem', {'id': item['id'], 'revision': 10}),
                 ('completeItem', {'id': True}), ('getItem', {'id': 'bad'}),
                 ('deleteItem', {'id': '00000000-0000-0000-0000-000000000000'})]
        for value in (False, 1, [], '2026-11-02T08:00:00', '2026-02-30T08:00:00Z',
                      '2026-11-02T08:00:00+24:00', '2026-11-02T08:00:00+01:60'):
            cases.append(('createItem', {'title': 'ok', 'dueAt': value}))
        for method, args in cases:
            with self.subTest(method=method, args=args):
                with self.assertRaises(ValueError):
                    self.service.handle(method, args)
        self.assertIs(self.timer.latest, old)
        self.assertFalse(old.cancelled)
        self.assertEqual(len(self.disk()['items']), 1)

    def test_profile_isolation_ordering_summary_and_host_local_time(self):
        plain = self.create(title='plain')
        future = self.create(20, title='future')
        overdue = self.create(-10, title='overdue')
        another = self.make(directory=Path(self.temp.name) / 'second-profile', timer=Timer())
        self.assertEqual(another.summary()['openCount'], 0)
        self.create(title='other profile', service=another)
        result = self.service.handle('listItems', {})
        self.assertEqual([row['id'] for row in result['items']], [overdue['id'], future['id'], plain['id']])
        self.assertEqual(result['now'], '2026-11-02T08:00:00Z')
        self.assertEqual(datetime.fromisoformat(result['localNow']), self.clock.now.astimezone())
        self.assertEqual(self.service.summary()['nextDueAt'], overdue['dueAt'])
        self.assertEqual(self.service.summary()['overdueCount'], 1)

    def test_offset_normalization_keeps_absolute_time_across_dst_offsets(self):
        item = self.service.handle('createItem', {'title': 'DST occurrence',
                         'dueAt': '2026-11-01T01:30:00-07:00'})['item']
        same = self.update(item, dueAt='2026-11-01T08:30:00Z')
        self.assertEqual(same['revision'], 1)
        later = self.update(item, dueAt='2026-11-01T01:30:00-08:00')
        self.assertEqual(later['dueAt'], '2026-11-01T09:30:00Z')
        self.assertEqual(later['occurrence'], 2)


if __name__ == '__main__':
    unittest.main()
