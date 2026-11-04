"""Synthetic local protocol tests; no real providers or application profile."""
import json
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.gateway import Gateway
from app.integration import UnconfiguredAdapter
from app.request_diagnostics import RequestFailure


@contextmanager
def upstream(protocol, respond):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            received.append((self.path, body))
            status, response, stream = respond(body)
            raw = (('data: ' + json.dumps(response) + '\n\n').encode() if stream
                   else json.dumps(response).encode())
            self.send_response(status)
            self.send_header('Content-Type', 'text/event-stream' if stream else 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory() as temporary:
            provider = {'id': 'fixture', 'name': 'Fixture', 'api': 'anthropic' if protocol == 'anthropic' else 'openai',
                        'key': 'fixture-secret-key', 'baseUrl': f'http://127.0.0.1:{server.server_port}/v1',
                        'models': [{'upstream': 'real-model', 'alias': 'friendly',
                                    'reasoningLevels': ['low', 'high', 'xhigh'], 'reasoningLevelsAuto': False}]}
            if protocol == 'responses':
                provider['wireApi'] = 'responses'
            store = SimpleNamespace(directory=Path(temporary), data={'providers': [provider]})
            yield Gateway(store, UnconfiguredAdapter()), received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def success(protocol):
    if protocol == 'anthropic':
        return {'content': [{'type': 'text', 'text': 'O'}], 'stop_reason': 'max_tokens'}
    if protocol == 'responses':
        return {'object': 'response', 'status': 'incomplete', 'incomplete_details': {'reason': 'max_output_tokens'},
                'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'O'}]}]}
    return {'choices': [{'message': {'role': 'assistant', 'content': 'O'}, 'finish_reason': 'length'}]}


def rejection(allowed=True):
    message = "Unsupported value for reasoning_effort: 'xhigh'."
    if allowed:
        message += " Supported values are: 'low', 'high'."
    return {'type': 'error', 'error': {'type': 'invalid_request_error', 'param': 'reasoning_effort', 'message': message}}


class ReasoningGatewayTests(unittest.TestCase):
    def test_probe_uses_exact_protocol_and_no_parameter_baseline(self):
        for protocol in ('openai', 'responses', 'anthropic'):
            with self.subTest(protocol=protocol), upstream(protocol, lambda body: (200, success(protocol), False)) as (gateway, received):
                gateway.reasoning_rejected = lambda *args: self.fail('Probe called rejection callback')

                def detection(request):
                    request(None)
                    request('low')
                    return {'state': 'known', 'source': 'probe', 'levels': ['low']}

                with patch('app.gateway.detect_levels', side_effect=detection):
                    self.assertEqual(gateway.detect_reasoning_levels('friendly', 'fixture')['levels'], ['low'])
                self.assertEqual(len(received), 2)
                expected_path = {'openai': '/v1/chat/completions', 'responses': '/v1/responses', 'anthropic': '/v1/messages'}[protocol]
                for index, (path, body) in enumerate(received):
                    self.assertEqual(path, expected_path)
                    self.assertEqual(body['model'], 'real-model')
                    self.assertTrue(body['stream'])
                    self.assertNotIn('tools', body)
                    if protocol == 'responses':
                        self.assertEqual(body['max_output_tokens'], 1)
                        self.assertEqual(body['input'], [{'role': 'user', 'content': 'Reply OK.'}])
                        self.assertEqual(body.get('reasoning'), {'effort': 'low'} if index else None)
                        self.assertNotIn('reasoning_effort', body)
                    elif protocol == 'anthropic':
                        self.assertEqual(body['max_tokens'], 1)
                        self.assertEqual(body['messages'], [{'role': 'user', 'content': [{'type': 'text', 'text': 'Reply OK.'}]}])
                        self.assertEqual(body.get('output_config'), {'effort': 'low'} if index else None)
                        self.assertNotIn('reasoning_effort', body)
                    else:
                        self.assertEqual(body['max_tokens'], 1)
                        self.assertEqual(body['messages'], [{'role': 'user', 'content': 'Reply OK.'}])
                        self.assertEqual(body.get('reasoning_effort'), 'low' if index else None)
                self.assertFalse(gateway.diagnostics.directory.exists())

    def test_real_detection_consumes_sse_validation_without_chat_diagnostics(self):
        for protocol in ('openai', 'responses', 'anthropic'):
            def respond(body):
                effort = (body.get('reasoning_effort') if protocol == 'openai' else
                          body.get('reasoning', {}).get('effort') if protocol == 'responses' else
                          body.get('output_config', {}).get('effort'))
                return ((200, success(protocol), False) if effort is None or effort in ('low', 'high')
                        else (200, rejection(), True))

            with self.subTest(protocol=protocol), upstream(protocol, respond) as (gateway, received):
                gateway.reasoning_rejected = lambda *args: self.fail('Probe called rejection callback')
                detected = gateway.detect_reasoning_levels('friendly', 'fixture')
                self.assertEqual(detected['state'], 'known')
                self.assertEqual(detected['levels'], ['low', 'high'])
                self.assertTrue(received)
                self.assertFalse(gateway.diagnostics.directory.exists())

    def test_chat_rejection_notifies_once_and_never_resends_http_or_sse(self):
        for protocol in ('openai', 'responses', 'anthropic'):
            for stream in (False, True):
                with self.subTest(protocol=protocol, stream=stream), upstream(protocol, lambda body: (200 if stream else 400, rejection(), stream)) as (gateway, received):
                    callbacks = []
                    gateway.reasoning_rejected = lambda *args: callbacks.append(args)
                    with self.assertRaises(RequestFailure) as caught:
                        list(gateway.events('friendly', [{'role': 'user', 'content': 'chat'}],
                                            provider_id='fixture', parameters={'reasoning_effort': 'xhigh'}))
                    self.assertFalse(caught.exception.retryable)
                    self.assertEqual(callbacks, [('fixture', 'real-model', 'xhigh', ['low', 'high'])])
                    self.assertEqual(len(received), 1)
                    self.assertIn('off, low, high', str(caught.exception))
                    self.assertIn('重新发送', str(caught.exception))

    def test_rejection_without_alternatives_uses_cached_levels_and_redacts_key(self):
        error = rejection(False)
        error['error']['message'] += ' fixture-secret-key'
        with upstream('openai', lambda body: (400, error, False)) as (gateway, received):
            callbacks = []
            gateway.reasoning_rejected = lambda *args: callbacks.append(args)
            with self.assertRaises(RequestFailure) as caught:
                list(gateway.events('friendly', [{'role': 'user', 'content': 'chat'}],
                                    parameters={'reasoning_effort': 'xhigh'}))
            self.assertEqual(callbacks, [('fixture', 'real-model', 'xhigh', None)])
            self.assertIn('off, low, high', str(caught.exception))
            self.assertNotIn('fixture-secret-key', str(caught.exception))
            self.assertEqual(len(received), 1)

    def test_unrelated_failures_do_not_change_reasoning_capability(self):
        for status, error in ((401, rejection()), (429, rejection()),
                              (400, {'error': {'message': 'max_tokens must be at least 16', 'param': 'max_tokens'}})):
            with self.subTest(status=status, error=error), upstream('openai', lambda body: (status, error, False)) as (gateway, received):
                callbacks = []
                gateway.reasoning_rejected = lambda *args: callbacks.append(args)
                with self.assertRaises(RequestFailure):
                    list(gateway.events('friendly', [{'role': 'user', 'content': 'chat'}],
                                        parameters={'reasoning_effort': 'xhigh'}))
                self.assertEqual(callbacks, [])
                self.assertEqual(len(received), 1)

    def test_model_catalog_exports_raw_manual_levels_and_provider_identity(self):
        with upstream('openai', lambda body: (200, success('openai'), False)) as (gateway, _):
            model = gateway.models()[0]
            self.assertEqual(model['provider'], 'fixture')
            self.assertEqual(model['reasoningLevels'], ['low', 'high', 'xhigh'])
            self.assertEqual(model['reasoningState'], 'manual')


if __name__ == '__main__':
    unittest.main()
