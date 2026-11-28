"""Background jobs and the settings snapshot they used to refresh."""
import os
import unittest
from unittest.mock import Mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from app.controller import Controller


class JobNotificationTests(unittest.TestCase):
    def controller(self):
        controller = Mock()
        controller._closing = False
        return controller

    def test_group_chat_jobs_do_not_notify_settings(self):
        # A history poll runs every few seconds while the group page is open.
        # It only answers through the chat reply signal, so it must not wake
        # every binding that reads backend.config.
        for name in ('group-chat:0123456789abcdef', 'group-chat:copy', 'group-chat:save'):
            controller = self.controller()
            Controller._on_job_done(controller, name, {'ok': True, 'value': {}})
            controller.changed.emit.assert_not_called()

    def test_other_jobs_still_notify_settings(self):
        controller = self.controller()
        controller.kernelVersion = '1.0.0'
        Controller._on_job_done(controller, 'check', {'ok': True, 'value': '2.0.0'})
        controller.changed.emit.assert_called_once_with()
        self.assertEqual(controller._kernel_status, '发现可用版本 2.0.0')


if __name__ == '__main__':
    unittest.main()
