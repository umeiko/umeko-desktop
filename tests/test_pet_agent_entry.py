"""Production entry selection, confirmation and exact conversation navigation."""
import copy
from unittest.mock import Mock, patch
from app.pi_sessions import SessionState
from tests import test_pet_agent_target as target_fixtures

class PetAgentEntryTests(target_fixtures.PetAgentTargetTests):
    def setUp(self):
        super().setUp()
        self.entry=self.pet.agentEntry
        self.entry.open()
        self.entry.select(self.identifier)

    def test_preview_is_read_only_then_confirm_dispatches_once(self):
        self.entry.setBody(' 检查构建\n保留正文 ')
        self.entry.prepare()
        self.host._command_pi.assert_not_called()
        self.assertTrue(self.entry.state['preview'])
        self.entry.confirm();self.entry.confirm()
        self.host._command_pi.assert_called_once()
        self.assertTrue(self.entry.state['attempted'])
        self.assertEqual(self.entry.body,'')
        self.assertIn('不代表完成',self.entry.notice)
        self.assert_isolation()

    def test_busy_between_preview_and_confirm_preserves_exact_draft(self):
        self.entry.setBody('  不插话\n ');self.entry.prepare()
        self.record.busy=True;self.entry.confirm()
        self.host._command_pi.assert_not_called()
        self.assertEqual(self.entry.body,'  不插话\n ')
        self.assertFalse(self.entry.attempted)

    def test_configuration_changed_after_preview_rejected(self):
        self.entry.setBody('保留');self.entry.prepare()
        self.bus.agents[self.identifier]['tools']=['bash']
        self.entry.confirm()
        self.host._command_pi.assert_not_called()
        self.assertEqual(self.entry.body,'保留')

    def test_close_cancel_and_reopen_preserve_target_and_draft(self):
        self.entry.setBody('保留');self.entry.prepare();self.entry.close()
        self.entry.confirm();self.host._command_pi.assert_not_called()
        self.entry.open()
        self.assertEqual(self.entry.body,'保留')
        self.assertFalse(self.entry.preview)

    def test_per_target_drafts_do_not_rebind_companion(self):
        other='c'*32
        self.bus.agents[other]={'id':other,'name':'另一个','model':'fixture-model'}
        self.bus.records[other]=SessionState(global_agent=other,model='fixture-model')
        self.entry.setBody('B正文');self.entry.select(other);self.entry.setBody('C正文')
        self.entry.select(self.identifier);self.assertEqual(self.entry.body,'B正文')
        self.entry.select(other);self.assertEqual(self.entry.body,'C正文')
        self.assertEqual(self.helper.identifier,self.default.global_agent)

    def test_deleted_target_cannot_open_replacement_conversation(self):
        del self.bus.agents[self.identifier]
        with patch.object(self.manager,'openPage') as open_page:
            self.assertFalse(self.entry.openDesktop());open_page.assert_not_called()
        self.host._command_pi.assert_not_called()

    def test_open_desktop_requests_exact_target_without_sending(self):
        with patch.object(self.manager,'openPage',return_value=True) as open_page:
            self.assertTrue(self.entry.openDesktop())
            open_page.assert_called_once_with('global-agents')
        self.assertEqual(self.manager._agent_navigation['id'],self.identifier)
        self.host._command_pi.assert_not_called()

    def test_unavailable_catalog_does_not_create_or_enable(self):
        before=copy.deepcopy(self.bus.agents)
        self.bus.active=False;self.entry.refresh()
        self.assertEqual(self.entry.options,[])
        self.assertEqual(self.bus.agents,before)

    def test_edit_after_preview_requires_another_preview(self):
        self.entry.setBody('原文');self.entry.prepare();self.entry.setBody('新文')
        self.entry.confirm();self.host._command_pi.assert_not_called()

    def test_uncertain_dispatch_latches_attempt_and_keeps_draft(self):
        self.entry.setBody('保留');self.entry.prepare()
        self.host._command_pi.side_effect=RuntimeError('uncertain')
        self.entry.confirm();self.entry.confirm()
        self.assertEqual(self.host._command_pi.call_count,1)
        self.assertTrue(self.entry.attempted);self.assertEqual(self.entry.body,'保留')

    def test_default_target_cannot_be_selected_or_dispatched_as_fallback(self):
        self.entry.select(self.default.global_agent)
        self.assertEqual(self.entry.target.identifier, self.identifier)
        del self.bus.agents[self.identifier]
        self.entry.setBody('保留原目标正文');self.entry.prepare();self.entry.confirm()
        self.host._command_pi.assert_not_called()
        self.assertFalse(self.default.messages)
        self.assertEqual(self.entry.body,'保留原目标正文')

    def running_preview(self, run='run-1'):
        self.record.id = 'existing-session'
        self.record.file = 'existing.jsonl'
        self.record.ready = True
        self.record.process = object()
        self.record.phase = 'running'
        self.record.action = 'prompt'
        self.record.pet_follow_up_run = run
        self.entry.select(self.identifier)
        self.entry.setBody('  追加正文\n ')
        self.entry.prepare()
        self.assertTrue(self.entry.state['followUp'])

    def test_bound_follow_up_waits_for_exact_receipt_and_never_steers(self):
        self.running_preview()
        self.entry.confirm()
        self.entry.confirm()
        [(key, event)] = self.host._pool.writes
        self.assertEqual(key, self.record.key)
        self.assertEqual((event['type'], event['petRunId']), ('follow-up', 'run-1'))
        self.assertEqual(self.entry.body, '  追加正文\n ')
        self.host._command_pi.assert_not_called()
        receipt = {'type': 'pet_follow_up_receipt', 'messageId': event['messageId'],
                   'runId': event['petRunId'], 'status': 'queued'}
        self.host._pool.event.emit(self.default, receipt)
        self.host._pool.event.emit(self.record, {**receipt, 'messageId': 'wrong'})
        self.host._pool.event.emit(self.record, {**receipt, 'runId': 'other'})
        self.assertEqual(self.entry.body, '  追加正文\n ')
        self.host._pool.event.emit(self.record, receipt)
        self.assertEqual(self.entry.body, '')
        self.assertIn('不代表开始或完成', self.entry.notice)
        self.assertEqual(self.host._view.draft, '主窗口草稿')
        self.assertEqual(self.record.draft, '目标原会话未发草稿')
        self.assertFalse(self.bus.bridges)

    def test_run_change_does_not_fallback_to_new_run_or_idle_prompt(self):
        self.running_preview()
        self.record.pet_follow_up_run = 'run-2'
        self.entry.confirm()
        self.assertEqual(self.entry.body, '  追加正文\n ')
        self.assertFalse(self.host._pool.writes)
        self.entry.prepare()
        self.record.phase = 'idle'
        self.entry.confirm()
        self.assertFalse(self.host._pool.writes)
        self.host._command_pi.assert_not_called()

    def test_exit_or_uncertain_retains_draft_and_ignores_late_success(self):
        self.running_preview()
        self.entry.confirm()
        event = self.host._pool.writes[-1][1]
        self.host._pool.event.emit(self.record, {'type': 'exit'})
        self.host._pool.event.emit(self.record, {'type': 'pet_follow_up_receipt',
            'messageId': event['messageId'], 'runId': event['petRunId'], 'status': 'queued'})
        self.entry.confirm()
        self.assertEqual(len(self.host._pool.writes), 1)
        self.assertEqual(self.entry.body, '  追加正文\n ')
