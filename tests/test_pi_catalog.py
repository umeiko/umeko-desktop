"""Management reads never become chat commands or leak across Pi instances."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtCore import QCoreApplication
from app.pi_sessions import PiSessionPool, SessionState


class PiCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

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
