from types import SimpleNamespace
import unittest

from app.global_agents import GlobalAgents
from app.im_widget_channel import ImWidgetChannel, OPERATIONS
from app.pi_sessions import SessionState


class AgentService:
    text = staticmethod(GlobalAgents.text)

    def __init__(self):
        self.agents = {'release': {'name': 'Release'}, 'operations': {'name': 'Operations'}}
        self.records = {key: SessionState(global_agent=key) for key in self.agents}
        self.member_sessions = {}
        self.group_chat = SimpleNamespace(active={})
        self.outbox = {}
        self.channel = ImWidgetChannel(self)
        self.pet_assistant_id = ''
        self.active = True
        self.started = []

    def record(self, identifier):
        return self.records[identifier.removeprefix('agent:')]

    def start_direct_turn(self, record, text):
        record.phase = 'running'
        self.started.append((record, text))

    def retire_turn(self, record):
        record.phase = 'idle'
        self.channel.interrupted(record)


class ImWidgetChannelTests(unittest.TestCase):
    def setUp(self):
        self.service = AgentService()
        self.channel = self.service.channel
        self.operations = {action: name for name, action in OPERATIONS.items()}

    def request(self, action, **arguments):
        return self.channel.request(self.operations[action], arguments)

    def start(self, digit, agent):
        return self.request('start', id=digit * 32, agent=agent, text='Question', sender='Member', group=agent)

    def test_ids_follow_the_original_turn_and_return_only_the_final_reply(self):
        self.assertEqual(self.start('a', 'release')['state'], 'running')
        self.assertEqual(self.start('b', 'release')['state'], 'busy')
        self.assertEqual(self.start('a', 'operations')['state'], 'running')
        self.assertEqual(self.start('b', 'operations')['state'], 'running')
        self.assertEqual(len(self.service.started), 2)
        first, second = self.service.records.values()
        self.channel.observe(first, {'type': 'message', 'role': 'assistant', 'text': 'Planning', 'stopReason': 'toolUse'})
        self.channel.observe(second, {'type': 'message', 'role': 'assistant', 'text': 'Second reply', 'stopReason': 'stop'})
        self.channel.observe(first, {'type': 'message', 'role': 'assistant', 'text': 'First reply', 'stopReason': 'stop'})
        self.assertEqual(self.request('status', id='a' * 32)['reply'], '')
        self.channel.observe(second, {'type': 'done'})
        self.channel.observe(first, {'type': 'done'})
        self.assertEqual(self.request('status', id='a' * 32)['reply'], 'First reply')
        self.assertEqual(self.start('b', 'release')['reply'], 'Second reply')
        self.assertEqual(len(self.service.started), 2)

    def test_cancel_and_stop_settle_while_late_events_cannot_publish(self):
        self.start('a', 'release')
        self.start('b', 'operations')
        self.assertEqual(self.request('cancel', id='a' * 32)['state'], 'cancelled')
        self.assertEqual(self.request('status', id='b' * 32)['state'], 'running')
        self.channel.stop()
        record = self.service.records['operations']
        self.channel.observe(record, {'type': 'message', 'role': 'assistant', 'text': 'Late reply'})
        self.channel.observe(record, {'type': 'done'})
        result = self.request('status', id='b' * 32)
        self.assertEqual((result['state'], result['reply']), ('cancelled', ''))
        self.assertFalse(self.channel.active)
