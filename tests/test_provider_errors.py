"""Provider error summaries and real loopback HTTP failure paths (no model calls)."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from app.gateway import Gateway
from app.integration import UnconfiguredAdapter
from app.provider_errors import format_http_error
from app.provider_models import fetch_model_windows
from app.request_diagnostics import RequestFailure


@contextmanager
def error_server(status, body, headers=None):
    requests = []
    raw = body.encode('utf-8') if isinstance(body, str) else body

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self):
            requests.append((self.command, self.path))
            if self.command == 'POST':
                self.rfile.read(int(self.headers.get('Content-Length', '0')))
            self.send_response(status)
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        do_GET = respond
        do_POST = respond

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1', requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def provider(base):
    return {'id': 'test-provider', 'name': 'Test provider', 'api': 'openai',
            'baseUrl': base, 'key': 'fixture-provider-secret',
            'models': [{'upstream': 'test-model', 'alias': 'test-model', 'vision': True}]}


class ProviderErrorSummaryTests(unittest.TestCase):
    def test_image_limit_400_keeps_actionable_reason_without_generic_hint(self):
        message = format_http_error(400, json.dumps({'error': {
            'message': 'At most 3 image(s) may be provided in one prompt. (parameter=image)',
            'type': 'BadRequestError', 'param': 'image', 'code': 400}}))
        self.assertTrue(message.startswith('供应商返回 HTTP 400：'), message)
        for value in ('At most 3 image(s) may be provided in one prompt. (parameter=image)',
                      'BadRequestError', 'image', '400'):
            self.assertIn(value, message)
        self.assertNotIn('提示：', message)
        self.assertNotIn('请检查地址、密钥和模型名称', message)

    def test_common_server_error_shapes(self):
        cases = [
            ({'error': {'message': 'Anthropic overloaded', 'type': 'overloaded_error'}, 'type': 'error'}, 'Anthropic overloaded'),
            ({'message': 'Request rejected by policy'}, 'Request rejected by policy'),
            ({'detail': 'Image format is not supported'}, 'Image format is not supported'),
            ({'error': 'Specific upstream rejection'}, 'Specific upstream rejection'),
            ({'error': {'type': 'invalid_request_error', 'code': 'bad_image'}}, 'bad_image'),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                self.assertIn(expected, format_http_error(400, json.dumps(body)))

    def test_authentication_and_permission_have_targeted_hints(self):
        for status, reason in ((401, 'Invalid API key'), (403, 'Model access is forbidden')):
            with self.subTest(status=status):
                message = format_http_error(status, json.dumps({'error': {'message': reason}}))
                self.assertIn(reason, message)
                self.assertIn('提示：', message)
                self.assertTrue('密钥' in message or '权限' in message, message)

    def test_not_found_points_to_address_or_model(self):
        message = format_http_error(404, '{"error":{"message":"Model test-model does not exist"}}')
        self.assertIn('Model test-model does not exist', message)
        self.assertIn('提示：', message)
        self.assertIn('地址', message)
        self.assertIn('模型', message)

    def test_rate_limit_keeps_retry_after_and_server_reason(self):
        message = format_http_error(429, '{"error":{"message":"Too many requests"}}', {'retry-after': '17'})
        self.assertIn('Too many requests', message)
        self.assertIn('17', message)
        self.assertIn('提示：', message)
        self.assertIn('重试', message)

    def test_timeout_and_length_have_specific_hints(self):
        for status, reason, expected in (
            (408, 'Upstream request timed out', '超时'),
            (413, 'Request body too large', '过长'),
            (400, 'Maximum context length exceeded: 150000 tokens', '过长'),
        ):
            with self.subTest(status=status):
                message = format_http_error(status, json.dumps({'error': {'message': reason}}))
                self.assertIn(reason, message)
                self.assertIn('提示：', message)
                self.assertIn(expected, message)

    def test_http_status_hints_take_priority_over_context_words(self):
        for status, hint in ((429, '请求受到限流'), (500, '供应商服务端错误')):
            with self.subTest(status=status):
                message = format_http_error(status, '{"message":"Error while processing context length"}')
                self.assertIn(hint, message)
                self.assertNotIn('提示：请求过大', message)

    def test_html_500_is_readable_and_drops_scripts_and_tags(self):
        message = format_http_error(500, '<html><head><script>alert("hidden-script")</script></head>'
                                    '<body><h1>Gateway unavailable</h1><p>Try later &amp; contact support</p></body></html>')
        self.assertIn('Gateway unavailable', message)
        self.assertIn('Try later & contact support', message)
        self.assertNotIn('<', message)
        self.assertNotIn('hidden-script', message)
        self.assertIn('提示：', message)
        self.assertIn('供应商', message)

    def test_non_json_unicode_and_bytes_preserve_reason(self):
        for body in ('代理拒绝图片：最多 5 张', 'Upstream validation failed'.encode()):
            with self.subTest(body=body):
                self.assertIn(body.decode() if isinstance(body, bytes) else body, format_http_error(400, body))

    def test_empty_body_has_explicit_fallback(self):
        for body in ('', '  \r\n', b''):
            with self.subTest(body=body):
                self.assertIn('服务器未返回错误详情', format_http_error(400, body))

    def test_oversized_summary_is_bounded_without_hiding_initial_reason(self):
        message = format_http_error(400, json.dumps({'error': {'message': 'Image rejected: ' + '长' * 10000,
                                                             'type': 'BadRequestError', 'param': 'image', 'code': 400}}))
        self.assertIn('Image rejected:', message)
        for detail in ('type=BadRequestError', 'param=image', 'code=400'):
            self.assertIn(detail, message)
        self.assertLessEqual(len(message), 1000)

    def test_sdk_http_errors_use_same_summary_without_a_gateway_trace(self):
        from umeko_provider_sdk import ProviderError
        from umeko_provider_sdk.http import HttpSession
        raw = '{"error":{"message":"Rate limited for fixture-provider-secret and opaque-hidden-password"}}'
        with error_server(429, raw, {'Retry-After': '17'}) as (base, requests):
            with self.assertRaises(ProviderError) as caught:
                HttpSession([base], environment_proxy=False).request(base + '/models',
                    method='POST', headers={'Authorization': 'Bearer fixture-provider-secret'},
                    data={'password': 'opaque-hidden-password'})
            self.assertIn('HTTP 429', str(caught.exception))
            self.assertIn('Retry-After: 17', str(caught.exception))
            self.assertIn('Rate limited', str(caught.exception))
            self.assertNotIn('fixture-provider-secret', str(caught.exception))
            self.assertNotIn('opaque-hidden-password', str(caught.exception))

    def test_secret_looking_text_and_explicit_secrets_are_redacted(self):
        tokens = ('opaque-fixture-secret', 'fixture-bearer-token', 'sk-fixture0123456789abcdef',
                  'fixture-api-key', 'fixture-access-token', 'fixture-password')
        reason = ('Invalid image; supplied opaque-fixture-secret; Authorization: Bearer fixture-bearer-token; '
                  'key sk-fixture0123456789abcdef; api_key=fixture-api-key; '
                  'token=fixture-access-token; password=fixture-password')
        message = format_http_error(400, json.dumps({'error': {'message': reason}}), secrets=(tokens[0],))
        self.assertIn('Invalid image', message)
        for token in tokens:
            self.assertNotIn(token, message)


class ProviderErrorHttpTests(unittest.TestCase):
    def test_gateway_records_full_error_and_surfaces_image_reason(self):
        reason = 'At most 3 image(s) may be provided in one prompt. (parameter=image)'
        raw = json.dumps({'error': {'message': reason, 'type': 'BadRequestError',
                                    'param': 'image', 'code': 400}}, ensure_ascii=False)
        with tempfile.TemporaryDirectory() as temporary, error_server(400, raw) as (base, requests):
            configured = provider(base)
            store = SimpleNamespace(directory=Path(temporary), data={'providers': [configured]})
            gateway = Gateway(store, UnconfiguredAdapter())
            with self.assertRaises(RequestFailure) as caught:
                list(gateway.events('test-model', [{'role': 'user', 'content': 'fixture'}]))
            failure = caught.exception
            for value in (reason, 'BadRequestError', 'image', '400'):
                self.assertIn(value, str(failure))
            self.assertIn('HTTP 400', str(failure))
            self.assertFalse(failure.retryable)
            self.assertEqual(requests, [('POST', '/v1/chat/completions')])
            identifier = str(failure).split('[Umeko:', 1)[1].split(']', 1)[0]
            report = json.loads(gateway.diagnostics.read(identifier))
            self.assertEqual(report['http'][0]['response']['body'], raw)
            self.assertEqual(report['http'][0]['response']['status'], 400)
            self.assertNotIn(configured['key'], json.dumps(report))

    def test_model_catalog_uses_same_reason_from_real_http_response(self):
        raw = '{"error":{"message":"Model catalog endpoint is missing","code":"not_found"}}'
        with error_server(404, raw) as (base, requests):
            with self.assertRaises(ValueError) as caught:
                fetch_model_windows(provider(base))
            self.assertIn('HTTP 404', str(caught.exception))
            self.assertIn('Model catalog endpoint is missing', str(caught.exception))
            self.assertEqual(requests, [('GET', '/v1/models')])


if __name__ == '__main__':
    unittest.main()
