"""Login policy uses the existing listener and a profile-scoped instance lock."""
import http.client
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QObject, Signal

from app.login_session import LoginStartupSettings, acquire_instance, instance_for_launch, start_login_proxy

APP = QCoreApplication.instance() or QCoreApplication([])
ROOT = Path(__file__).resolve().parents[1]


class FakeManager:
    def __init__(self):
        self.value = {'available': True, 'reason': '', 'umeko': False, 'proxy': False}

    def refresh(self):
        return dict(self.value)

    def set_enabled(self, umeko, proxy):
        self.value.update(umeko=umeko, proxy=proxy)
        return self.refresh()


class Owner(QObject):
    toast = Signal(str)


class LoginSessionTests(unittest.TestCase):
    def test_background_tray_and_minimized_fallback_do_not_notify(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from PySide6.QtGui import QWindow
        from app.tray import TrayController
        for available in (True, False):
            window, tray = Mock(), Mock()
            window.visibility.return_value = QWindow.Hidden
            tray.icon.return_value.isNull.return_value = False
            owner = SimpleNamespace(window=window, tray=tray, tray_available=lambda: available,
                                    english=True, notificationRequested=Mock())
            TrayController.minimize_to_tray(owner, notify=False)
            if available:
                window.hide.assert_called_once()
                window.showMinimized.assert_not_called()
            else:
                window.showMinimized.assert_called_once()
            owner.notificationRequested.emit.assert_not_called()
            tray.showMessage.assert_not_called()

    def test_bridge_refreshes_system_state_and_reports_failure(self):
        owner, manager = Owner(), FakeManager()
        bridge = LoginStartupSettings(owner, manager=manager, background=True)
        self.assertTrue(bridge.background)
        bridge.setEnabled(True, True)
        self.assertTrue(bridge.state['umeko'] and bridge.state['proxy'])
        manager.value.update(umeko=False, proxy=False)
        bridge.refresh()
        self.assertFalse(bridge.state['umeko'] or bridge.state['proxy'])
        messages = []
        owner.toast.connect(messages.append)
        with patch.object(manager, 'set_enabled', side_effect=OSError('denied')):
            bridge.setEnabled(True, False)
        self.assertEqual(messages, ['保存开机启动设置失败。'])

    def test_only_one_instance_per_profile_and_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            first = acquire_instance(directory)
            self.assertIsNotNone(first)
            try:
                self.assertIsNone(acquire_instance(directory))
                other = acquire_instance(directory / 'other-profile')
                self.assertIsNotNone(other)
                other.unlock()
            finally:
                first.unlock()
            replacement = acquire_instance(directory)
            self.assertIsNotNone(replacement)
            replacement.unlock()

    def test_manual_launches_continue_with_free_or_busy_lock_but_login_skips(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            manual, proceed = instance_for_launch(directory, [])
            self.assertTrue(proceed)
            self.assertIsNotNone(manual)
            try:
                second_manual, proceed = instance_for_launch(directory, [])
                self.assertTrue(proceed)
                self.assertIsNone(second_manual)
                login, proceed = instance_for_launch(directory, ['--login-startup', '--login-proxy'])
                self.assertFalse(proceed)
                self.assertIsNone(login)
            finally:
                manual.unlock()
            login, proceed = instance_for_launch(directory, ['--login-startup'])
            self.assertTrue(proceed)
            self.assertIsNotNone(login)
            try:
                manual, proceed = instance_for_launch(directory, [])
                self.assertTrue(proceed)
                self.assertIsNone(manual)
            finally:
                login.unlock()

    def test_manual_launch_continues_when_lock_directory_is_unavailable(self):
        with patch('app.login_session.acquire_instance', side_effect=PermissionError('denied')):
            self.assertEqual(instance_for_launch(Path('unused'), []), (None, True))

    def test_installer_does_not_acquire_a_lock(self):
        with patch('app.login_session.acquire_instance') as acquire:
            self.assertEqual(instance_for_launch(Path('unused'), ['--install-update']), (None, True))
            acquire.assert_not_called()

    def test_login_recovers_lock_left_by_an_exited_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            child = subprocess.run([sys.executable, '-c',
                'import os, sys; from pathlib import Path; '
                'from app.login_session import acquire_instance; '
                'lock = acquire_instance(Path(sys.argv[1])); '
                'os._exit(0 if lock is not None else 1)', str(directory)],
                cwd=ROOT, capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            self.assertEqual(child.returncode, 0, child.stderr)
            self.assertTrue((directory / 'desktop-instance.lock').is_file())
            lock, proceed = instance_for_launch(directory, ['--login-startup'])
            self.assertTrue(proceed)
            self.assertIsNotNone(lock)
            lock.unlock()

    def test_login_proxy_uses_real_controller_listener_once_with_both_flags(self):
        from app.controller import Controller
        from app.storage import Store
        from app.api_keys import make_key
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
                'UMEKO_DATA_DIR': temporary, 'PI_CODING_AGENT_DIR': str(Path(temporary) / 'agent')}):
            store = Store()
            store.data['server'].update(port=0, keys=[make_key('Fixture', 'fixture-login-key-12345678901234567890')])
            store.save()
            controller = Controller(ROOT)
            try:
                start_login_proxy(controller, [])
                self.assertFalse(controller.serverRunning)
                start_login_proxy(controller, ['--login-startup', '--login-umeko'])
                self.assertFalse(controller.serverRunning)
                flags = ['--login-startup', '--login-umeko', '--login-proxy']
                start_login_proxy(controller, flags)
                server = controller.public_server
                self.assertIsNotNone(server)
                self.assertEqual(server.host, '127.0.0.1')
                start_login_proxy(controller, flags)
                self.assertIs(controller.public_server, server)
                connection = http.client.HTTPConnection('127.0.0.1', server.port, timeout=3)
                try:
                    connection.request('GET', '/v1/models')
                    response = connection.getresponse()
                    self.assertEqual(response.status, 401)
                    response.read()
                finally:
                    connection.close()
            finally:
                controller.close()

    def test_login_proxy_does_not_create_credentials_or_bypass_key_requirement(self):
        from app.controller import Controller
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
                'UMEKO_DATA_DIR': temporary, 'PI_CODING_AGENT_DIR': str(Path(temporary) / 'agent')}):
            controller = Controller(ROOT)
            try:
                start_login_proxy(controller, ['--login-startup', '--login-proxy'])
                self.assertFalse(controller.serverRunning)
                self.assertEqual(controller.store.data['server']['keys'], [])
            finally:
                controller.close()


if __name__ == '__main__':
    unittest.main()
