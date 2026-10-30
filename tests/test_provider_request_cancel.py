"""The local gateway exposes peer cancellation before any provider token."""
import http.client
import json
import threading
import unittest

from app.gateway import LocalServer
from umeko_provider_sdk import ProviderContext


class RequestCancellationTests(unittest.TestCase):
    def test_quiet_provider_observes_disconnect_without_global_cancellation(self):
        started, stopped = threading.Event(), threading.Event()
        context = ProviderContext({}, None, None)
        class QuietGateway:
            def events(self, *args, **kwargs):
                local = context.request_cancelled
                started.set()
                if local.wait(3):
                    stopped.set()
                if False:
                    yield {}
        server = LocalServer(QuietGateway(), 0, 'synthetic-local-token', private=True)
        connection = http.client.HTTPConnection('127.0.0.1', server.httpd.server_port, timeout=3)
        try:
            connection.request('POST', '/v1/chat/completions',
                json.dumps({'model':'fixture','messages':[{'role':'user','content':'wait'}],'stream':True}),
                {'Authorization':'Bearer synthetic-local-token','Content-Type':'application/json'})
            self.assertTrue(started.wait(2))
            connection.close()
            self.assertTrue(stopped.wait(2))
            self.assertFalse(context.cancelled.is_set())
        finally:
            connection.close()
            server.close()


if __name__ == '__main__':
    unittest.main()
