"""Response compatibility through a real local HTTP connection."""
import json
import tempfile
import threading
import unittest
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app import protocols
from app.openai_responses import responses_events
import umeko_provider_sdk as sdk


@contextmanager
def fake_response(events, *, json_body=False, done=True, raw=False, requests=None):
    if raw:
        payload = events
    elif json_body:
        payload = json.dumps(events).encode()
    else:
        payload = b': keepalive\r\n\r\n' + b''.join(
            b'data: ' + json.dumps(event).encode() + b'\r\n\r\n' for event in events)
        if done:
            payload += b'data: [DONE]\r\n\r\n'
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            if requests is not None:
                requests.append(json.loads(body))
            self.do_GET()
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json' if json_body else 'text/event-stream')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            # Fragment transport bytes independently from model deltas.
            try:
                for offset in range(0, len(payload), 7):
                    self.wfile.write(payload[offset:offset + 7])
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                pass  # Error consumers can close before the terminal SSE marker.
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}', timeout=5) as response:
            yield response
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def delta(value=None, finish=None, **extra):
    return dict(choices=[dict(delta=value or {}, finish_reason=finish)], **extra)


class OpenAIResponseCompatibility(unittest.TestCase):
    def collect(self, events, **kwargs):
        # Exercise both callers of the shared parser against separate HTTP replies.
        results = []
        for module in (protocols, sdk):
            with fake_response(events, **kwargs) as response:
                results.append(module.collect_openai(module.response_events(response)))
        for result in results:
            self.assertEqual(result['choices'][0]['message'], results[0]['choices'][0]['message'])
        return results[0]

    def test_reasoning_aliases(self):
        for field in ('reasoning_content', 'reasoning', 'reasoning_text'):
            with self.subTest(field=field):
                result = self.collect([delta({field: 'plan'}), delta({'content': 'answer'}, 'stop')])
                self.assertEqual(result['choices'][0]['message']['reasoning_content'], 'plan')

    def test_split_think_tags(self):
        events = [delta({'content': part}) for part in ('<thi', 'nk>plan</th', 'ink>an', 'swer')]
        result = self.collect(events + [delta(finish='stop')])
        self.assertEqual(result['choices'][0]['message']['content'], 'answer')
        self.assertEqual(result['choices'][0]['message']['reasoning_content'], 'plan')

    def test_usage_absent_null_and_aliases(self):
        for usage, expected in ((None, {}), ({'input_tokens': 3, 'output_tokens': 2}, {'prompt_tokens': 3, 'completion_tokens': 2, 'total_tokens': 5})):
            with self.subTest(usage=usage):
                result = self.collect([delta({'content': 'answer'}, 'stop', usage=usage)])
                self.assertEqual(result['usage'], expected)

    def test_tool_arguments_fragments_and_objects(self):
        for arguments in (( '{"value":', '1}'), ({'value': 1},)):
            events = [delta({'tool_calls': [{'id': 'call1', 'function': {'name': 'lookup', 'arguments': arguments[0]}}]})]
            events += [delta({'tool_calls': [{'function': {'arguments': part}}]}) for part in arguments[1:]]
            result = self.collect(events + [delta(finish='tool_calls')])
            call = result['choices'][0]['message']['tool_calls'][0]
            self.assertEqual(json.loads(call['function']['arguments']), {'value': 1})
            self.assertEqual(call['id'], 'call1')

    def test_omitted_tool_indexes(self):
        result = self.collect([delta({'tool_calls': [
            {'id': 'one', 'function': {'name': 'first', 'arguments': {}}},
            {'id': 'two', 'function': {'name': 'second', 'arguments': {}}}]}), delta(finish='tool_use')])
        self.assertEqual([call['id'] for call in result['choices'][0]['message']['tool_calls']], ['one', 'two'])

    def test_finish_aliases(self):
        for reason, expected in [('tool_use', 'tool_calls'), ('function_call', 'tool_calls'), ('max_tokens', 'length'), ('max_output_tokens', 'length'), ('end_turn', 'stop'), ('completed', 'stop')]:
            with self.subTest(reason=reason):
                self.assertEqual(self.collect([delta({'content': 'answer'}, reason)])['choices'][0]['finish_reason'], expected)

    def test_missing_done_terminal_success_and_empty_chunks(self):
        result = self.collect([{}, {'choices': []}, delta(), delta({'content': 'answer'}, 'stop')], done=False)
        self.assertEqual(result['choices'][0]['message']['content'], 'answer')

    def test_empty_and_broken_streams_raise(self):
        for events in ([], [delta({'content': 'partial'})]):
            for module in (protocols, sdk):
                with self.subTest(events=events, module=module.__name__):
                    with fake_response(events, done=False) as response:
                        with self.assertRaisesRegex(Exception, 'completion|完成|结束'):
                            module.collect_openai(module.response_events(response))

    def test_http_200_error_cause(self):
        for json_body in (False, True):
            for module in (protocols, sdk):
                body = {'error': {'message': 'unsupported response_format', 'code': 'invalid_parameter'}}
                with fake_response(body if json_body else [body], json_body=json_body) as response:
                    with self.assertRaisesRegex(Exception, 'response_format'):
                        module.collect_openai(module.response_events(response))

    def test_json_reasoning_and_object_tool_arguments(self):
        body = {'choices': [{'message': {'role': 'assistant', 'content': '<think>plan</think>answer', 'tool_calls': [{'id': 'one', 'function': {'name': 'lookup', 'arguments': {'value': 1}}}]}, 'finish_reason': 'tool_use'}], 'usage': None}
        result = self.collect(body, json_body=True)
        message = result['choices'][0]['message']
        self.assertEqual(message['reasoning_content'], 'plan')
        self.assertEqual(message['content'], 'answer')
        self.assertEqual(json.loads(message['tool_calls'][0]['function']['arguments']), {'value': 1})

    def test_responses_object_arguments(self):
        events = [dict(object='response', status='completed', output=[dict(type='function_call', id='item', call_id='call', name='lookup', arguments={'value': 1})])]
        with fake_response(events) as response:
            result = sdk.collect_openai(responses_events(protocols.response_events(response)))
        self.assertEqual(json.loads(result['choices'][0]['message']['tool_calls'][0]['function']['arguments']), {'value': 1})

    def test_anthropic_object_arguments(self):
        events = [dict(type='message', content=[dict(type='tool_use', id='call', name='lookup', input={'value': 1})], stop_reason='tool_use', usage=None)]
        with fake_response(events) as response:
            result = sdk.collect_openai(protocols.anthropic_events_to_openai(protocols.response_events(response)))
        self.assertEqual(json.loads(result['choices'][0]['message']['tool_calls'][0]['function']['arguments']), {'value': 1})

    def test_named_sse_error_and_empty_data_keepalive(self):
        with fake_response(b'data:\r\n\r\nevent: error\r\ndata: {"message":"unsupported tool_choice"}\r\n\r\n', raw=True) as response:
            with self.assertRaisesRegex(ValueError, 'tool_choice'):
                sdk.collect_openai(sdk.response_events(response))
        body = b'data:\n\n: keepalive\n\ndata: {"choices":[{"delta":{"content":"answer"},"finish_reason":"stop"}]}\n\n'
        with fake_response(body, raw=True) as response:
            self.assertEqual(sdk.collect_openai(sdk.response_events(response))['choices'][0]['message']['content'], 'answer')

    def test_incremental_canonical_stream_and_double_adapter(self):
        from umeko_provider_sdk.streaming import normalize_openai_events
        events = [delta({'content': '<thi'}), delta({'content': 'nk>plan</th'}), delta({'content': 'ink>answer'}, 'end_turn')]
        with fake_response(events, done=False) as response:
            canonical = list(normalize_openai_events(normalize_openai_events(sdk.response_events(response))))
        pieces = [choice['delta'] for event in canonical for choice in event['choices']]
        self.assertEqual(''.join(part.get('content', '') for part in pieces), 'answer')
        self.assertEqual(''.join(part.get('reasoning_content', '') for part in pieces), 'plan')
        self.assertEqual(canonical[-1]['choices'][0]['finish_reason'], 'stop')

    def test_responses_done_and_anthropic_stream_object_arguments(self):
        cases = [
            (responses_events, [dict(type='response.output_item.added', item=dict(type='function_call', id='item', call_id='call', name='lookup', arguments='')), dict(type='response.function_call_arguments.done', item_id='item', arguments={'value': 1}), dict(type='response.completed', response=dict(status='completed', output=[]))]),
            (protocols.anthropic_events_to_openai, [dict(type='content_block_start', index=0, content_block=dict(type='tool_use', id='call', name='lookup', input={'value': 1})), dict(type='message_delta', delta=dict(stop_reason='tool_use'), usage=None)]),
        ]
        for adapter, events in cases:
            with fake_response(events) as response:
                result = sdk.collect_openai(adapter(sdk.response_events(response)))
            self.assertEqual(json.loads(result['choices'][0]['message']['tool_calls'][0]['function']['arguments']), {'value': 1})

    def test_plugin_usage_tail_and_nested_response_failure(self):
        result = self.collect([delta({'content': 'answer'}), dict(choices=[], usage=dict(prompt_tokens=7))], done=False)
        self.assertEqual(result['choices'][0]['message']['content'], 'answer')
        self.assertEqual(result['usage']['prompt_tokens'], 7)
        error = dict(type='response.failed', response=dict(error=dict(message='unsupported field', param='response_format', code='invalid_parameter')))
        for adapter in (lambda events: events, responses_events):
            with fake_response([error]) as response:
                with self.assertRaisesRegex(ValueError, 'HTTP 200.*response_format'):
                    sdk.collect_openai(adapter(sdk.response_events(response)))

    def test_usage_tail_emits_canonical_terminal_chunk(self):
        from umeko_provider_sdk.streaming import normalize_openai_events
        for content, expected in ((dict(content='answer<'), 'stop'), (dict(tool_calls=[dict(id='call', function=dict(name='lookup', arguments={}))]), 'tool_calls')):
            with fake_response([delta(content), dict(choices=[], usage=dict(completion_tokens=0))], done=False) as response:
                chunks = list(normalize_openai_events(sdk.response_events(response)))
            self.assertEqual(chunks[-1]['choices'][0]['finish_reason'], expected)
            if expected == 'stop':
                self.assertEqual(chunks[-1]['choices'][0]['delta']['content'], '<')

    def test_gateway_direct_reasoning_and_object_tool_arguments(self):
        from app.gateway import Gateway
        from app.integration import UnconfiguredAdapter
        from app.storage import Store
        cases = [
            [delta({'content': '<thi'}), delta({'content': 'nk>plan</think>answer'}, 'end_turn')],
            [delta({'tool_calls': [dict(id='call', function=dict(name='lookup', arguments={'value': 1}))]}, 'tool_use')],
        ]
        for events in cases:
            with fake_response(events, done=False) as response, tempfile.TemporaryDirectory(dir=r'C:\UmekoTests\p124') as directory:
                store = Store(Path(directory))
                store.data['providers'] = [dict(id='fixture', name='Fixture', api='openai', key='fixture-key', baseUrl=response.url + '/v1', proxy=dict(mode='direct'), models=[dict(alias='fixture-model', upstream='fixture-model')])]
                gateway = Gateway(store, UnconfiguredAdapter())
                result = gateway.complete('fixture-model', [dict(role='user', content='answer')], [dict(name='lookup', parameters=dict(type='object'))], provider_id='fixture')
                if events is cases[0]:
                    self.assertEqual((result.text, result.thinking), ('answer', 'plan'))
                else:
                    self.assertEqual(result.tool_calls, [dict(id='call', name='lookup', arguments={'value': 1})])

    def test_responses_preserves_explicit_options_and_native_fields(self):
        from app.openai_responses import responses_request
        configured = dict(response_format=dict(type='json_object'), user='fixture-user', seed=7,
                          custom_option=dict(enabled=True), store=True, stream=False,
                          max_output_tokens=23, reasoning=dict(effort='low', summary='auto'),
                          reasoning_effort='high', tool_choice=dict(type='function', name='lookup'),
                          _umeko_private='host-only')
        cases = [
            (configured, {key: value for key, value in configured.items() if key not in ('reasoning_effort', '_umeko_private')}),
            (dict(max_completion_tokens=19, reasoning_effort='high', tool_choice=dict(type='function', function=dict(name='lookup'))), dict(max_completion_tokens=19, reasoning=dict(effort='high'), tool_choice=dict(type='function', name='lookup'))),
            (dict(max_tokens=17), dict(max_tokens=17)),
        ]
        for parameters, expected in cases:
            with self.subTest(parameters=parameters):
                captured = []
                with fake_response(dict(choices=[dict(message=dict(role='assistant', content='answer'), finish_reason='stop')]), json_body=True, requests=captured) as response:
                    body = responses_request([dict(role='user', content='answer')], [], 100, parameters)
                    with urllib.request.urlopen(urllib.request.Request(response.url, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'}), timeout=5) as posted:
                        sdk.collect_openai(sdk.response_events(posted))
                sent = captured[0]
                for key, value in expected.items():
                    self.assertEqual(sent[key], value)
                self.assertNotIn('_umeko_private', sent)
                self.assertNotIn('reasoning_effort', sent)
                self.assertEqual(sum(key in sent for key in ('max_tokens', 'max_completion_tokens', 'max_output_tokens')), 1)


if __name__ == '__main__':
    unittest.main()
