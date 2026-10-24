import json
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from app.gateway import Gateway
from app.integration import UnconfiguredAdapter
from app.storage import Store
from app.openai_responses import responses_events


class ResponsesTests(unittest.TestCase):
    def test_gateway_uses_responses_for_tool_calls_and_returns_results(self):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append((self.path, dict(self.headers), body))
                if len(requests) == 1:
                    events = [dict(type='response.output_item.added', item=dict(type='function_call', id='fc_1', call_id='call_1', name='read_file', arguments='')),
                              dict(type='response.function_call_arguments.delta', item_id='fc_1', delta='{"path":"a.txt"}'),
                              dict(type='response.function_call_arguments.done', item_id='fc_1', arguments='{"path":"a.txt"}'),
                              dict(type='response.completed', response=dict(status='completed', output=[], usage=dict(input_tokens=3, output_tokens=5)))]
                else:
                    events = [dict(type='response.output_text.delta', delta='Finished'),
                              dict(type='response.completed', response=dict(status='completed', output=[dict(type='message', content=[dict(type='output_text', text='Finished')])], usage=dict(input_tokens=8, output_tokens=2)))]
                self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
                for event in events: self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode())
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                store = Store(Path(temp))
                store.data['providers'] = [dict(id='codex', name='Codex(Work)', api='openai', wireApi='responses', key='fixture-key', baseUrl=f'http://127.0.0.1:{server.server_port}/v1', proxy=dict(mode='direct'), models=[dict(alias='local-alias', upstream='gpt-6.1-sol', vision=True, visionAuto=False)])]
                gateway = Gateway(store, UnconfiguredAdapter())
                messages = [dict(role='user', content=[dict(type='text', text='Read this'), dict(type='image_url', image_url=dict(url='data:image/png;base64,fixture'))])]
                tools = [dict(name='read_file', parameters=dict(type='object', properties=dict(path=dict(type='string'))))]
                result = gateway.complete('local-alias', messages, tools, 100, 'codex', dict(reasoning_effort='high'))
                self.assertEqual(result.tool_calls, [dict(id='call_1', name='read_file', arguments=dict(path='a.txt'))])
                messages += [dict(role='assistant', content='', tool_calls=[dict(id='call_1', function=dict(name='read_file', arguments='{"path":"a.txt"}'))]), dict(role='tool', tool_call_id='call_1', content='file contents')]
                result = gateway.complete('local-alias', messages, tools, 100, 'codex')
                self.assertEqual((result.text, result.input_tokens, result.output_tokens), ('Finished', 8, 2))
                path, headers, body = requests[0]
                self.assertEqual((path, headers['Authorization']), ('/v1/responses', 'Bearer fixture-key'))
                self.assertEqual(body['model'], 'gpt-6.1-sol')
                self.assertEqual(body['input'][0]['content'][1]['type'], 'input_image')
                self.assertEqual(body['reasoning'], dict(effort='high'))
                self.assertEqual(body['tools'][0]['name'], 'read_file')
                self.assertFalse(body['store'])
                self.assertNotIn('max_tokens', body)
                self.assertEqual(requests[1][2]['input'][-1], dict(type='function_call_output', call_id='call_1', output='file contents'))
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_failure_and_truncated_stream_never_look_successful(self):
        for events in ([dict(type='response.failed', response=dict(error=dict(message='rejected')))], [dict(type='response.output_text.delta', delta='partial')]):
            with self.assertRaises(ValueError): list(responses_events(events))
        result = list(responses_events([dict(type='response.incomplete', response=dict(status='incomplete', incomplete_details=dict(reason='max_output_tokens'), output=[]))]))
        self.assertEqual(result[-1]['choices'][0]['finish_reason'], 'length')

    def test_nonstream_tool_response_and_complete_arguments_are_supported(self):
        result = list(responses_events([dict(object='response', status='completed', output=[dict(type='function_call', id='fc', call_id='call', name='read', arguments='{}')])]))
        self.assertEqual(result[0]['choices'][0]['delta']['tool_calls'][0]['function']['arguments'], '{}')
