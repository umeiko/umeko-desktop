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

    def test_daily_local_clock_and_persistent_unread_survive_restart(self):
        self.clock.now=datetime(2026,3,7,13,tzinfo=timezone.utc)
        self.service.assistant=lambda:'a'*32
        item=self.service.handle('createItem',{'title':'每日喝水','dueAt':'2026-03-07T09:00:00-05:00','repeat':'daily','timeZone':'America/New_York'})['item']
        self.service.start();self.clock.advance(3600);self.service.check()
        current=self.get(item)
        self.assertEqual(current['dueAt'],'2026-03-08T13:00:00Z')
        self.assertEqual((current['localTime'],current['dailyTime'],current['occurrence']),('09:00','09:00:00',2))
        self.assertEqual(len(self.service.unread_alerts()),1)
        event,=self.service.pending_notifications()
        self.assertEqual((event['agentId'],event['occurrence']),('a'*32,1))
        self.service.stop();restored=self.make();restored.start()
        self.assertEqual(len(restored.unread_alerts()),1)
        self.assertEqual(restored.pending_notifications()[0]['id'],event['id'])
        restored.acknowledge_notifications([event['id']])
        self.assertEqual(len(restored.unread_alerts()),1,'Agent delivery must not clear user unread state')
        restored.mark_viewed(item['id']);self.assertEqual(restored.unread_alerts(),[])
        self.assertEqual(restored.handle('getItem',{'id':item['id']})['item']['dueAt'],'2026-03-08T13:00:00Z')
        self.clock.advance(23*3600);restored.check()
        self.assertEqual(len(restored.unread_alerts()),1)
        self.assertEqual(restored.pending_notifications()[0]['occurrence'],2)

    def test_completed_edits_preserve_completion_but_rescheduling_rearms_after_restart(self):
        for repeat in ('once', 'daily'):
            with self.subTest(repeat=repeat):
                directory=Path(self.temp.name)/repeat
                service=self.make(directory=directory)
                service.start()
                args={'title':'已完成事项','dueAt':self.clock.at(-1),'repeat':repeat}
                if repeat=='daily':args['timeZone']='UTC'
                item=service.handle('createItem',args)['item']
                service.handle('completeItem',{'id':item['id']})
                edited=service.handle('updateItem',{'id':item['id'],'title':'编辑后','notes':'仍然完成','dueAt':item['dueAt']})['item']
                self.assertTrue(edited['completed'])
                self.assertEqual(edited['occurrence'],item['occurrence'])
                count=len(self.requests)
                service.check()
                self.assertEqual(len(self.requests),count)
                future=self.clock.at(120)
                rearmed=service.handle('updateItem',{'id':item['id'],'dueAt':future})['item']
                self.assertFalse(rearmed['completed'])
                self.assertEqual(rearmed['occurrence'],edited['occurrence']+1)
                self.assertIsNone(rearmed['firedOccurrence'])
                self.assertIsNone(rearmed['processedAt'])
                self.assertEqual(service.pending_notifications(),[])
                self.assertEqual(len(service.unread_alerts()),1)
                service.stop()
                restored=self.make(directory=directory)
                restored.start()
                self.assertFalse(self.get(item,restored)['completed'])
                self.assertEqual(len(self.requests),count)
                self.clock.advance(120);restored.check()
                self.assertEqual(len(self.requests),count+1)
                restored.check()
                self.assertEqual(len(self.requests),count+1)
                self.assertEqual(restored.pending_notifications()[0]['occurrence'],rearmed['occurrence'])
                restored.stop()

    def test_restore_overdue_is_quiet_idempotent_and_durable(self):
        self.service.start()
        item=self.create(60)
        self.service.handle('completeItem',{'id':item['id']})
        self.clock.advance(120)
        restored=self.service.handle('completeItem',{'id':item['id'],'completed':False})['item']
        self.assertFalse(restored['completed']);self.assertTrue(restored['overdue'])
        self.assertEqual(restored['dueAt'],item['dueAt'])
        self.assertEqual(restored['notificationOutcome'],'restored_overdue')
        self.assertEqual(self.requests,[]);self.assertEqual(self.service.unread_alerts(),[])
        self.assertEqual(self.service.pending_notifications(),[])
        self.assertEqual(self.service.handle('completeItem',{'id':item['id'],'completed':False})['item']['revision'],restored['revision'])
        self.service.stop();reloaded=self.make();reloaded.start()
        self.assertFalse(self.get(item,reloaded)['completed']);self.assertEqual(self.requests,[])

    def test_restore_future_resumes_original_timer_and_processed_restore_does_not_replay(self):
        self.service.start();item=self.create(120)
        self.service.handle('completeItem',{'id':item['id']});self.clock.advance(60)
        current=self.service.handle('completeItem',{'id':item['id'],'completed':False})['item']
        self.assertEqual(current['occurrence'],item['occurrence']);self.assertFalse(current['overdue'])
        self.clock.advance(60);self.service.check();self.assertEqual(len(self.requests),1)
        fired=self.get(item)
        self.service.handle('completeItem',{'id':item['id']})
        current=self.service.handle('completeItem',{'id':item['id'],'completed':False})['item']
        self.assertEqual(current['processedAt'],fired['processedAt'])
        self.assertEqual(current['notificationOutcome'],fired['notificationOutcome'])
        self.assertEqual(len(self.requests),1)

    def test_restore_daily_skips_missed_alert_and_resumes_next_calendar_day(self):
        self.service.start()
        item=self.service.handle('createItem',{'title':'每日','repeat':'daily','timeZone':'UTC','dueAt':self.clock.at(60)})['item']
        self.service.handle('completeItem',{'id':item['id']});self.clock.advance(120)
        current=self.service.handle('completeItem',{'id':item['id'],'completed':False})['item']
        self.assertFalse(current['completed']);self.assertGreater(current['dueAt'],self.clock.at(0).replace('+00:00','Z'))
        self.assertEqual(current['occurrence'],2);self.assertEqual(self.requests,[])
        self.clock.advance(86400);self.service.check();self.assertEqual(len(self.requests),1)

    def test_failed_completed_reschedule_does_not_reopen_or_replace_history(self):
        self.service.start()
        item=self.create(-1)
        self.service.handle('completeItem',{'id':item['id']})
        before=self.disk()
        with patch.object(self.service,'_write',side_effect=OSError('read-only')):
            with self.assertRaises(ValueError):self.update(item,dueAt=self.clock.at(120))
        self.assertEqual(self.disk(),before)
        with patch.object(self.service,'_write',side_effect=OSError('read-only')):
            with self.assertRaises(ValueError):self.service.handle('completeItem',{'id':item['id'],'completed':False})
        self.assertEqual(self.disk(),before)
        self.assertTrue(self.get(item)['completed'])
        self.assertIsNone(self.service.summary()['nextDueAt'])
        # Removing a completed reminder's time is a content edit, not rearming.
        self.assertTrue(self.update(item,clearDueAt=True)['completed'])

    def test_clear_completed_is_atomic_and_keeps_open_items_and_unread(self):
        self.service.start()
        due=self.create(-1);open_item=self.create(60)
        self.service.handle('completeItem',{'id':due['id']})
        completed=self.create();self.service.handle('completeItem',{'id':completed['id']})
        before=self.disk()
        with patch.object(self.service,'_write',side_effect=OSError('write failed')):
            with self.assertRaises(ValueError):self.service.handle('clearCompleted',{})
        self.assertEqual(self.disk(),before)
        self.assertEqual(len(self.service.handle('listItems',{'status':'all'})['items']),3)
        self.assertEqual(self.service.handle('clearCompleted',{}),{'deletedCount':2})
        self.assertEqual([item['id'] for item in self.service.handle('listItems',{'status':'all'})['items']],[open_item['id']])
        self.assertEqual(len(self.service.unread_alerts()),1)
        self.assertEqual(self.service.handle('clearCompleted',{}),{'deletedCount':0})
        restored=self.make()
        self.assertEqual([item['id'] for item in restored.handle('listItems',{})['items']],[open_item['id']])
        with self.assertRaises(ValueError):restored.handle('clearCompleted',{'status':'all'})

    def test_daily_dst_gap_fold_and_long_sleep_do_not_burst(self):
        from app.pet_reminders import _next_daily
        item={'dueAt':'2026-03-07T07:30:00Z','timeZone':'America/New_York','dailyTime':'02:30:00'}
        self.assertEqual(_next_daily(item,datetime(2026,3,7,8,tzinfo=timezone.utc)),datetime(2026,3,8,7,tzinfo=timezone.utc))
        item.update(dueAt='2026-10-31T05:30:00Z',dailyTime='01:30:00')
        first=_next_daily(item,datetime(2026,10,31,6,tzinfo=timezone.utc))
        self.assertEqual(first,datetime(2026,11,1,5,30,tzinfo=timezone.utc))
        item['dueAt']=first.isoformat()
        self.assertEqual(_next_daily(item,first),datetime(2026,11,2,6,30,tzinfo=timezone.utc))
        self.service.start();daily=self.service.handle('createItem',{'title':'Daily','dueAt':self.clock.at(60),'repeat':'daily','timeZone':'UTC'})['item']
        self.clock.advance(10*86400+120);self.service.check()
        self.assertEqual(len(self.requests),1)
        self.assertEqual(self.get(daily)['occurrence'],2)
        self.assertGreater(datetime.fromisoformat(self.get(daily)['dueAt'].replace('Z','+00:00')),self.clock.now)

    def test_legacy_data_migrates_and_crash_claim_recovers_daily_schedule(self):
        item=self.create(60);legacy=self.disk();legacy['schemaVersion']=1;legacy.pop('notifications',None);legacy.pop('alerts',None)
        for row in legacy['items']:
            for key in ('repeat','timeZone','dailyTime','agentId'):row.pop(key)
        self.service.path.write_text(json.dumps(legacy))
        restored=self.make();self.assertEqual(restored.handle('getItem',{'id':item['id']})['item']['repeat'],'once')
        daily=restored.handle('createItem',{'title':'Daily','dueAt':self.clock.at(60),'repeat':'daily','timeZone':'UTC'})['item']
        saved=json.loads(restored.path.read_text());row=next(v for v in saved['items'] if v['id']==daily['id'])
        row.update(firedOccurrence=row['occurrence'],processedAt=self.clock.at(60).replace('+00:00','Z'),notificationOutcome='claimed')
        restored.path.write_text(json.dumps(saved));restored.stop()
        self.clock.advance(60);again=self.make();again.start()
        self.assertEqual(again.handle('getItem',{'id':daily['id']})['item']['occurrence'],2)

    def test_unread_is_not_cleared_by_completion_or_elapsed_time(self):
        self.service.start();item=self.create(0)
        self.assertEqual(len(self.service.unread_alerts()),1)
        self.clock.advance(9*3600);self.service.check()
        self.service.handle('completeItem',{'id':item['id']})
        self.assertEqual(len(self.service.unread_alerts()),1)
        self.service.mark_viewed(item['id']);self.assertEqual(self.service.unread_alerts(),[])

    def test_daily_and_local_picker_validation(self):
        with self.assertRaises(ValueError):self.service.handle('createItem',{'title':'Missing time','repeat':'daily'})
        gap=self.service.resolve_local_time({'date':'2026-03-08','time':'02:30','timeZone':'America/New_York'})
        self.assertEqual(gap['candidates'],[])
        fold=self.service.resolve_local_time({'date':'2026-11-01','time':'01:30','timeZone':'America/New_York'})
        self.assertEqual([v['label'] for v in fold['candidates']],['UTC-04:00','UTC-05:00'])
        self.assertEqual(self.service.resolve_local_time({'date':'2026-02-30','time':'09:00','timeZone':'UTC'})['candidates'],[])

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
        self.assertEqual(self.service.summary(), {'openCount': 1, 'overdueCount': 1, 'nextDueAt': None, 'unreadCount':1, 'error': ''})

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

        def interrupted(items,notifications=None,alerts=None):
            original_write(items,notifications,alerts)
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

        def record(items,notifications=None,alerts=None):
            snapshots.append(copy.deepcopy(items))
            original(items,notifications,alerts)

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

        def write(items,notifications=None,alerts=None):
            calls.append(items)
            if len(calls) == 2:
                raise OSError('second write failed')
            original(items,notifications,alerts)

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
                 ('completeItem', {'id': True}),
                 ('completeItem', {'id': item['id'], 'completed': 'false'}),
                 ('completeItem', {'id': item['id'], 'completed': 0}),
                 ('completeItem', {'id': item['id'], 'completed': None}), ('getItem', {'id': 'bad'}),
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
