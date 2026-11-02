"""The local fake provider must start without contacting a DNS resolver."""
from http.server import BaseHTTPRequestHandler
import unittest
from unittest.mock import patch

from tests.reasoning_stream_fixture import _LoopbackServer


class ReasoningFixtureTests(unittest.TestCase):
    def test_loopback_binding_does_not_perform_reverse_dns(self):
        with patch('socket.getfqdn', side_effect=AssertionError('Unexpected DNS query')) as lookup:
            server = _LoopbackServer(('127.0.0.1', 0), BaseHTTPRequestHandler)
            try:
                self.assertEqual(server.server_name, 'localhost')
                self.assertGreater(server.server_port, 0)
                self.assertEqual(server.socket.getsockname(), server.server_address)
                lookup.assert_not_called()
            finally:
                server.server_close()
