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

    def test_speech_limits_are_shared_across_rebinds_and_enforce_identity(self):
        record = self.bind()
        self.assertTrue(self.speak(record)['ok'])
        for _ in range(100): self.assertEqual(self.speak(record)['status'], 'rate_limited')
        self.assertEqual([s for s in self.speech if s], ['任务完成啦。'])
        self.pet.configure({'appearance':'komari'})
        self.assertEqual(self.speak(record)['status'], 'rate_limited')
        self.now += 30; self.assertTrue(self.speak(record, '第二条')['ok'])
        self.now += 29.999; self.assertEqual(self.speak(record)['status'], 'rate_limited')
        self.now += .001; self.assertTrue(self.speak(record, '第三条')['ok'])
        other = SessionState(global_agent=record.global_agent)
        self.assertEqual(self.speak(other)['status'], 'unavailable')
        self.assertEqual(self.speak(self.host._view)['status'], 'unavailable')
        self.pet.configure({'visible':False})
        self.assertEqual(self.speak(record)['status'], 'unavailable')

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
