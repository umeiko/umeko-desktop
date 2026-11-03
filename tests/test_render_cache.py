"""Session render retention, isolated from other tests' Qt application types."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class RenderCacheSubprocessTests(unittest.TestCase):
    def test_render_cache_offscreen(self):
        with tempfile.TemporaryDirectory(prefix='render-cache-') as temporary:
            env = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
                       QSG_RHI_BACKEND='software', QT_QUICK_CONTROLS_STYLE='Basic',
                       UMEKO_DATA_DIR=str(Path(temporary) / 'profile'),
                       PI_CODING_AGENT_DIR=str(Path(temporary) / 'agent'), PYTHONUTF8='1')
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--child'],
                                    cwd=ROOT, env=env, capture_output=True, text=True,
                                    encoding='utf-8', timeout=60,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def child_suite():
    import copy
    import threading
    from types import SimpleNamespace
    from unittest.mock import patch
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtGui import QGuiApplication
    from app.chat_model import ChatModel
    from app.chat_presentation import HistoryPresentation, LocalDocument
    from app.transcript_index import WeightedLRU

    application = QGuiApplication.instance() or QGuiApplication([])

    def wait_until(predicate):
        loop, timer, deadline = QEventLoop(), QTimer(), QTimer()
        timer.setInterval(5)
        timer.timeout.connect(lambda: loop.quit() if predicate() else None)
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        timer.start()
        deadline.start(5000)
        if not predicate():
            loop.exec()
        timer.stop()
        deadline.stop()
        if not predicate():
            raise AssertionError('Render worker did not settle')

    class RenderCacheTests(unittest.TestCase):
        def setUp(self):
            self.calls = []
            calls = self.calls

            class ObservedDocument(LocalDocument):
                def setMarkdown(self, text, *args):
                    calls.append((text, threading.get_ident()))
                    return super().setMarkdown(text, *args)

            self.patch = patch('app.chat_presentation.LocalDocument', ObservedDocument)
            self.patch.start()
            self.addCleanup(self.patch.stop)
            self.model = ChatModel()
            self.addCleanup(self.shutdown)
            self.context = {'theme': 'light', 'themeStyle': {'base': 'light', 'colors': {}},
                            'fontScale': 1.0, 'fontFamily': 'sans-serif',
                            'language': 'en', 'lineSpacing': 'standard'}

        def shutdown(self):
            self.model.close()
            self.model._reader.shutdown(wait=True, cancel_futures=True)
            application.processEvents()

        def bind(self, key, messages, streaming=False, enabled=True):
            self.model.set_session(key, self.context, streaming, enabled)
            self.model.set_snapshot(None)
            self.model.update(messages)
            if messages:
                self.model.requestRange(0, self.model.rowCount() - 1)

        def ready(self, row=0):
            self.model.message(row)
            wait_until(lambda: self.model._job is None and self.model.isReady(row))
            return self.model.message(row)

        @staticmethod
        def rendered(row):
            return row.get('_rendered') or next((step.get('_rendered') for step in row.get('activity', [])
                                               if step.get('_rendered')), None)

        def test_finished_live_session_switch_hits_without_touching_native_rows(self):
            messages = [{'entryId': 'one', 'role': 'assistant', 'text': '**Alpha**\n\n```py\nx=1\n```'}]
            original = copy.deepcopy(messages)
            self.bind('a', messages)
            self.assertTrue(self.rendered(self.ready()))
            self.assertNotIn('umeko-conversation:', repr(self.rendered(self.model.message(0))))
            self.assertEqual(len(self.calls), 1)
            self.assertNotEqual(self.calls[0][1], threading.get_ident())
            self.assertNotIn('_rendered', self.model.rows[0]['activity'][0])
            self.bind('b', [{'entryId': 'two', 'role': 'assistant', 'text': 'Beta'}])
            self.ready()
            count = len(self.calls)
            self.bind('a', messages)
            self.assertTrue(self.rendered(self.ready()))
            self.assertEqual(len(self.calls), count)
            self.assertEqual(messages, original)

        def test_edit_regenerate_and_delete_replace_or_remove_row_slot(self):
            messages = [{'entryId': 'one', 'role': 'assistant', 'text': 'old'}]
            self.bind('a', messages)
            self.ready()
            messages[0]['text'] = 'edited'
            self.model.update(messages, dirty_from=0)
            self.assertTrue(self.rendered(self.ready()))
            self.assertEqual(len(self.calls), 2)
            self.assertEqual(len(self.model._render_cache.items), 1)
            self.assertNotIn('old', repr(self.model._render_cache.items))
            messages[0]['entryId'] = 'regenerated'
            self.model.update(messages, dirty_from=0)
            self.ready()
            self.assertEqual(len(self.calls), 3)
            self.model.update([])
            self.assertFalse(self.model._render_cache.items)
            self.assertEqual(self.model._render_cache.weight, 0)

        def test_all_render_context_changes_invalidate_without_old_context_versions(self):
            messages = [{'role': 'assistant', 'text': 'same answer'}]
            self.bind('a', messages)
            self.ready()
            changes = [('theme', 'dark'), ('themeStyle', {'base': 'dark', 'colors': {'accent': '#ff0000'}}),
                       ('language', 'zh'), ('fontScale', 1.25), ('fontFamily', 'serif'),
                       ('lineSpacing', 'relaxed')]
            for field, value in changes:
                self.context[field] = value
                count = len(self.calls)
                self.model.set_session('a', self.context)
                self.ready()
                self.assertEqual(len(self.calls), count + 1, field)
                self.assertEqual(len(self.model._presentation.sessions), 1)

        def test_streaming_group_and_every_fragment_bypass_until_completion(self):
            messages = [{'entryId': 'start', 'role': 'assistant', 'text': 'Inspect',
                         'tools': [{'id': 'read', 'name': 'read', 'state': 'done'}]},
                        {'entryId': 'tail', 'role': 'assistant', 'text': 'streamed paragraph\n\n' * 5000}]
            self.bind('a', messages, streaming=True)
            self.assertGreater(len(self.model.rows), 1)
            self.assertTrue(all(not self.model._live_renderable(i) for i in range(self.model.rowCount())))
            self.assertFalse(self.model._render_cache.items)
            self.assertFalse(self.calls)
            self.assertFalse(self.model.message(0).get('_loading'))
            self.model.set_session('a', self.context, streaming=False)
            self.model.requestRange(0, 0)
            self.assertTrue(self.rendered(self.ready()))
            self.assertTrue(self.calls)

        def test_session_discard_disabled_cache_and_close_release_render_resources(self):
            messages = [{'role': 'assistant', 'text': 'retained'}]
            self.bind('a', messages)
            self.ready()
            self.model.discard_session('a')
            self.assertNotIn('a', self.model._presentation.sessions)
            self.assertFalse(self.model._cache_enabled)
            self.assertFalse(self.model._wanted)
            self.assertFalse(self.model.message(0).get('_loading'))
            self.bind('b', messages, enabled=False)
            self.assertNotIn('b', self.model._presentation.sessions)
            self.bind('a', messages)
            self.ready()
            self.model.close()
            self.assertFalse(self.model._presentation.sessions)
            self.assertFalse(self.model._live_prepared)

        def test_session_lru_bound_and_cancelled_prepare_do_not_store_results(self):
            presentation = HistoryPresentation()
            cache = presentation.session_cache('a', {})
            cache.limit = 64
            row = {'role': 'assistant', 'text': '**larger than the cache**'}
            result = presentation.prepare({0: row}, cache=cache)
            self.assertTrue(result[0]['_rendered'])
            self.assertEqual(cache.weight, 0)
            self.assertFalse(cache.items)
            cancelled = threading.Event()
            original = LocalDocument.setMarkdown
            def cancel_after_parse(document, text, *args):
                value = original(document, text, *args)
                cancelled.set()
                return value
            cache.limit = 1024 * 1024
            with patch.object(LocalDocument, 'setMarkdown', cancel_after_parse):
                self.assertEqual(presentation.prepare({0: row}, cancelled.is_set, cache=cache), {})
            self.assertFalse(cache.items)
            presentation.discard_session('a')
            self.assertNotIn('a', presentation.sessions)

        def test_discard_during_worker_parse_cannot_restore_released_session(self):
            entered, release = threading.Event(), threading.Event()
            original = LocalDocument.setMarkdown
            def blocked(document, text, *args):
                entered.set()
                if not release.wait(5):
                    raise AssertionError('Test release did not arrive')
                return original(document, text, *args)
            with patch.object(LocalDocument, 'setMarkdown', blocked):
                try:
                    self.bind('a', [{'role': 'assistant', 'text': 'in-flight'}])
                    wait_until(entered.is_set)
                    cache = self.model._render_cache
                    self.model.discard_session('a')
                finally:
                    release.set()
                wait_until(lambda: self.model._job is None)
            self.assertNotIn('a', self.model._presentation.sessions)
            self.assertFalse(cache.items)
            self.assertFalse(self.model._live_prepared)

        def test_paged_history_stays_viewport_bounded_and_session_cache_survives_switch(self):
            class Snapshot:
                count, question_count, focus_row = 10000, 0, 0
                database, revision = 'fixture.db', 1
                repository = SimpleNamespace(cache=WeightedLRU())
                reads = []
                def page(self, page):
                    from app.transcript_index import PAGE_ROWS
                    self.reads.append(page)
                    return {i: {'role': 'assistant', 'text': 'body ' + str(i)}
                            for i in range(page * PAGE_ROWS, (page + 1) * PAGE_ROWS)}
                def key(self, row):
                    return ('fixture', row)
                def metadata(self, row):
                    return {'role': 'assistant', 'hint': 100}
            snapshot = Snapshot()
            self.model.set_session('a', self.context)
            self.model.set_snapshot(snapshot)
            self.ready()
            self.assertLessEqual(len(self.model._prepared), 8)
            count = len(self.calls)
            self.bind('b', [{'role': 'assistant', 'text': 'other'}])
            self.ready()
            other_count = len(self.calls)
            self.model.set_session('a', self.context)
            self.model.set_snapshot(snapshot)
            self.ready()
            self.assertEqual(len(self.calls), other_count)
            self.assertGreater(count, 0)
            # An edited/deleted offscreen row cannot remain cached under the
            # revised transcript, even before that viewport is revisited.
            self.model._render_cache.put(9000, (((-1, 'deleted historical text', False),), []))
            snapshot.revision = 2
            snapshot.count = 9999
            self.model.set_snapshot(snapshot)
            self.assertNotIn(9000, self.model._render_cache.items)
            self.assertNotIn('deleted historical text', repr(self.model._render_cache.items))
            self.ready()
            self.assertGreater(len(self.calls), other_count)
            self.model.discard_session('a')
            self.assertNotIn('a', self.model._snapshot_sources)
            self.assertFalse(self.model._wanted)
            self.assertIsNone(self.model._job)

    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RenderCacheTests))
    return result.wasSuccessful()


if __name__ == '__main__':
    if '--child' in sys.argv:
        raise SystemExit(0 if child_suite() else 1)
    unittest.main()
