"""Freedesktop notifications with explicit D-Bus signatures on a worker loop."""
import asyncio
import queue
import threading
from dbus_next import Message, MessageType
from dbus_next.aio import MessageBus

SERVICE = 'org.freedesktop.Notifications'
PATH = '/org/freedesktop/Notifications'


class DesktopCenter:
    def __init__(self, icon):
        self.icon = icon
        self.events = queue.SimpleQueue()
        self.ids = {}
        self.loop = asyncio.new_event_loop()
        self.thread = None
        self.connection = None
        self.bus = None
        self.owner = ''
        self.closing = False

    async def connect(self):
        self.bus = await MessageBus().connect()
        for member in ('ActionInvoked', 'NotificationClosed'):
            rule = f"type='signal',sender='{SERVICE}',path='{PATH}',interface='{SERVICE}',member='{member}'"
            reply = await self.bus.call(Message(destination='org.freedesktop.DBus', path='/org/freedesktop/DBus',
                interface='org.freedesktop.DBus', member='AddMatch', signature='s', body=[rule]))
            if reply.message_type == MessageType.ERROR: raise RuntimeError(reply.error_name)
        self.bus.add_message_handler(self.message)

    async def ensure_server(self):
        # Desktop daemons can be activated lazily (including after suspend).
        reply = await self.bus.call(Message(destination='org.freedesktop.DBus', path='/org/freedesktop/DBus',
            interface='org.freedesktop.DBus', member='StartServiceByName', signature='su', body=[SERVICE, 0]))
        if reply.message_type == MessageType.ERROR: raise RuntimeError(reply.error_name)
        reply = await self.bus.call(Message(destination='org.freedesktop.DBus', path='/org/freedesktop/DBus',
            interface='org.freedesktop.DBus', member='GetNameOwner', signature='s', body=[SERVICE]))
        if reply.message_type == MessageType.ERROR: raise RuntimeError(reply.error_name)
        if self.owner != reply.body[0]: self.ids.clear()
        self.owner = reply.body[0]

    def message(self, message):
        if message.message_type != MessageType.SIGNAL or message.sender != self.owner: return
        if message.path != PATH or message.interface != SERVICE or not message.body: return
        if message.member == 'ActionInvoked' and len(message.body) == 2 and message.body[1] == 'default':
            token = self.ids.pop(message.body[0], '')
            if token: self.events.put('clicked:' + token)
        elif message.member == 'NotificationClosed':
            token = self.ids.pop(message.body[0], '')
            if token: self.events.put('dismissed:' + token)

    async def notify(self, identifier, title, body):
        from dbus_next import Variant
        try:
            if self.connection is None: self.connection = asyncio.create_task(self.connect())
            await self.connection
            await self.ensure_server()
            hints = {'sound-name': Variant('s', 'complete'), 'suppress-sound': Variant('b', False), 'transient': Variant('b', False)}
            reply = await self.bus.call(Message(destination=SERVICE, path=PATH, interface=SERVICE, member='Notify',
                signature='susssasa{sv}i', body=['Umeko', 0, self.icon, title, body, ['default', 'Open'], hints, -1]))
            if reply.message_type == MessageType.ERROR: raise RuntimeError(reply.error_name)
            self.ids[int(reply.body[0])] = identifier
            while len(self.ids) > 128: self.ids.pop(next(iter(self.ids)))
        except Exception:
            self.events.put('failed:' + identifier)
            self.connection = None
            if self.bus is not None: self.bus.disconnect()

    def send(self, identifier, title, body):
        if self.closing: return -1
        if self.thread is None:
            def run():
                asyncio.set_event_loop(self.loop)
                try: self.loop.run_forever()
                finally:
                    pending = asyncio.all_tasks(self.loop)
                    for task in pending: task.cancel()
                    self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    self.loop.close()
            self.thread = threading.Thread(target=run, name='Umeko desktop notifications', daemon=True)
            self.thread.start()
        asyncio.run_coroutine_threadsafe(self.notify(identifier, title, body), self.loop)
        return 1

    def poll(self):
        try: return self.events.get_nowait()
        except queue.Empty: return None

    def close(self):
        if self.closing: return
        self.closing = True
        if self.thread is not None:
            def stop():
                if self.bus is not None: self.bus.disconnect()
                self.loop.stop()
            self.loop.call_soon_threadsafe(stop)
        else: self.loop.close()
