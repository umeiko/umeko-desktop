"""Exercise compatible-service recovery through real loopback HTTP requests."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.gateway import Gateway, LocalServer
from app.integration import UnconfiguredAdapter


class Service:
    def __init__(self, reply):
        self.requests = []
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests.append(body)
                status, payload, headers = reply(body, len(owner.requests))
                raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'text/event-stream' if isinstance(payload, bytes) else 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                for key, value in headers.items(): self.send_header(key, value)
                self.end_headers()
                self.wfile.write(raw)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}/v1'

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


OK = {'choices': [{'message': {'role': 'assistant', 'content': 'OK'}, 'finish_reason': 'stop'}]}
MESSAGES = [{'role': 'user', 'content': 'Reply OK'}]
TOOLS = [{'name': 'lookup', 'parameters': {'type': 'object', 'properties': {}}}]


class GatewayCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def gateway(self, reply, **provider_options):
        service = Service(reply)
        self.addCleanup(service.close)
        provider = {'id': 'fixture', 'name': 'Fixture', 'api': 'openai',
                    'baseUrl': service.base, 'key': 'fixture-key', 'proxy': {'mode': 'direct'},
                    'models': [{'alias': 'fixture', 'upstream': 'fixture', 'reasoningFormat': 'deepseek'}],
                    **provider_options}
        store = SimpleNamespace(directory=Path(self.temp.name), data={'providers': [provider]})
        return Gateway(store, UnconfiguredAdapter()), service, store

    def test_required_choice_falls_back_to_auto_and_keeps_tools(self):
        def reply(body, count):
            if body.get('tool_choice') == 'required':
                return 400, {'error': {'message': 'tool_choice required is not supported in thinking mode', 'param': 'tool_choice'}}, {}
            return 200, OK, {}
        gateway, service, store = self.gateway(reply)
        params = {'tool_choice': 'required', '_umeko_auto_parameters': ['tool_choice']}
        self.assertEqual(gateway.complete('fixture', MESSAGES, TOOLS, parameters=params).text, 'OK')
        self.assertEqual(service.requests[1]['tool_choice'], 'auto')
        self.assertTrue(service.requests[1]['tools'])
        restored = Gateway(store, UnconfiguredAdapter())
        self.assertEqual(restored.complete('fixture', MESSAGES, TOOLS, parameters=params).text, 'OK')
        self.assertEqual(len(service.requests), 3)
        self.assertEqual(service.requests[-1]['tool_choice'], 'auto')

    def test_automatically_mapped_thinking_is_removed_after_named_rejection(self):
        def reply(body, count):
            if 'thinking' in body:
                return 400, {'error': {'type': 'UnsupportedParamsError', 'message': "unsupported parameters: ['thinking']"}}, {}
            return 200, OK, {}
        gateway, service, _ = self.gateway(reply)
        self.assertEqual(gateway.complete('fixture', MESSAGES, parameters={'_umeko_reasoning_effort': 'high'}).text, 'OK')
        self.assertNotIn('thinking', service.requests[-1])
        self.assertEqual(service.requests[-1]['reasoning_effort'], 'high')

    def test_validation_location_identifies_the_automatic_parameter(self):
        def reply(body, count):
            if 'reasoning_effort' in body:
                return 400, {'detail': [{'loc': ['body', 'reasoning_effort'], 'type': 'literal_error', 'msg': 'Input should be low or high'}]}, {}
            return 200, OK, {}
        gateway, service, _ = self.gateway(reply)
        self.assertEqual(gateway.complete('fixture', MESSAGES, parameters={
            'reasoning_effort': 'medium', '_umeko_auto_parameters': ['reasoning_effort']}).text, 'OK')
        self.assertNotIn('reasoning_effort', service.requests[-1])

    def test_user_configured_parameter_is_preserved(self):
        gateway, service, _ = self.gateway(lambda body, n: (400, {'error': {
            'type': 'UnsupportedParamsError', 'message': 'thinking rejected', 'param': 'thinking'}}, {}))
        with self.assertRaisesRegex(Exception, 'thinking'):
            gateway.complete('fixture', MESSAGES, parameters={'thinking': {'type': 'enabled'}})
        self.assertEqual(len(service.requests), 1)
        self.assertEqual(service.requests[0]['thinking'], {'type': 'enabled'})

    def test_unrelated_bad_request_is_not_retried(self):
        gateway, service, _ = self.gateway(lambda body, n: (400, {'error': {'message': 'messages is malformed', 'param': 'messages'}}, {}))
        with self.assertRaisesRegex(Exception, 'messages'):
            gateway.complete('fixture', MESSAGES, parameters={'seed': 1, '_umeko_auto_parameters': ['seed']})
        self.assertEqual(len(service.requests), 1)

    def test_silent_drop_is_success_without_rejection_memory(self):
        gateway, service, _ = self.gateway(lambda body, n: (200, OK, {}))
        params = {'seed': 7, '_umeko_auto_parameters': ['seed']}
        for _ in range(2): self.assertEqual(gateway.complete('fixture', MESSAGES, parameters=params).text, 'OK')
        self.assertEqual([row['seed'] for row in service.requests], [7, 7])

    def test_rate_limit_honours_retry_after_and_retries_once(self):
        gateway, service, _ = self.gateway(lambda body, n: (429, {'error': {'message': 'slow down'}}, {'Retry-After': '0'}) if n == 1 else (200, OK, {}))
        self.assertEqual(gateway.complete('fixture', MESSAGES).text, 'OK')
        self.assertEqual(len(service.requests), 2)

    def test_service_unavailable_recovers(self):
        gateway, service, _ = self.gateway(lambda body, n: (503, {'error': {'message': 'busy'}}, {'Retry-After': '0'}) if n == 1 else (200, OK, {}))
        self.assertEqual(gateway.complete('fixture', MESSAGES).text, 'OK')
        self.assertEqual(len(service.requests), 2)

    def test_auth_and_missing_routes_keep_the_cause_and_single_attempt(self):
        for status in (401, 403, 404, 500):
            with self.subTest(status=status):
                gateway, service, _ = self.gateway(lambda body, n, status=status: (status, {'error': {'message': 'fixture cause', 'param': 'fixture-field'}}, {}))
                with self.assertRaisesRegex(Exception, 'fixture cause'):
                    gateway.complete('fixture', MESSAGES)
                self.assertEqual(len(service.requests), 1)

    def test_http_200_error_keeps_real_cause(self):
        gateway, _, _ = self.gateway(lambda body, n: (200, {'error': {'message': 'bad response_format', 'param': 'response_format'}}, {}))
        with self.assertRaisesRegex(Exception, 'response_format'):
            gateway.complete('fixture', MESSAGES)

    def test_auto_default_token_limit_can_be_removed(self):
        gateway, service, _ = self.gateway(lambda body, n: (400, {'error': {'message': 'max_tokens unsupported; use max_completion_tokens', 'param': 'max_tokens'}}, {}) if 'max_tokens' in body else (200, OK, {}))
        self.assertEqual(gateway.complete('fixture', MESSAGES).text, 'OK')
        self.assertNotIn('max_tokens', service.requests[-1])

    def test_explicit_token_limit_keeps_its_name_and_value(self):
        gateway, service, _ = self.gateway(lambda body, n: (200, OK, {}))
        gateway.complete('fixture', MESSAGES, max_tokens=17, parameters={'max_completion_tokens': 23})
        self.assertEqual(service.requests[0].get('max_completion_tokens'), 23)
        self.assertNotIn('max_tokens', service.requests[0])

    def test_other_automatic_fields_follow_the_same_named_rejection_rule(self):
        values = {'response_format': {'type': 'json_object'}, 'stream_options': {'include_usage': True},
                  'parallel_tool_calls': True, 'temperature': .5, 'top_p': .9,
                  'dimensions': 32, 'user': 'fixture-user', 'seed': 7, 'n': 1}
        for name, value in values.items():
            with self.subTest(parameter=name):
                gateway, service, _ = self.gateway(lambda body, n, name=name: (400, {'error': {
                    'message': name + ' is not supported', 'param': name}}, {}) if name in body else (200, OK, {}))
                self.assertEqual(gateway.complete('fixture', MESSAGES, parameters={name: value, '_umeko_auto_parameters': [name]}).text, 'OK')
                self.assertNotIn(name, service.requests[-1])

    def test_learned_rejection_does_not_strip_a_later_user_value(self):
        gateway, service, _ = self.gateway(lambda body, n: (400, {'error': {
            'message': 'seed not supported', 'param': 'seed'}}, {}) if n == 1 else (200, OK, {}))
        gateway.complete('fixture', MESSAGES, parameters={'seed': 1, '_umeko_auto_parameters': ['seed']})
        gateway.complete('fixture', MESSAGES, parameters={'seed': 2})
        self.assertEqual(service.requests[-1]['seed'], 2)

    def test_rejection_memory_is_scoped_to_provider_address_and_model(self):
        gateway, service, store = self.gateway(lambda body, n: (400, {'error': {
            'message': 'seed not supported', 'param': 'seed'}}, {}) if n == 1 else (200, OK, {}))
        params = {'seed': 1, '_umeko_auto_parameters': ['seed']}
        gateway.complete('fixture', MESSAGES, parameters=params)
        for key, value in (('id', 'other-provider'), ('baseUrl', service.base + '/other')):
            original = store.data['providers'][0][key]
            store.data['providers'][0][key] = value
            gateway.complete('fixture', MESSAGES, parameters=params)
            self.assertEqual(service.requests[-1]['seed'], 1)
            store.data['providers'][0][key] = original
        store.data['providers'][0]['models'][0]['upstream'] = 'other-model'
        gateway.complete('fixture', MESSAGES, parameters=params)
        self.assertEqual(service.requests[-1]['seed'], 1)

    def test_parameter_recovery_replays_only_once(self):
        gateway, service, _ = self.gateway(lambda body, n: (400, {'error': {
            'message': ('seed' if n == 1 else 'n') + ' unsupported',
            'param': 'seed' if n == 1 else 'n'}}, {}))
        with self.assertRaisesRegex(Exception, 'unsupported'):
            gateway.complete('fixture', MESSAGES, parameters={'seed': 1, 'n': 1, '_umeko_auto_parameters': ['seed', 'n']})
        self.assertEqual(len(service.requests), 2)

    def test_transient_retry_cap_and_long_retry_after(self):
        for status, headers, count in ((429, {'Retry-After': '0'}, 3), (503, {'Retry-After': '0'}, 3),
                                       (429, {'Retry-After': '120'}, 1)):
            with self.subTest(status=status, headers=headers):
                gateway, service, _ = self.gateway(lambda body, n, status=status, headers=headers: (status, {'error': {'message': 'busy'}}, headers))
                with self.assertRaisesRegex(Exception, 'busy'):
                    gateway.complete('fixture', MESSAGES)
                self.assertEqual(len(service.requests), count)

    def test_rate_limit_without_header_waits_before_retry(self):
        gateway, service, _ = self.gateway(lambda body, n: (429, {'error': {'message': 'busy'}}, {}) if n == 1 else (200, OK, {}))
        started = time.monotonic()
        self.assertEqual(gateway.complete('fixture', MESSAGES).text, 'OK')
        self.assertGreaterEqual(time.monotonic() - started, .35)

    def test_public_proxy_preserves_user_fields_and_ignores_auto_metadata(self):
        import urllib.request
        gateway, service, _ = self.gateway(lambda body, n: (200, OK, {}))
        server = LocalServer(gateway, 0, 'fixture-key')
        self.addCleanup(server.close)
        fields = {'response_format': {'type': 'json_object'}, 'stream_options': {'include_usage': True},
                  'max_completion_tokens': 23, 'seed': 7, 'user': 'fixture-user', 'n': 1,
                  'custom_option': {'enabled': True}, 'thinking': {'type': 'enabled'}}
        body = {'model': 'fixture', 'messages': MESSAGES, **fields, '_umeko_auto_parameters': list(fields)}
        request = urllib.request.Request(f'http://127.0.0.1:{server.port}/v1/chat/completions',
            data=json.dumps(body).encode(), headers={'Authorization': 'Bearer fixture-key', 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)
        for key, value in fields.items(): self.assertEqual(service.requests[-1][key], value)
        self.assertNotIn('max_tokens', service.requests[-1])
        self.assertNotIn('_umeko_auto_parameters', service.requests[-1])

    def test_nested_automatic_tool_fields_recover_and_user_strict_is_preserved(self):
        result = {'object': 'response', 'status': 'completed', 'output': [
            {'type': 'message', 'content': [{'type': 'output_text', 'text': 'OK'}]}]}
        def reply(body, count):
            if 'strict' in body['tools'][0]:
                return 400, {'error': {'message': 'strict not supported', 'param': 'tools[0].strict'}}, {}
            return 200, result, {}
        gateway, service, _ = self.gateway(reply, wireApi='responses')
        self.assertEqual(gateway.complete('fixture', MESSAGES, TOOLS).text, 'OK')
        self.assertNotIn('strict', service.requests[-1]['tools'][0])
        explicit = [{**TOOLS[0], 'strict': True}]
        with self.assertRaisesRegex(Exception, 'strict'):
            gateway.complete('fixture', MESSAGES, explicit)
        self.assertIs(service.requests[-1]['tools'][0]['strict'], True)

    def test_invalid_millisecond_header_uses_valid_retry_after_seconds(self):
        from umeko_provider_sdk.compatibility import retry_delay
        self.assertEqual(retry_delay({'Retry-After-Ms': 'invalid', 'Retry-After': '2.5'}, 0), 2.5)

    def test_null_keepalive_frame_allows_later_stream_output(self):
        final = {'choices': [{'delta': {'content': 'OK'}, 'finish_reason': 'stop'}]}
        stream = b'data: null\n\ndata: {}\n\n' + b'data: ' + json.dumps(final).encode() + b'\n\n'
        gateway, _, _ = self.gateway(lambda body, n: (200, stream, {}))
        self.assertEqual(gateway.complete('fixture', MESSAGES).text, 'OK')

    def test_http_200_explicit_failure_status_retains_cause(self):
        for payload in ({'success': False, 'message': 'response_format rejected', 'param': 'response_format'},
                        {'status': 'failed', 'message': 'response_format rejected', 'param': 'response_format'}):
            with self.subTest(payload=payload):
                gateway, _, _ = self.gateway(lambda body, n, payload=payload: (200, payload, {}))
                with self.assertRaisesRegex(Exception, 'response_format rejected'):
                    gateway.complete('fixture', MESSAGES)

    def test_probe_skips_null_frames_and_keeps_unfinished_observation(self):
        frame = {'choices': [{'delta': {'content': '<think>reason</think>OK'}}]}
        stream = b'data: null\n\ndata: ' + json.dumps(frame).encode() + b'\n\n'
        gateway, _, _ = self.gateway(lambda body, n: (200, stream, {}))
        with patch('app.gateway.detect_model', side_effect=lambda request, **kwargs: request('high', 'openai', 16)):
            self.assertEqual(gateway.detect_reasoning('fixture'), {'thinking': True, 'content': True})

    def test_other_client_parameter_status_uses_the_same_recovery(self):
        gateway, service, _ = self.gateway(lambda body, n: (415, {'error': {
            'message': 'response_format is not supported', 'param': 'response_format'}}, {})
            if 'response_format' in body else (200, OK, {}))
        self.assertEqual(gateway.complete('fixture', MESSAGES, parameters={
            'response_format': {'type': 'json_object'}, '_umeko_auto_parameters': ['response_format']}).text, 'OK')
        self.assertNotIn('response_format', service.requests[-1])

    def test_explicit_error_parameter_precedes_an_incidental_field_mention(self):
        gateway, service, _ = self.gateway(lambda body, n: (400, {'error': {
            'message': 'messages are malformed; seed was supplied', 'param': 'messages'}}, {}))
        with self.assertRaisesRegex(Exception, 'messages'):
            gateway.complete('fixture', MESSAGES, parameters={'seed': 7, '_umeko_auto_parameters': ['seed']})
        self.assertEqual(len(service.requests), 1)


if __name__ == '__main__':
    unittest.main()
