"""Threaded local fake provider, driven while the UI uses a real Qt event loop."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from socketserver import TCPServer
import threading
import time
from types import SimpleNamespace


class _LoopbackServer(ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer's reverse lookup is unnecessary for a loopback fixture.
        TCPServer.server_bind(self)
        self.server_name = 'localhost'
        self.server_port = self.server_address[1]


def _paced_indices(stop, count=600, interval=.025):
    # Keep the intended stream rate when a loaded runner wakes a timer late.
    # Relative sleeps accumulate that lateness once per chunk (600 times).
    deadline = time.monotonic()
    for index in range(count):
        deadline += interval
        if stop.wait(max(0, deadline - time.monotonic())):
            return
        yield index


class ReasoningStream:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def __init__(self):
        self.release, self.stop = threading.Event(), threading.Event()
        self.sent = SimpleNamespace(value=0)
        self.requests, self.errors = [], []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests.append((self.path, body['model']))
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()

                def emit(delta, finish=None):
                    data = {'id': 'chatcmpl-test', 'object': 'chat.completion.chunk',
                            'created': 1, 'model': 'test-model',
                            'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}
                    self.wfile.write(('data: ' + json.dumps(data) + '\n\n').encode())
                    self.wfile.flush()

                try:
                    emit({'role': 'assistant'})
                    emit({'reasoning_content': 'First stable line.\nSecond stable line.\n'})
                    if not owner.release.wait(20):
                        owner.errors.append({'message': 'GUI did not release the initial reasoning stream'})
                        return
                    words = ['Reasoning ', 'keeps ', 'the ', 'same ', 'line ', 'spacing.\n']
                    for index in _paced_indices(owner.stop):
                        emit({'reasoning_content': words[index % len(words)]})
                        owner.sent.value += 1
                    if owner.stop.is_set():
                        return
                    emit({'content': 'The local streaming test is complete.'})
                    emit({}, 'stop')
                    self.wfile.write(b'data: [DONE]\n\n')
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError) as error:
                    if not owner.stop.is_set():
                        owner.errors.append({'message': repr(error), 'sent': owner.sent.value})

        self.server = _LoopbackServer(('127.0.0.1', 0), Handler)
        self.server_port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def poll(self):
        assert self.thread.is_alive(), 'Fake SSE provider stopped unexpectedly'

    def close(self):
        self.stop.set()
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        assert not self.thread.is_alive(), 'Fake SSE provider did not stop'
