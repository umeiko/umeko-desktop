"""Exercise each deterministic gateway through the production HTTP collector."""
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
from tests.test_reasoning_effects import FakeModel


class EffectGatewayTests(unittest.TestCase):
    def test_parameter_effects_cross_real_transport(self):
        cases = [
            ('all-effort400', 'qwen-switch', ['high'], False),
            ('ignored200', 'openai', [], False),
            ('litellm-ignored', 'openai', [], False),
            ('thinking', 'qwen-switch', ['high'], False),
            ('reasoning', 'reasoning-switch', ['high'], False),
            ('template', 'template-thinking', ['high'], False),
            ('deepseek', 'deepseek-switch', ['high'], False),
            ('degrading', 'qwen-switch', ['high'], True),
            ('disappearing', 'qwen-switch', ['high'], True),
            ('native', 'openai-none', ['none', 'low', 'medium', 'high', 'max'], False),
            ('nested', 'chat-template', ['none', 'low', 'medium', 'high', 'max'], False),
            ('unobservable', 'openai', ['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'], False),
        ]
        results = {}
        for mode, style, levels, degraded in cases:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as profile:
                model, calls = FakeModel(mode), []

                class Upstream(BaseHTTPRequestHandler):
                    def log_message(self, *_):
                        pass

                    def do_POST(self):
                        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                        params = {key: body[key] for key in ('reasoning_effort', 'enable_thinking',
                                  'enable_reasoning', 'thinking', 'chat_template_kwargs') if key in body}
                        calls.append(params)
                        try:
                            observed = model.respond(params)
                            message = {'role': 'assistant', 'content': observed['answer']}
                            if observed['thinkingChars']:
                                message['reasoning_content'] = 'r' * observed['thinkingChars']
                            usage = {}
                            if observed['reasoningTokens'] is not None:
                                usage['completion_tokens_details'] = {'reasoning_tokens': observed['reasoningTokens']}
                            payload = {'choices': [{'message': message, 'finish_reason': 'stop'}], 'usage': usage}
                            status = 200
                        except ValueError as error:
                            payload, status = {'error': {'message': str(error), 'param': 'reasoning_effort'}}, 400
                        raw = json.dumps(payload).encode()
                        self.send_response(status)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Content-Length', str(len(raw)))
                        self.end_headers()
                        self.wfile.write(raw)

                server = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
                thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
                thread.start()
                try:
                    row = {'alias': 'test-model', 'upstream': 'test-model',
                           'reasoningLevelsAuto': True, 'reasoningFormatAuto': True}
                    provider = {'id': 'test', 'name': 'Test provider', 'api': 'openai', 'key': 'fixture',
                                'baseUrl': f'http://127.0.0.1:{server.server_port}/v1', 'models': [row]}
                    store = SimpleNamespace(directory=Path(profile), data={'providers': [provider]})
                    result = Gateway(store, UnconfiguredAdapter()).detect_reasoning('test-model')
                    self.assertEqual(result['format']['format'], style)
                    self.assertEqual(result['levels']['levels'], levels)
                    self.assertEqual(bool(result['format']['degradingStyles']), degraded)
                    self.assertEqual(result['format']['requestCount'], len(calls))
                    self.assertEqual(len(calls), len({json.dumps(p, sort_keys=True) for p in calls}))
                    self.assertEqual(result['format']['verified'], mode not in (
                        'unobservable', 'ignored200', 'litellm-ignored'))
                    results[mode] = result
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join()
        if os.environ.get('UMEKO_EFFECT_HTTP_RESULTS'):
            Path(os.environ['UMEKO_EFFECT_HTTP_RESULTS']).write_text(
                json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
