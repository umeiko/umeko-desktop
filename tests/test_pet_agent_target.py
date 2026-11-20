"""Production target contract using isolated native SessionState and mock dispatch."""
import copy
import unittest
from app.pet_agent_target import PetAgentTarget
from app.pi_sessions import SessionState
from tests import test_pet_assistant as fixtures


class PetAgentTargetTests(unittest.TestCase):
    setUpClass = classmethod(lambda cls: fixtures.PetAssistantTests.setUpClass())
    bind = fixtures.PetAssistantTests.bind

    def setUp(self):
        fixtures.PetAssistantTests.setUp(self)
        self.default = self.bind()
        self.identifier = 'b' * 32
        self.bus.agents[self.identifier] = {'id': self.identifier, 'name': '测试目标',
                                           'model': 'fixture-model', 'tools': [], 'skills': []}
        self.record = SessionState(global_agent=self.identifier, model='fixture-model')
        self.record.draft = '目标原会话未发草稿'
        self.record.attachments = [{'id': 'target-fixture'}]
        self.bus.records[self.identifier] = self.record
        self.target = PetAgentTarget(self.bus, self.identifier)
        self.host._view.draft = '主窗口草稿'
        self.host._view.attachments = [{'id': 'fixture'}]
        self.snapshot = copy.deepcopy(self.bus.agents)

    def assert_isolation(self):
        self.assertEqual(self.bus.agents, self.snapshot)
        self.assertFalse(self.bus.bridges)
        self.assertFalse(self.host._pool.writes)
        self.assertEqual(self.helper.identifier, self.default.global_agent)
        self.assertEqual(self.host._view.draft, '主窗口草稿')
        self.assertEqual(self.host._view.attachments, [{'id': 'fixture'}])
        self.assertEqual(self.record.draft, '目标原会话未发草稿')
        self.assertEqual(self.record.attachments, [{'id': 'target-fixture'}])

    def reject(self, status):
        text = '  保留\n原始草稿  '
        self.assertEqual(self.target.submit(text), {'ok': False, 'status': status,
                         'draft': text, 'targetId': self.identifier})
        self.host._command_pi.assert_not_called()
        self.assertFalse(self.host._pool.writes)

    def test_idle_dispatch_owns_target_and_does_not_grant_or_rebind(self):
        result = self.target.submit('  目标任务  ')
        self.assertTrue(result['ok'])
        self.assertEqual(result['sessionKey'], self.record.key)
        self.host._command_pi.assert_called_once_with('prompt', self.record,
                                                       text='(input from pet)\n目标任务')
        self.assertEqual(self.record.messages[0]['text'], '(input from pet)\n目标任务')
        self.assertFalse(self.default.messages)
        self.assert_isolation()
        self.assertEqual(self.target.submit('重复')['status'], 'already_submitted')
        self.assertEqual(self.host._command_pi.call_count, 1)

    def test_busy_ready_never_steers_or_consumes_draft(self):
        self.record.busy = self.record.ready = True
        self.reject('busy')
        self.assert_isolation()

    def test_pending_approval_never_dispatches(self):
        self.record.approval = {'id': 'synthetic-approval'}
        self.reject('busy')
        self.assertEqual(self.record.approval, {'id': 'synthetic-approval'})
        self.assert_isolation()

    def test_disabled_never_falls_back(self):
        self.bus.active = False
        self.reject('unavailable')

    def test_deleted_never_recreates(self):
        del self.bus.agents[self.identifier]
        self.reject('target_changed')
        self.assertNotIn(self.identifier, self.bus.agents)

    def test_replaced_config_even_same_values_requires_reselection(self):
        self.bus.agents[self.identifier] = copy.deepcopy(self.bus.agents[self.identifier])
        self.reject('target_changed')

    def test_changed_tools_requires_reselection_without_changing_them(self):
        self.bus.agents[self.identifier]['tools'] = ['read']
        self.reject('target_changed')
        self.assertEqual(self.bus.agents[self.identifier]['tools'], ['read'])

    def test_replaced_session_requires_reselection(self):
        self.bus.records[self.identifier] = SessionState(global_agent=self.identifier)
        self.reject('target_changed')

    def test_changed_session_file_requires_reselection(self):
        self.record.file = '/synthetic/not-opened.jsonl'
        self.reject('target_changed')

    def test_uninitialized_target_does_not_create_session(self):
        del self.bus.records[self.identifier]
        self.target = PetAgentTarget(self.bus, self.identifier)
        self.reject('target_changed')
        self.assertNotIn(self.identifier, self.bus.records)

    def test_active_subagents_prevent_dispatch(self):
        self.record.subagents_active = True
        self.reject('busy')

    def test_global_capacity_prevents_dispatch(self):
        for i in range(4):
            record = SessionState()
            record.busy = True
            self.bus.records['busy' + str(i)] = record
        self.reject('capacity')

    def test_invalid_text_does_not_consume_target(self):
        for text in ('', '  ', 'x' * 16001):
            self.assertEqual(self.target.submit(text)['status'], 'invalid_text')
        self.host._command_pi.assert_not_called()
        self.assertTrue(self.target.submit('有效任务')['ok'])

    def test_uncertain_dispatch_is_not_replayed(self):
        self.host._command_pi.side_effect = OSError('synthetic dispatch failure')
        result = self.target.submit('保留草稿')
        self.assertEqual(result['status'], 'uncertain')
        self.assertEqual(result['draft'], '保留草稿')
        self.assertFalse(self.record.messages)
        self.assertEqual(self.target.submit('保留草稿')['status'], 'already_submitted')
        self.assertEqual(self.host._command_pi.call_count, 1)

    def test_failed_dispatch_retains_draft_and_rolls_back_optimistic_messages(self):
        self.host._command_pi.return_value = False
        result = self.target.submit('  原始草稿  ')
        self.assertEqual(result['draft'], '  原始草稿  ')
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(self.record.messages)
        self.assertFalse(self.record.optimistic_user)
        self.assertEqual(self.target.submit('再次')['status'], 'already_submitted')
        self.assertEqual(self.host._command_pi.call_count, 1)
        self.assert_isolation()


if __name__ == '__main__':
    unittest.main()
