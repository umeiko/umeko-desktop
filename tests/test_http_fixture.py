import os
import socket
import struct
import unittest

from tests.http_fixture import peer_disconnected


class PeerDisconnectTests(unittest.TestCase):
    def connection(self):
        listener = socket.socket()
        self.addCleanup(listener.close)
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        client = socket.create_connection(listener.getsockname())
        self.addCleanup(client.close)
        server, _ = listener.accept()
        self.addCleanup(server.close)
        server.settimeout(1)
        return client, server

    def test_orderly_tcp_close_is_a_disconnect(self):
        client, server = self.connection()
        client.shutdown(socket.SHUT_WR)
        self.assertTrue(peer_disconnected(server))

    def test_tcp_reset_is_a_disconnect(self):
        client, server = self.connection()
        linger = struct.pack('HH' if os.name == 'nt' else 'ii', 1, 0)
        client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger)
        client.close()
        self.assertTrue(peer_disconnected(server))

    def test_open_connection_timeout_is_not_a_disconnect(self):
        _, server = self.connection()
        server.settimeout(.05)
        with self.assertRaises(TimeoutError):
            peer_disconnected(server)

    def test_received_data_is_not_a_disconnect(self):
        client, server = self.connection()
        client.sendall(b'x')
        self.assertFalse(peer_disconnected(server))
