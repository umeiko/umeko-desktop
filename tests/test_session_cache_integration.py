"""Session cache/controller contracts; isolated Qt and no model or desktop I/O."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')

from tests.test_preview_channel import qt_application, isolated_test_module
from PySide6.QtTest import QSignalSpy
from app.controller import Controller
from app.pi_sessions import SessionState
from app.storage import Store


class ControllerCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_application()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='umeko-session-cache-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, {'UMEKO_DATA_DIR': str(self.root / 'profile')})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        seed = Store()
        seed.data['agent']['agentDir'] = str(self.root / 'agent')
        seed.save()
        self.controller = Controller(ROOT)
        self.addCleanup(self.controller.close)

    def session(self, identifier, **values):
        record = SessionState(id=identifier, title=identifier,
                              messages=[{'role': 'assistant', 'text': 'Completed reply', 'error': False}], **values)
        self.controller._sessions.append({'id': identifier, 'title': identifier, 'file': ''})
        self.controller._pool.touch(record)
        return record

    def test_capacity_persists_and_failed_save_keeps_previous_policy(self):
        c = self.controller
        self.assertEqual(c._pool.limit, 3)
        self.assertTrue(c.setSessionCacheSize(1))
        self.assertEqual(c._pool.limit, 1)
        self.assertEqual(Store().data['ui']['sessionCacheSize'], 1)
        with patch.object(c.store, 'save', side_effect=OSError('Cannot save')):
            self.assertFalse(c.setSessionCacheSize(0))
        self.assertEqual(c._pool.limit, 1)
        self.assertEqual(c.store.data['ui']['sessionCacheSize'], 1)
        for value in (-1, True, '3', 2147483648):
            self.assertFalse(c.setSessionCacheSize(value))

    def test_store_invalid_capacity_uses_default(self):
        settings = self.root / 'separate'
        settings.mkdir()
        (settings / 'settings.json').write_text(json.dumps({'ui': {'sessionCacheSize': -3}}), encoding='utf-8')
        self.assertEqual(Store(settings).data['ui']['sessionCacheSize'], 3)

    def test_cached_switch_only_refreshes_global_settings_when_configuration_changes(self):
        c = self.controller
        first = self.session('first')
        second = self.session('second')
        c.openSession(first.id)
        c.openSession(second.id)
        c.openSession(first.id)
        changed, view = QSignalSpy(c.changed), QSignalSpy(c.viewChanged)
        c.openSession(second.id)
        self.assertEqual(changed.count(), 0)
        self.assertEqual(view.count(), 1)
        c.store.data['providers'] = [{'id': 'test-provider', 'name': 'Test provider',
                                     'api': 'openai', 'models': [{'alias': 'test-model', 'upstream': 'test-model'}]}]
        different = self.session('different', provider='test-provider', model='test-model')
        c.openSession(different.id)
        self.assertEqual(changed.count(), 1)
        self.assertEqual(c.config['selectedModel'], 'test-model')

    def test_crashed_cached_kernel_restarts_on_switch_back_but_cold_history_is_lazy(self):
        c = self.controller
        crashed = self.session('crashed', crashed=True)
        with patch.object(c, '_command_pi', return_value=True) as command:
            c.openSession(crashed.id)
            command.assert_called_once_with('inspect', record=crashed)
        cold = self.session('cold')
        with patch.object(c, '_command_pi') as command:
            c.openSession(cold.id)
            command.assert_not_called()

    def test_delete_without_transcript_releases_render_and_process_lifecycle(self):
        c = self.controller
        record = self.session('no-file')
        with patch.object(c._chat_model, 'discard_session', wraps=c._chat_model.discard_session) as discard:
            c.deleteSession(record.id)
            discard.assert_called_once_with(record.key)
        self.assertIsNone(c._pool.find(record.id))
        self.assertFalse(any(row['id'] == record.id for row in c._sessions))

    def test_archive_releases_idle_resources_and_keeps_waiting_session(self):
        c = self.controller
        idle = self.session('idle')
        waiting = self.session('waiting', approval={'id': 'question'})
        with patch.object(c._chat_model, 'discard_session') as discard:
            c.archiveSession(idle.id, True)
            discard.assert_called_once_with(idle.key)
            c.archiveSession(waiting.id, True)
            self.assertEqual(discard.call_count, 1)
        self.assertFalse(idle.retained)
        self.assertTrue(waiting.retained)
        c.deleteSession(waiting.id)
        self.assertIs(c._pool.find(waiting.id), waiting)
        c._handle_pi_event(waiting, {'type': 'done'})
        self.assertFalse(waiting.retained, 'Archived task must release its cache once it becomes idle')

    def test_language_change_invalidates_startup_configuration(self):
        c = self.controller
        with patch.object(c, '_restart_pi') as restart:
            c.setLanguage('en' if c.language == 'zh' else 'zh')
            restart.assert_called_once_with()

    def test_stale_kernel_with_running_child_is_not_closed(self):
        c = self.controller
        record = self.session('children', stale=True, subagents_active=True)
        with patch.object(c._pool, 'retire') as retire:
            self.assertFalse(c._command_pi('inspect', record=record))
            retire.assert_not_called()
        c._handle_pi_event(record, {'type': 'done'})
        self.assertTrue(record.stale)

    def test_finished_background_task_rechecks_idle_capacity(self):
        c = self.controller
        c.setSessionCacheSize(0)
        running = self.session('running', phase='running', action='inspect')
        self.assertTrue(running.retained)
        c._handle_pi_event(running, {'type': 'done'})
        self.assertFalse(running.retained)

    def test_stale_path_is_checked_at_click_without_fallback_open(self):
        c = self.controller
        file = self.root / 'guide.txt'
        file.write_text('content', encoding='utf-8')
        # The cached link was resolved while the file existed.
        from app.conversation_links import recognize_links
        link = recognize_links('guide.txt', self.root)[0]
        file.unlink()
        toasts = []
        c.toast.connect(toasts.append)
        with patch.object(c, 'openChatboxPath') as opener, patch('app.controller.QDesktopServices.openUrl') as desktop:
            c.openConversationPath(link.target, False)
            c.openConversationPath(link.target, True)
            opener.assert_not_called()
            desktop.assert_not_called()
        self.assertEqual(toasts, ['文件已移动或不存在', '文件已移动或不存在'])


def load_tests(loader, tests, pattern):
    if __name__ == '__main__':
        return tests
    class Isolated(unittest.TestCase):
        def runTest(self):
            isolated_test_module(self, Path(__file__))
    return unittest.TestSuite([Isolated()])


if __name__ == '__main__':
    unittest.main(verbosity=2)
