"""Binding identity, legacy packs, completion delivery and host speech budgets."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QImage
from app.desktop_plugins import DesktopPlugins
from app.pi_sessions import SessionState
from app.pet_packs import read_pack, import_pack
from app.controller_runtime import PiControllerMixin
from tests.test_desktop_plugins import Host


class PetAssistantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.host = Host(Path(self.temp.name))
        self.host.gateway = SimpleNamespace(models=lambda:[{'id':'fixture-model'}])
        self.host._pool.retire = Mock()
        self.host._command_pi = Mock(return_value=True)
        settings = self.host.store.directory / 'desktop-plugins/settings.json'
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({'config': {'desktop-pet': {'visible': False}}}), encoding='utf-8')
        self.manager = DesktopPlugins(self.host); self.addCleanup(self.manager.close)
        self.host._desktop_plugins = self.manager
        self.pet, self.bus = self.manager.pet, self.manager.global_agents
        self.helper = self.pet.assistant
        self.now = 1000.
        self.helper.clock = lambda:self.now
        self.speech = []; self.pet.assistantSpeech.connect(self.speech.append)

    def bind(self):
        self.pet.configure({'visible':True})
        identifier = self.helper.identifier
        record = SessionState(global_agent=identifier, title='悬浮小助手', model='fixture-model')
        self.bus.records[identifier] = record
        self.host._pool.records[record.key] = record
        return record

    def speak(self, record, text='任务完成啦。', binding=None):
        return self.helper.send(record, {'text':text, 'binding':self.helper.binding if binding is None else binding})

    def test_binding_is_idempotent_durable_and_never_claims_a_user_namesake(self):
        namesake = 'a'*32
        self.bus.agents[namesake] = {'id':namesake,'name':'悬浮小助手','character':'yanami','model':'fixture-model'}
        self.pet.configure({'visible':True})
        identifier = self.helper.identifier
        self.assertNotEqual(identifier, namesake)
        self.assertEqual(self.bus.agents[identifier]['managedBy'], 'desktop-pet')
        for _ in range(10): self.helper.reconcile()
        self.assertEqual(len(self.bus.agents), 2)
        self.assertEqual(json.loads(self.bus.registry.read_text())['petAssistantId'], identifier)
        self.pet.configure({'visible':False}); self.assertFalse(self.helper.binding)
        self.pet.configure({'visible':True}); self.assertEqual(self.helper.identifier, identifier)
        self.assertFalse(self.bus.bridges, 'Creating a companion must not connect any project')
        self.manager.close()
        restored = DesktopPlugins(self.host); self.addCleanup(restored.close)
        restored.pet.assistant.reconcile()
        self.assertEqual(restored.pet.assistant.identifier, identifier)
        self.assertEqual(len(restored.global_agents.agents), 2)

    def test_capacity_error_preserves_existing_agents(self):
        self.bus.agents = {f'{i:032x}':{'id':f'{i:032x}','name':str(i)} for i in range(16)}
        self.pet.configure({'visible':True})
        self.assertFalse(self.helper.identifier)
        self.assertIn('16', self.helper.error)
        self.assertEqual(len(self.bus.agents), 16)

    def test_pet_task_targets_bound_agent_without_changing_visible_conversation(self):
        record = self.bind()
        self.bus.selected_conversation = 'another-agent'
        visible = self.host._view
        self.assertEqual(self.pet.sendTask('  检查当前任务  ', record.global_agent),
                         {'ok': True, 'status': 'accepted'})
        self.host._command_pi.assert_called_once_with('prompt', record, text='(input from pet)\n检查当前任务')
        self.assertEqual(record.messages[0], {'role':'user', 'text':'(input from pet)\n检查当前任务'})
        self.assertIs(self.host._view, visible)
        self.assertEqual(self.bus.selected_conversation, 'another-agent')

    def test_pet_task_uses_existing_busy_agent_queue(self):
        record = self.bind(); record.busy = True; record.ready = True
        self.assertEqual(self.pet.sendTask('继续检查', record.global_agent),
                         {'ok':True, 'status':'queued'})
        self.assertEqual(self.host._pool.writes[-1],
                         (record.key, {'type':'steer', 'text':'(input from pet)\n继续检查'}))
        self.host._command_pi.assert_not_called()

    def test_pet_task_never_creates_or_retargets_an_unbound_agent(self):
        self.assertEqual(self.pet.sendTask('检查', '')['status'], 'unavailable')
        self.assertFalse(self.bus.agents)
        record = self.bind()
        self.assertEqual(self.pet.sendTask('检查', 'another-agent')['status'], 'binding_changed')
        self.bus.agents.pop(record.global_agent)
        self.assertFalse(self.pet.assistantStatus['bound'])
        self.assertEqual(self.pet.sendTask('检查', record.global_agent)['status'], 'unavailable')
        self.host._command_pi.assert_not_called()

    def test_pet_task_rejects_empty_overlong_disabled_and_loading_input(self):
        record = self.bind()
        for text in ('', ' \n ', 'x'*16001):
            self.assertEqual(self.pet.sendTask(text, record.global_agent)['status'], 'invalid_text')
        record.busy = True; record.ready = False
        result = self.pet.sendTask('保留草稿', record.global_agent)
        self.assertFalse(result['ok']); self.assertIn('正在加载', result['error'])
        self.manager.setEnabled('global-agents', False)
        self.assertEqual(self.pet.sendTask('检查', record.global_agent)['status'], 'unavailable')
        self.host._command_pi.assert_not_called()

    def test_failed_pet_task_rolls_back_optimistic_messages(self):
        record = self.bind(); record.messages = [{'role':'user', 'text':'原有历史'}]
        self.host._command_pi.return_value = False
        result = self.pet.sendTask('检查', record.global_agent)
        self.assertFalse(result['ok']); self.assertIn('启动失败', result['error'])
        self.assertEqual(record.messages, [{'role':'user', 'text':'原有历史'}])

    def test_persona_changes_invalidate_old_tool_binding_and_keep_user_preferences(self):
        record = self.bind(); old = self.helper.binding
        self.assertIn('八奈见', self.helper.prompt(record))
        self.pet.handle('setPersona', {'id':'yanami','persona':'沉静，用一句话报告。'})
        self.assertNotEqual(old, self.helper.binding)
        self.assertTrue(record.stale)
        self.assertIn('沉静，用一句话报告。', self.bus.prompt(record))
        self.assertNotIn('开朗俏皮', self.bus.prompt(record))
        self.assertEqual(self.speak(record, binding=old)['status'], 'binding_changed')
        self.pet.handle('setPersona', {'id':'yanami','persona':''})
        self.assertEqual(self.pet.status()['persona'], '')
        self.pet.handle('setPersona', {'id':'yanami','reset':True})
        self.assertIn('八奈见', self.pet.status()['persona'])
        self.pet.configure({'appearance':'komari'})
        self.assertIn('小鞠', self.helper.prompt(record))
        self.assertNotIn('八奈见', self.helper.prompt(record))
        self.assertEqual(self.helper.identifier, record.global_agent)

    def test_legacy_pack_without_persona_imports_and_all_builtins_have_short_defaults(self):
        folder = Path(self.temp.name)/'legacy'; folder.mkdir()
        image = QImage(4,4,QImage.Format_ARGB32);image.fill(0);self.assertTrue(image.save(str(folder/'idle.png')))
        data = {'format':'umeko-pet','version':1,'id':'legacy','name':'Legacy','states':{'idle':'idle.png'}}
        (folder/'pet.json').write_text(json.dumps(data))
        self.assertNotIn('persona', import_pack(folder/'pet.json', Path(self.temp.name)/'installed'))
        for identifier, pack in self.pet._packs.items():
            self.assertTrue(0 < len(pack['persona']) < 200, identifier)
        data['persona'] = ['invalid'];(folder/'pet.json').write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'persona'): read_pack(folder)

    def test_speech_has_no_frequency_quota_and_still_enforces_identity(self):
        record = self.bind()
        self.assertTrue(self.speak(record)['ok'])
        self.assertTrue(self.speak(record, '第二条')['ok'])
        for _ in range(100): self.assertTrue(self.speak(record)['ok'])
        self.assertEqual(len(self.spoken_text()),102)
        self.pet.configure({'appearance':'komari'})
        self.assertTrue(self.speak(record, '第三条')['ok'])
        other = SessionState(global_agent=record.global_agent)
        self.assertEqual(self.speak(other)['status'], 'unavailable')
        self.assertEqual(self.speak(self.host._view)['status'], 'unavailable')
        self.pet.configure({'visible':False})
        self.assertEqual(self.speak(record)['status'], 'unavailable')

    def test_pet_source_marker_keeps_input_limit_and_leaves_normal_chat_unchanged(self):
        record=self.bind();text='字'*16000
        self.assertTrue(self.pet.sendTask(text,record.global_agent)['ok'])
        self.assertEqual(self.host._command_pi.call_args.kwargs['text'],'(input from pet)\n'+text)
        self.bus.handle('send',{'id':record.global_agent,'text':'普通聊天'})
        self.assertEqual(self.host._command_pi.call_args.kwargs['text'],'普通聊天')

    def test_reading_duration_tracks_text_and_visible_graphemes(self):
        record=self.bind()
        for text,duration in [('Done.',1800),('One two three.',1978),('字'*30,5200),('字'*80,12200),('👩‍💻'*80,12200)]:
            self.assertEqual(self.pet.speechDuration(text),duration,text)
            self.assertEqual(self.speak(record,text)['reading_ms'],duration)

    def test_pet_timer_capture_and_delivery_are_bound_to_itself_after_restart(self):
        record = self.bind()
        host = self.manager._host_services.scheduled_service()
        source = host.capture(self.manager.bridge.snapshot(record))
        target = 'agent:' + record.global_agent
        self.assertEqual([row['id'] for row in source['timerTargets']], [target])
        self.assertEqual(source['timerOwnerTarget'], target)
        self.assertTrue(self.helper.allows_timer(record, 'widgets.docs', {'id':'scheduled-tasks'}))
        self.assertFalse(self.helper.allows_timer(record, 'widgets.call', {'id':'desktop-pet'}))
        request = {'widget':'scheduled-tasks','operation':'scheduledTasks.trigger','page':False,
                   'session':source,'arguments':{'run_id':'d'*32,'target':target,'text':'喝水时间到了'}}
        result = host.request(request)
        self.assertEqual(result['state'], 'queued')
        self.assertEqual(result['source']['timerAgentId'], record.global_agent)
        self.host._command_pi.assert_called_once()
        args, kwargs = self.host._command_pi.call_args
        self.assertIs(args[1], record)
        self.assertEqual(kwargs['notification']['message'], '喝水时间到了')
        self.assertFalse(self.bus.requests, 'Self wake must not use a self-dispatch bus request')
        old_key = record.key
        self.host._pool.records.pop(old_key)
        record.key = 'restarted-token'
        self.host._pool.records[record.key] = record
        self.assertIs(host.record(source), record)
        request['arguments'] = {'run_id':'e'*32,'target':'main','text':'不可改投前台'}
        with self.assertRaises(ValueError):host.request(request)
        self.pet.configure({'visible':False})
        with self.assertRaises(ValueError):host.capture(source)

    def test_reminder_tool_shared_crud_and_due_delivery_preserve_unread(self):
        from datetime import datetime,timedelta,timezone
        record=self.bind();binding=self.helper.reminder_binding_for(record)
        def call(action,**values):return self.helper.reminder(record,{'binding':binding,'action':action,**values})
        created=call('create',title='喝水',dueAt=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),repeat='daily',timeZone='UTC')['item']
        self.assertEqual(created['agentId'],record.global_agent)
        self.assertEqual(call('list')['items'][0]['id'],created['id'])
        self.assertEqual(call('update',id=created['id'],notes='一杯温水')['item']['notes'],'一杯温水')
        self.assertEqual(call('get',id=created['id'])['item']['repeat'],'daily')
        self.assertEqual(self.helper.reminder(self.host._view,{'binding':binding,'action':'list'})['status'],'unavailable')
        self.assertEqual(self.helper.reminder(record,{'binding':'stale','action':'list'})['status'],'binding_changed')
        self.pet.reminders.clock=lambda:datetime.now(timezone.utc)+timedelta(hours=2)
        self.pet.reminders.check();self.helper.flush_reminders()
        self.assertEqual(len(self.pet.reminders.pending_notifications()),1)
        self.assertEqual(len(self.pet.reminders.unread_alerts()),1)
        self.host._command_pi.assert_called_once()
        self.assertIs(self.host._command_pi.call_args.kwargs['record'],record)
        self.assertIn('reminders',self.host._command_pi.call_args.kwargs['notification']['data'])
        notification=self.host._command_pi.call_args.kwargs['notification']
        self.assertRegex(notification['id'],r'^[a-f0-9]{32}$')
        self.helper.flush_reminders();self.host._command_pi.assert_called_once()
        self.helper.observe_reminders(record,{'type':'widget_delivery','id':notification['id'],'status':'queued'})
        self.assertEqual(len(self.pet.reminders.pending_notifications()),1)
        self.helper.observe_reminders(self.host._view,{'type':'widget_delivery','id':notification['id'],'status':'delivered'})
        self.assertEqual(len(self.pet.reminders.pending_notifications()),1)
        self.helper.observe_reminders(record,{'type':'widget_delivery','id':notification['id'],'status':'failed','error':'fixture failure'})
        self.helper.flush_reminders();self.host._command_pi.assert_called_once()
        self.now+=31;self.helper.flush_reminders();self.assertEqual(self.host._command_pi.call_count,2)
        self.helper.observe_reminders(record,{'type':'widget_delivery','id':notification['id'],'status':'delivered'})
        self.assertEqual(self.pet.reminders.pending_notifications(),[])
        self.assertEqual(len(self.pet.reminders.unread_alerts()),1)
        call('complete',id=created['id']);self.assertEqual(len(self.pet.reminders.unread_alerts()),1)
        self.assertFalse(call('complete',id=created['id'],completed=False)['item']['completed'])
        self.assertEqual(len(self.pet.reminders.unread_alerts()),1)
        self.pet.openReminders(created['id'],False);self.assertEqual(self.pet.reminders.unread_alerts(),[])
        call('delete',id=created['id']);self.assertEqual(call('list')['items'],[])

    def test_visible_character_limit_and_reminder_priority(self):
        record = self.bind()
        self.assertEqual(self.speak(record, '字'*81)['status'], 'invalid_text')
        self.assertEqual(self.speak(record, '<'*2000)['status'], 'invalid_text')
        self.assertEqual(self.speak(record, ' \n\t')['status'], 'invalid_text')
        self.pet._reminder_card = [{'id':'reminder'}]
        self.assertEqual(self.speak(record)['status'], 'unavailable')
        self.pet._reminder_card = []
        self.assertTrue(self.speak(record, '👩‍💻'*80)['ok'], 'Count visible graphemes, not UTF-16 units')
        self.assertEqual(len(self.spoken_text()), 1)

    def spoken_text(self): return [s for s in self.speech if s]

    def test_real_completion_hook_threshold_dedup_source_and_bounded_delivery(self):
        assistant = self.bind()
        record = SessionState(id='background-chat',title='后台长任务',action='prompt',prompt_started=self.now-90,
                              messages=[{'role':'assistant','text':'真实结果：完成。'+'x'*100000}])
        self.host.store.data['sessionMeta'] = {}; self.host.store.save = Mock()
        with patch('app.controller_runtime.time.monotonic', return_value=self.now):
            PiControllerMixin._finish_turn(self.host, record)
        self.assertFalse(self.helper.pending)
        record.prompt_started -= .001
        with patch('app.controller_runtime.time.monotonic', return_value=self.now):
            PiControllerMixin._finish_turn(self.host, record)
            PiControllerMixin._finish_turn(self.host, record)
        self.assertEqual(len(self.helper.pending), 1)
        brief = next(iter(self.helper.pending.values()))
        self.assertEqual(brief['sessionId'], 'background-chat')
        self.assertEqual(brief['source'], '后台长任务')
        self.assertEqual(len(brief['result']), 800)
        self.helper.flush()
        args = self.host._command_pi.call_args
        self.assertEqual(args.args, ('widget-notify',))
        self.assertIs(args.kwargs['record'], assistant)
        self.assertEqual(args.kwargs['notification']['data']['taskBriefings'][0], brief)
        self.assertFalse(self.helper.pending)
        self.helper.completed(assistant, {'elapsed':200,'state':'finished'})
        self.assertFalse(self.helper.pending, 'The assistant cannot notify itself recursively')

    def test_completion_storm_is_bounded_and_disabled_paths_do_not_backfill(self):
        self.bind()
        record = SessionState(id='task', title='任务', action='prompt')
        for i in range(200):
            record.prompt_started = i
            self.helper.completed(record, {'elapsed':100,'state':'finished'})
        self.assertEqual(len(self.helper.pending), 8)
        self.assertEqual(self.helper.overflow, 192)
        self.assertEqual(len(self.helper.seen), 128)
        self.manager.setEnabled('global-agents', False)
        self.assertFalse(self.helper.pending)
        self.assertFalse(self.helper.binding)
        self.helper.completed(record, {'elapsed':100,'state':'finished'})
        self.assertFalse(self.helper.pending)
        self.assertEqual(self.speak(self.bus.records[next(iter(self.bus.records))])['status'],'unavailable')

    def test_streaming_status_refresh_does_not_postpone_pending_delivery_timer(self):
        from PySide6.QtTest import QTest
        self.bind()
        record = SessionState(id='task', action='prompt', prompt_started=1)
        self.helper.completed(record, {'elapsed':100,'state':'finished'})
        remaining = self.helper.timer.remainingTime()
        QTest.qWait(100)
        self.helper.reconcile()
        record.prompt_started = 2
        self.helper.completed(record, {'elapsed':100,'state':'finished'})
        self.assertLess(self.helper.timer.remainingTime(), remaining - 50)


if __name__ == '__main__': unittest.main()
