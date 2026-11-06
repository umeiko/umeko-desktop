"""Prompt controls enter only through the active built-in page and owning Pi."""
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock

from PySide6.QtCore import QObject, QCoreApplication, Signal

from app.desktop_plugins import DesktopPlugins
from app.widget_host import WidgetHost
from tests.test_widget_host import Manager


class Pool(QObject):
    event = Signal(object, object)


class SystemPromptHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.manager = Manager()
        self.manager._page = 'system-prompt'
        self.manager.entries['system-prompt'] = {
            'name': 'System Prompt', 'builtin': True, 'permissions': ['pi.read', 'pi.manage']}
        self.manager.workers['system-prompt'] = {'ready': True}
        self.manager.b._pool = Pool()
        self.manager.b._view = SimpleNamespace(key='chat-one', workspace='/fixture', busy=False, subagents_active=False)
        self.manager.b._command_pi = Mock(return_value=True)
        self.host = WidgetHost(self.manager)

    def request(self, operation, arguments=None, page=True, widget='system-prompt'):
        identifier = self.host.request_for(widget, {'operation': operation,
            'arguments': arguments or {}, 'session': dict(self.manager._session)}, page=page)
        self.app.processEvents()
        return identifier

    def test_forwards_page_action_to_current_runtime_and_returns_its_tree(self):
        identifier = self.request('systemPrompt.toggle', {'id': 'source', 'enabled': False})
        self.manager.b._command_pi.assert_called_once_with('system-prompt', record=self.manager.b._view,
            requestId=identifier, promptOperation='toggle', id='source', enabled=False)
        result = {'ok': True, 'tree': [{'id': 'source', 'enabled': False}]}
        self.manager.b._pool.event.emit(self.manager.b._view, {
            'type': 'system_prompt', 'requestId': identifier, 'result': result})
        self.assertEqual(self.manager.replies[identifier]['tree'], result['tree'])

    def test_builtin_package_passes_the_actual_worker_manifest_validator(self):
        from umeko_plugin_sdk.packages import validate
        manifest, _, _ = validate(Path(__file__).resolve().parents[1] / 'umeko-plugins/system-prompt')
        self.assertEqual(manifest['id'], 'system-prompt')
        self.assertEqual(manifest['agent']['methods'], {})

    def test_rejects_workers_other_widgets_and_busy_chat(self):
        worker = self.request('systemPrompt.inspect', page=False)
        other = self.request('systemPrompt.inspect', widget='a')
        self.manager.b._view.busy = True
        busy = self.request('systemPrompt.save', {'id': 'source', 'text': 'Edited instruction'})
        for identifier in (worker, other, busy):
            self.assertFalse(self.manager.replies[identifier]['ok'])
        self.manager.b._command_pi.assert_not_called()

    def test_runtime_failure_completes_pending_request(self):
        identifier = self.request('systemPrompt.inspect')
        self.manager.b._pool.event.emit(self.manager.b._view, {'type': 'error', 'message': 'Could not read source'})
        self.assertFalse(self.manager.replies[identifier]['ok'])
        self.assertFalse(self.host._system_prompt.pending)

    def test_default_off_and_session_switches_do_not_leak_activation(self):
        fake = SimpleNamespace(settings={}, entries={'system-prompt': {'builtin': True}}, application=lambda _: False)
        fake.enabled = lambda identifier: DesktopPlugins.enabled(fake, identifier)
        record = SimpleNamespace(id='', key='one')
        self.assertFalse(DesktopPlugins.system_prompt_enabled(fake, record))
        fake.settings = {'enabled': {'system-prompt': True}, 'sessions': {'draft:one': []}}
        self.assertFalse(DesktopPlugins.system_prompt_enabled(fake, record))
        fake.settings['sessions']['draft:one'] = ['system-prompt']
        self.assertTrue(DesktopPlugins.system_prompt_enabled(fake, record))
        record.id = 'persisted'
        fake.settings['sessions']['persisted'] = []
        self.assertFalse(DesktopPlugins.system_prompt_enabled(fake, record))


if __name__ == '__main__':
    unittest.main()
