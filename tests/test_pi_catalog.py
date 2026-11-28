"""Exercise the pool's management and admission messages."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from PySide6.QtCore import QCoreApplication, QProcess
from app.pi_sessions import PiSessionPool, SessionState


class PiCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_broken_admission_pipe_keeps_lease_until_worker_finishes(self):
        def message(action, ticket):
            return {'type': 'subagent_admission', 'action': action, 'ticket': ticket}

        for short_write in (False, True):
            with self.subTest(short_write=short_write), patch('app.pi_sessions.QTimer') as timer:
                pool = PiSessionPool()
                broker = pool.subagent_admission
                broker.set_limit(1)
                a, b = Mock(), Mock()
                a.state.return_value = b.state.return_value = QProcess.Running
                a.write.side_effect = (lambda data: len(data) - 1) if short_write else len
                b.write.side_effect = len
                a.readAllStandardOutput.return_value = b''
                record = SessionState(process=a, ready=True)
                first, second = str(uuid4()), str(uuid4())
                broker.event(a, message('acquire', first))
                broker.event(b, message('acquire', second))
                if not short_write:
                    pool._error(record, a, QProcess.WriteError)
                self.assertEqual(broker.active, {(a, first)})
                self.assertIn((b, second), broker.waiting)
                a.readAllStandardOutput.return_value = (json.dumps(message('release', first)) + '\n').encode()
                pool._read(record, a)
                a.readAllStandardOutput.return_value = b''
                self.assertEqual(broker.active, {(a, first)})
                a.kill.assert_not_called()
                timer.singleShot.call_args.args[1]()
                a.kill.assert_called_once()
                self.assertEqual(broker.active, {(a, first)})
                a.state.return_value = QProcess.NotRunning
                pool._finished(record, a)
                self.assertEqual(broker.active, {(b, second)})
                self.assertEqual(json.loads(b.write.call_args.args[0])['state'], 'granted')
                self.assertIsNone(record.process)

    def test_read_uses_busy_owning_process_and_consumes_only_matching_reply(self):
        pool = PiSessionPool()
        record = SessionState(process=SimpleNamespace(write=Mock()), ready=True, phase='running')
        replies = []
        self.assertTrue(pool.query_catalog(record, 'skills', replies.append))
        identifier = next(iter(pool.catalog_requests))
        pool._catalog_reply(SessionState(), {'id': identifier, 'ok': True, 'value': {'skills': ['wrong chat']}})
        self.assertEqual(replies, [])
        pool._catalog_reply(record, {'id': identifier, 'ok': True, 'value': {'skills': []}})
        self.assertEqual(replies, [{'ok': True, 'value': {'skills': []}}])
        self.assertEqual(record.phase, 'running')
        self.assertFalse(pool.catalog_requests)
        pool._catalog_reply(record, {'id': identifier, 'ok': True, 'value': {'skills': ['late']}})
        self.assertEqual(len(replies), 1)

    def test_stale_or_cold_instances_fall_back_and_retirement_cancels_once(self):
        pool = PiSessionPool()
        for record in (SessionState(), SessionState(process=Mock(), ready=True, stale=True),
                       SessionState(process=Mock(), ready=True, global_agent='coordinator')):
            self.assertFalse(pool.query_catalog(record, 'extensions', Mock()))
        record = SessionState(process=Mock(), ready=True)
        replies = []
        self.assertTrue(pool.query_catalog(record, 'extensions', replies.append))
        pool._cancel_catalogs(record)
        pool._cancel_catalogs(record)
        self.assertEqual(len(replies), 1)
        self.assertFalse(replies[0]['ok'])
        self.assertFalse(pool.catalog_requests)
