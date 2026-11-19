"""Keep custom headers and their privacy rules across compatibility retries."""
import copy
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.gateway import Gateway
from app.integration import UnconfiguredAdapter
from app.request_headers import DEFAULTS


class CompatibilityRequestHeadersTests(unittest.TestCase):
    def setUp(self):
        directory = None
        if os.name == 'nt':
            directory = Path('C:/UmekoTests/p124-latest')
            directory.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=directory, prefix='compat-headers-')
        self.addCleanup(self.temp.cleanup)
        self.calls = []
        self.rejected_parameter = 'tool_choice'
        self.fail_after_retry = False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.calls.append({'body': body, 'headers': {
                    key.lower(): value for key, value in self.headers.items()}})
                rejected = (body.get('tool_choice') == 'required' if owner.rejected_parameter == 'tool_choice'
                            else owner.rejected_parameter in body)
                if rejected:
                    status = 400
                    payload = {'error': {'param': owner.rejected_parameter,
                        'message': owner.rejected_parameter + ' unsupported; echoed opaque-workspace-credential'}}
                elif owner.fail_after_retry:
                    status = 403
                    payload = {'error': {'message': 'workspace access denied; echoed opaque-workspace-credential and header-fixture-key'}}
                else:
                    status = 200
                    payload = {'choices': [{'message': {'role': 'assistant', 'content': 'OK'},
                                             'finish_reason': 'stop'}]}
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        policy = copy.deepcopy(DEFAULTS)
        for row in policy:
            if row['id'] == 'authorization':
                row['name'] = 'X-Client-Auth'
            elif row['id'] == 'user-agent':
                row['enabled'] = False
        policy.append({'id': 'workspace', 'name': 'X-Workspace',
                       'value': 'opaque-workspace-credential', 'enabled': True})
        provider = {'id': 'header-fixture', 'name': 'Offline headers', 'api': 'openai',
            'baseUrl': f'http://127.0.0.1:{self.server.server_port}/v1',
            'key': 'header-fixture-key', 'proxy': {'mode': 'direct'},
            'models': [{'upstream': 'header-model', 'alias': 'header-model',
                        'reasoningFormat': 'deepseek'}]}
        self.store = SimpleNamespace(directory=Path(self.temp.name), data={
            'providers': [provider], 'requestHeaders': policy})
        self.gateway = Gateway(self.store, UnconfiguredAdapter())

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def complete(self, parameters):
        tools = [{'name': 'lookup', 'parameters': {'type': 'object', 'properties': {}}}]
        return self.gateway.complete('header-model', [{'role': 'user', 'content': 'Reply OK'}],
                                     tools, parameters=parameters)

    def assert_custom_headers_on_every_attempt(self, count):
        self.assertEqual(len(self.calls), count)
        for call in self.calls:
            self.assertEqual(call['headers']['x-workspace'], 'opaque-workspace-credential')
            self.assertEqual(call['headers']['x-client-auth'], 'Bearer header-fixture-key')
            self.assertNotIn('authorization', call['headers'])
            self.assertNotIn('user-agent', call['headers'])
            self.assertEqual(call['headers']['content-type'], 'application/json')

    def assert_secrets_absent(self, text):
        for secret in ('opaque-workspace-credential', 'header-fixture-key'):
            self.assertNotIn(secret, text)

    def test_tool_choice_retry_preserves_custom_renamed_and_disabled_headers(self):
        params = {'tool_choice': 'required', '_umeko_auto_parameters': ['tool_choice']}
        self.assertEqual(self.complete(params).text, 'OK')
        self.assert_custom_headers_on_every_attempt(2)
        self.assertEqual([call['body']['tool_choice'] for call in self.calls], ['required', 'auto'])
        self.assertEqual(self.calls[0]['body']['tools'], self.calls[1]['body']['tools'])
        self.assertEqual(params['tool_choice'], 'required')
        latest = self.gateway.diagnostics.latest_compatibility('header-fixture')
        self.assertEqual(latest['compatibilityNotice'], '请求已重试成功')
        raw = self.gateway.diagnostics.read(latest['compatibilityReportId'])
        self.assert_secrets_absent(raw)
        report = json.loads(raw)
        self.assertEqual([row['response']['status'] for row in report['http']], [400, 200])
        self.assertEqual(report['http'][0]['parameterRetry'], ['tool_choice'])

    def test_thinking_retry_redacts_custom_header_from_both_failed_attempts(self):
        self.rejected_parameter = 'thinking'
        self.fail_after_retry = True
        with self.assertRaises(ValueError) as captured:
            self.complete({'thinking': {'type': 'enabled'}, '_umeko_auto_parameters': ['thinking']})
        self.assert_custom_headers_on_every_attempt(2)
        self.assertIn('thinking', self.calls[0]['body'])
        self.assertNotIn('thinking', self.calls[1]['body'])
        self.assertIn('workspace access denied', str(captured.exception))
        self.assert_secrets_absent(str(captured.exception))
        reports = list((self.store.directory / 'request-errors').glob('*.json'))
        self.assertEqual(len(reports), 1)
        raw = reports[0].read_text(encoding='utf-8')
        self.assert_secrets_absent(raw)
        report = json.loads(raw)
        self.assertEqual([row['response']['status'] for row in report['http']], [400, 403])

    def test_cached_success_diagnostic_redacts_arbitrarily_named_custom_header(self):
        params = {'tool_choice': 'required', '_umeko_auto_parameters': ['tool_choice']}
        self.assertEqual(self.complete(params).text, 'OK')
        self.assertEqual(self.complete(params).text, 'OK')
        self.assert_custom_headers_on_every_attempt(3)
        self.assertEqual(self.calls[-1]['body']['tool_choice'], 'auto')
        latest = self.gateway.diagnostics.latest_compatibility('header-fixture')
        self.assertTrue(latest['compatibilityReportId'])
        raw = self.gateway.diagnostics.read(latest['compatibilityReportId'])
        self.assert_secrets_absent(raw)
        report = json.loads(raw)
        self.assertEqual(len(report['http']), 1)
        self.assertEqual(report['http'][0]['response']['status'], 200)
        self.assertEqual(report['http'][0]['compatibility'][0]['parameter'], 'tool_choice')


if __name__ == '__main__':
    unittest.main()
