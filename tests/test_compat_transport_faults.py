"""Local HTTP faults, Retry-After waits and stream replay boundaries.

When loaded against the unmodified baseline, the absent compatibility helper
uses that version's direct urllib open so missing retry behavior is observable.
"""
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import http.client
import importlib
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from umeko_provider_sdk import ProviderError
from umeko_provider_sdk.http import HttpSession
from umeko_provider_sdk.network import network_scope

try:
    compatibility = importlib.import_module('umeko_provider_sdk.compatibility')
except ModuleNotFoundError:
    compatibility = None

TEMP_ROOT = Path('C:/UmekoTests/p124')
TEMP_ROOT.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TEMP_ROOT)
os.environ['TMP'] = os.environ['TEMP'] = str(TEMP_ROOT)


def open_compatible(opener, request, **kwargs):
    if compatibility is None:
        return opener.open(request, timeout=kwargs.get('timeout', 20))
    return compatibility.compatible_open(opener, request, **kwargs)


class RecordingCancellation:
    def __init__(self):
        self.waits = []

    def is_set(self):
        return False

    def wait(self, seconds):
        self.waits.append(seconds)
        return False


class TransportFaultTests(unittest.TestCase):
    def setUp(self):
        self.mode = 'transient'
        self.calls = 0
        self.retry_header = ('Retry-After', '0')
        self.partial = b'data: {"delta":"visible token"}\n\n'
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                owner.calls += 1
                if owner.mode == 'closed':
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                if owner.mode == 'timeout':
                    time.sleep(.2)
                if owner.mode == 'partial':
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream')
                    self.send_header('Content-Length', str(len(owner.partial) + 100))
                    self.end_headers()
                    self.wfile.write(owner.partial)
                    self.wfile.flush()
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                status = 429 if owner.mode == 'transient' and owner.calls == 1 else 200
                raw = json.dumps({'error': {'message': 'fixture rate limit'}} if status == 429 else {'data': []}).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                if status == 429:
                    self.send_header(*owner.retry_header)
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except (ConnectionError, OSError):
                    pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.url = f'http://127.0.0.1:{self.server.server_port}/v1/models'
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def assert_sdk_fault(self, expected):
        records = []
        session = HttpSession([self.url], environment_proxy=False)
        with network_scope(records=records), self.assertRaises(ProviderError):
            session.request(self.url, timeout=.05)
        self.assertEqual(self.calls, 1)
        self.assertEqual(len(records), 1)
        self.assertRegex(records[0].get('exception', ''), expected)

    def test_close_before_headers_preserves_cause_without_replay(self):
        self.mode = 'closed'
        self.assert_sdk_fault('(?i)closed|reset|aborted|disconnected')

    def test_timeout_preserves_cause_without_replay(self):
        self.mode = 'timeout'
        self.assert_sdk_fault('(?i)timed out|timeout')

    def assert_wait(self, header, expected=None):
        self.retry_header = header
        cancelled = RecordingCancellation()
        records = []
        fixed_now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        clock = patch.object(compatibility, 'datetime') if compatibility else nullcontext()
        with clock as mocked_clock:
            if mocked_clock is not None:
                mocked_clock.now.return_value = fixed_now
            with open_compatible(self.opener, urllib.request.Request(self.url),
                                 cancelled=cancelled, records=records) as response:
                self.assertEqual(json.load(response), {'data': []})
        self.assertEqual(self.calls, 2)
        self.assertEqual(len(cancelled.waits), 1)
        if expected is None:
            self.assertGreaterEqual(cancelled.waits[0], .375)
            self.assertLessEqual(cancelled.waits[0], .5)
        else:
            self.assertAlmostEqual(cancelled.waits[0], expected)
        if compatibility:
            self.assertEqual([r['response']['status'] for r in records], [429, 200])

    def test_retry_after_http_date(self):
        deadline = datetime(2030, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=7)
        self.assert_wait(('Retry-After', format_datetime(deadline, usegmt=True)), 7)

    def test_retry_after_milliseconds(self):
        self.assert_wait(('Retry-After-Ms', '1250'), 1.25)

    def test_retry_after_nonzero_seconds(self):
        self.assert_wait(('Retry-After', '2.5'), 2.5)

    def test_retry_after_invalid_header_uses_bounded_fallback(self):
        self.assert_wait(('Retry-After', 'invalid-fixture-date'))

    def test_cancellation_interrupts_retry_wait_without_replay(self):
        self.retry_header = ('Retry-After', '20')
        cancelled = threading.Event()
        timer = threading.Timer(.05, cancelled.set)
        timer.daemon = True
        timer.start()
        self.addCleanup(timer.cancel)
        started = time.monotonic()
        with self.assertRaisesRegex(InterruptedError, '取消'):
            open_compatible(self.opener, urllib.request.Request(self.url), cancelled=cancelled)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(self.calls, 1)

    def test_partial_stream_is_not_replayed_after_visible_output(self):
        self.mode = 'partial'
        records = []
        with open_compatible(self.opener, urllib.request.Request(self.url), records=records) as response:
            visible = response.read1(len(self.partial))
            self.assertEqual(visible, self.partial)
            with self.assertRaises(http.client.IncompleteRead):
                response.read()
        self.assertEqual(self.calls, 1)


if __name__ == '__main__':
    unittest.main()
