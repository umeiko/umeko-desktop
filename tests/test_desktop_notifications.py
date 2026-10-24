import asyncio
import sys
import unittest
from unittest.mock import AsyncMock

if sys.platform.startswith('linux'):
    from app.desktop_notifications import DesktopCenter, SERVICE, PATH
    from dbus_next import Message, MessageType


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux desktop D-Bus transport')
class DesktopNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = DesktopCenter('/tmp/yanami.png')
        self.client.bus = AsyncMock()
        self.client.connection = asyncio.get_running_loop().create_future()
        self.client.connection.set_result(None)
        self.serial = 0
        async def call(message):
            if message.member == 'StartServiceByName': body, signature = [2], 'u'
            elif message.member == 'GetNameOwner': body, signature = [':1.42'], 's'
            else:
                self.assertEqual(message.member, 'Notify')
                self.assertEqual(message.signature, 'susssasa{sv}i')
                self.assertEqual(message.body[5], ['default', 'Open'])
                self.assertFalse(message.body[6]['suppress-sound'].value)
                self.serial += 1; body, signature = [self.serial], 'u'
            return Message(message_type=MessageType.METHOD_RETURN, reply_serial=1, signature=signature, body=body)
        self.client.bus.call.side_effect = call

    async def asyncTearDown(self):
        self.client.close()

    def signal(self, member, signature, body, sender=':1.42'):
        return Message(message_type=MessageType.SIGNAL, sender=sender, path=PATH, interface=SERVICE,
            member=member, signature=signature, body=body)

    async def test_notification_center_routes_older_entries_and_validates_sender(self):
        await self.client.notify('first', 'Completed', 'First task')
        await self.client.notify('second', 'Completed', 'Second task')
        self.client.message(self.signal('ActionInvoked', 'us', [2, 'default'], ':1.wrong'))
        self.assertIsNone(self.client.poll())
        self.client.message(self.signal('ActionInvoked', 'us', [2, 'default']))
        self.client.message(self.signal('NotificationClosed', 'uu', [1, 2]))
        self.assertEqual(self.client.poll(), 'clicked:second')
        self.assertEqual(self.client.poll(), 'dismissed:first')
        self.assertFalse(self.client.ids)

    async def test_service_is_activated_for_each_notification_after_suspend(self):
        await self.client.notify('first', 'Complete', 'Task')
        await self.client.notify('second', 'Complete', 'Task')
        methods = [call.args[0].member for call in self.client.bus.call.call_args_list]
        self.assertEqual(methods.count('StartServiceByName'), 2)
        self.assertEqual(methods.count('GetNameOwner'), 2)
