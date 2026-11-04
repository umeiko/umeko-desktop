"""Real background desktop/proxy path, with native tray/notifications isolated."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
                  QT_QUICK_CONTROLS_STYLE='Basic')

from PySide6.QtCore import QObject, Signal
from PySide6.QtQuick import QQuickWindow


class TrayFixture(QObject):
    quitRequested = Signal()
    notificationRequested = Signal(str)

    def __init__(self, window, icon, owner):
        super().__init__(owner)
        self.tray = None

    def set_language(self, language):
        pass

    def restore(self):
        raise AssertionError('Background login must not restore the main window')

    def minimize_to_tray(self, notify=True):
        assert not notify, 'Login startup must not send a native notification'


class NotificationFixture(QObject):
    activated = Signal(str)

    def __init__(self, window, tray, root, owner):
        super().__init__(owner)

    def task_finished(self, *args):
        raise AssertionError('No login task should send a notification')


def main():
    with tempfile.TemporaryDirectory(prefix='umeko-login-launch-') as temporary, patch.dict(os.environ, {
            'UMEKO_DATA_DIR': temporary, 'PI_CODING_AGENT_DIR': str(Path(temporary) / 'agent')}):
        from app.storage import Store
        from app.api_keys import make_key
        store = Store()
        store.data['desktop']['webDisplay'] = 'external'
        store.data['server'].update(port=0, keys=[make_key('Fixture', 'fixture-login-launch-12345678901234567890')])
        store.save()
        from main import create_application
        with patch.object(sys, 'argv', [sys.argv[0], '--login-startup', '--login-umeko', '--login-proxy']), \
                patch('app.tray.TrayController', TrayFixture), \
                patch('app.notifications.TaskNotifications', NotificationFixture):
            app, engine, backend = create_application()
            try:
                window = engine.rootObjects()[0]
                assert isinstance(window, QQuickWindow)
                assert not window.isVisible(), 'The main window was shown during construction'
                app.processEvents()  # Deliver the queued existing-proxy startup.
                assert not window.isVisible(), 'The login startup opened the main window'
                assert backend.serverRunning and backend.public_server.host == '127.0.0.1'
                from app.login_session import start_login_proxy
                server = backend.public_server
                start_login_proxy(backend, sys.argv)
                assert backend.public_server is server
                assert backend._view.process is None
                print('LOGIN_STARTUP_LAUNCH_OK: real QML stays hidden; both flags reuse one existing proxy listener')
            finally:
                backend.close()
                import shiboken6
                shiboken6.delete(engine)
                app.processEvents()


if __name__ == '__main__':
    main()
