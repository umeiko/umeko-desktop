"""Native timers retain the original target and recheck Agent Bus permission."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from PySide6.QtCore import QCoreApplication, QObject, Signal
from app.pi_sessions import SessionState
from app.scheduled_task_host import ScheduledTaskHost


class Pool(QObject):
    event = Signal(object, object)
    def __init__(self, record):
        super().__init__();self.records = {record.key: record};self.writes = []
    def find(self, identifier):return next((r for r in self.records.values() if r.id == identifier), None)
    def write(self, record, value):self.writes.append((record, value))


class ScheduledTaskHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app = QCoreApplication.instance() or QCoreApplication([])
    def setUp(self):
        self.record = SessionState(id='one', workspace='/one')
        self.pool = Pool(self.record)
        self.dispatched = []
        self.allowed = {'a'*32}
        self.bus = SimpleNamespace(active=True, agents={'a'*32:{'name':'Connected'}, 'b'*32:{'name':'Other'}}, records={}, requests={},
            allowed=lambda source, target:target.removeprefix('agent:') in self.allowed)
        def dispatch(operation, args, caller):
            self.dispatched.append((operation, args, caller));key='request-one'
            self.bus.requests[key] = {'status':'queued'}
            return {'requestId':key}
        self.bus.execute = dispatch
        self.commands = []
        self.b = SimpleNamespace(_pool=self.pool, _command_pi=lambda *args, **kw:self.commands.append((args,kw)) or True)
        self.m = SimpleNamespace(entries={'scheduled-tasks':{'builtin':True}}, global_agents=self.bus)
        self.host = ScheduledTaskHost(SimpleNamespace(m=self.m, b=self.b))
        self.source = {'id':self.record.id, 'token':self.record.key, 'workspace':self.record.workspace}
    def request(self, operation, args, source=None):
        return self.host.request({'widget':'scheduled-tasks', 'operation':'scheduledTasks.'+operation,
                                  'arguments':args, 'session':source or self.source, 'page':False})
    def trigger(self, key='c'*32, target='main'):
        return self.request('trigger', {'run_id':key, 'target':target, 'text':'Check progress'})

    def test_native_receipt_is_not_model_completion_and_duplicate_is_not_resent(self):
        self.assertEqual(self.trigger()['state'], 'queued')
        self.trigger()
        self.assertEqual(len(self.commands), 1)
        wrong = SessionState(id='two', workspace='/two')
        self.host.observe(wrong, {'type':'widget_delivery','id':'c'*32,'status':'delivered'})
        self.assertEqual(self.request('status', {'run_ids':['c'*32]})['runs'][0]['state'], 'queued')
        self.host.observe(self.record, {'type':'widget_delivery','id':'c'*32,'status':'delivered'})
        self.assertEqual(self.request('status', {'run_ids':['c'*32]})['runs'][0]['state'], 'delivered')

    def test_only_connected_global_targets_and_permission_rechecked_at_delivery(self):
        self.assertEqual([row['id'] for row in self.request('targets', {})['targets']], ['main', 'agent:'+'a'*32])
        with self.assertRaises(ValueError):self.trigger(target='agent:'+'b'*32)
        self.trigger(target='agent:'+'a'*32)
        self.assertIs(self.dispatched[0][2], self.record)
        self.bus.requests['request-one']['status'] = 'running'
        self.assertEqual(self.request('status', {'run_ids':['c'*32]})['runs'][0]['state'], 'delivered')
        self.allowed.clear()
        with self.assertRaises(ValueError):self.trigger('d'*32, 'agent:'+'a'*32)
        self.assertEqual(len(self.dispatched), 1)

    def test_other_conversation_and_changed_workspace_cannot_access_a_run(self):
        self.trigger()
        other = SessionState(id='two', workspace='/two')
        self.pool.records[other.key] = other
        with self.assertRaises(ValueError):
            self.request('status', {'run_ids':['c'*32]}, {'id':other.id,'token':other.key,'workspace':other.workspace})
        self.record.workspace='/changed'
        with self.assertRaises(ValueError):self.trigger('d'*32)

    def test_native_identity_can_be_recaptured_after_restart_without_opening_foreground(self):
        self.record.key = 'new-process-token'
        self.pool.records = {self.record.key:self.record}
        self.trigger()
        self.assertIs(self.commands[0][0][1], self.record)
        self.assertEqual(self.host.capture(self.source)['token'], 'new-process-token')

    def test_native_delivery_honors_existing_concurrency_capacity(self):
        for index in range(8):
            record = SessionState(id=str(index), workspace='/other', phase='running')
            self.pool.records[record.key] = record
        with self.assertRaisesRegex(ValueError, 'capacity'):self.trigger()
        self.assertEqual(self.commands, [])
