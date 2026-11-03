"""Bounded retained view models and unchanged credential persistence."""
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from tests.test_preview_channel import qt_application, isolated_test_module
from app.conversation_views import ConversationViews
from app.chat_model import MAX_PREPARED_ROWS, MAX_CACHED_ROWS
from app.storage import Store
from app.transcript_index import TranscriptRepository


class RetainedViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_application()

    def test_warm_model_keeps_rows_heights_and_lru_discards_oldest(self):
        views = ConversationViews()
        self.addCleanup(views.close)
        a = views.select('a')
        a.update([{'role': 'user', 'text': 'retain me'}])
        a._heights[12] = 320
        b, c = views.select('b'), views.select('c')
        self.assertIs(views.select('a'), a)
        self.assertEqual(a.rows[0]['text'], 'retain me')
        self.assertEqual(a._heights[12], 320)
        evicted = []
        views.evicted.connect(evicted.append)
        views.select('d')
        self.assertEqual(evicted, ['b'])
        self.assertEqual(list(views.models), ['c', 'a', 'd'])
        self.assertTrue(b._closed)
        self.assertTrue(c._suspended)
        self.assertFalse(views.models['d']._suspended)
        self.assertIs(a._reader, c._reader)
        self.assertIs(a._presentation, c._presentation)

    def test_viewport_requests_are_bounded_and_inactive_models_do_not_page(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'history.jsonl'
            with path.open('w') as handle:
                for i in range(100):
                    handle.write(json.dumps({'type': 'message', 'id': str(i), 'parentId': str(i-1) if i else None,
                        'message': {'role': 'user' if i % 2 == 0 else 'assistant', 'content': 'message ' + str(i)}}) + '\n')
            views = ConversationViews()
            try:
                model = views.select('a')
                model.suspend(True)
                model.set_snapshot(TranscriptRepository(Path(directory) / 'cache').open(path))
                model.requestRange(20, 90)
                self.assertLessEqual(len(model._wanted), MAX_PREPARED_ROWS)
                self.assertIsNone(model._job)
                self.assertTrue(model.message(20)['_loading'])
                self.assertEqual(model.message(20, synchronous=True)['text'], 'message 20')
                # Screen rows take priority over prefetch and cannot be cut off
                # by the normal eight-row budget on a dense/tall viewport.
                model.requestViewport(list(range(40, 51)), [39, 51])
                self.assertEqual(model._wanted, list(range(40, 51)))
                model._prepared.update((row, {'text': str(row)}) for row in range(35, 51))
                model.requestViewport([43, 44, 45], [42, 46])
                self.assertTrue(model.isReady(41), 'A nearby boundary row was discarded immediately')
                model._prepared.update((row, {'text': str(row)}) for row in range(51, 61))
                model._trim_prepared()
                self.assertLessEqual(len(model._prepared), MAX_CACHED_ROWS)
                self.assertTrue(all(model.isReady(row) for row in model._wanted))
            finally:
                views.close()

    def test_unchanged_credentials_are_reused_across_save_and_reload(self):
        class Keyring:
            priority = 1
            def __init__(self): self.values, self.writes = {}, []
            def set_password(self, service, account, value):
                self.values[service, account] = value
                self.writes.append(account)
            def get_password(self, service, account): return self.values.get((service, account))
        Keyring.__module__ = 'keyring.backends.SecretService'
        ring = Keyring()
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, {'keyring': types.SimpleNamespace(get_keyring=lambda: ring)}):
            store = Store(Path(directory))
            store.data['password'] = 'fixture-password'
            store.data['providers'] = [{'id': 'fixture', 'key': 'fixture-key', 'models': []}]
            store.save()
            self.assertEqual(len(ring.writes), 2)
            for row in range(5):
                store.data['sessionMeta']['fixture'] = {'viewport': {'row': row}}
                store.save()
            self.assertEqual(len(ring.writes), 2)
            reloaded = Store(Path(directory))
            reloaded.data['workspace'] = directory
            reloaded.save()
            self.assertEqual(len(ring.writes), 2)
            reloaded.data['providers'][0]['key'] = 'replacement-key'
            reloaded.save()
            self.assertEqual(len(ring.writes), 3)
            disk = store.path.read_text()
            for secret in ('fixture-password', 'fixture-key', 'replacement-key'):
                self.assertNotIn(secret, disk)
            self.assertEqual(Store(Path(directory)).data['providers'][0]['key'], 'replacement-key')


def load_tests(loader, tests, pattern):
    if __name__ == '__main__': return tests
    class Isolated(unittest.TestCase):
        def runTest(self): isolated_test_module(self, Path(__file__))
    return unittest.TestSuite([Isolated()])

if __name__ == '__main__': unittest.main(verbosity=2)
