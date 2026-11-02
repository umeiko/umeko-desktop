"""The local fake provider binds locally and keeps its intended stream cadence."""
from http.server import BaseHTTPRequestHandler
import unittest
from unittest.mock import patch

from tests.reasoning_stream_fixture import _LoopbackServer, _paced_indices


class ReasoningFixtureTests(unittest.TestCase):
    def test_late_timer_wakeups_do_not_accumulate_stream_delay(self):
        from types import SimpleNamespace
        clock = SimpleNamespace(now=0.)
        def wait(delay):
            clock.now += delay + (.05 if delay > 0 else 0)
            return False
        stop = SimpleNamespace(wait=wait)
        with patch('tests.reasoning_stream_fixture.time.monotonic', side_effect=lambda: clock.now):
            self.assertEqual(list(_paced_indices(stop)), list(range(600)))
        self.assertGreaterEqual(clock.now, 15.)
        self.assertLessEqual(clock.now, 15.051)

    def test_pacing_stops_before_emitting_another_chunk(self):
        from threading import Event
        stop = Event()
        stop.set()
        self.assertEqual(list(_paced_indices(stop)), [])

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
