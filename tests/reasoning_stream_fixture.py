"""Local fake provider isolated from Qt's Python callbacks and event pumping."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import multiprocessing
import threading


def _serve(channel, release, stop, sent):
    lock = threading.Lock()

    def report(value):
        with lock:
            channel.send(value)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            report({'type': 'request', 'path': self.path, 'model': body['model']})
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
                if not release.wait(20):
                    report({'type': 'error', 'message': 'GUI did not release the initial reasoning stream'})
                    return
                words = ['Reasoning ', 'keeps ', 'the ', 'same ', 'line ', 'spacing.\n']
                for index in range(600):
                    if stop.wait(.025):
                        return
                    emit({'reasoning_content': words[index % len(words)]})
                    sent.value += 1
                emit({'content': 'The local streaming test is complete.'})
                emit({}, 'stop')
                self.wfile.write(b'data: [DONE]\n\n')
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError) as error:
                if not stop.is_set():
                    report({'type': 'error', 'message': repr(error), 'sent': sent.value})

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    report({'type': 'ready', 'port': server.server_port})
    try:
        stop.wait()
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        channel.close()


class ReasoningStream:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def __init__(self):
        context = multiprocessing.get_context('spawn')
        self.channel, child = context.Pipe(duplex=False)
        self.release, self.stop = context.Event(), context.Event()
        self.sent = context.RawValue('i', 0)
        self.requests, self.errors = [], []
        self.process = context.Process(target=_serve, args=(child, self.release, self.stop, self.sent),
                                       name='umeko-thinking-fixture')
        self.process.start()
        child.close()
        try:
            if not self.channel.poll(10):
                raise AssertionError('Fake SSE provider did not start')
            ready = self.channel.recv()
            assert ready['type'] == 'ready', ready
            self.server_port = ready['port']
        except BaseException:
            self.close()
            raise

    def poll(self):
        while self.channel.poll():
            try:
                value = self.channel.recv()
            except EOFError:
                raise AssertionError(('Fake SSE provider exited early', self.process.exitcode))
            if value['type'] == 'request':
                self.requests.append((value['path'], value['model']))
            elif value['type'] == 'error':
                self.errors.append(value)

    def close(self):
        self.stop.set()
        self.release.set()
        self.process.join(timeout=5)
        if self.process.is_alive():
            self.process.terminate()  # Only the fake provider process owned by this fixture.
            self.process.join(timeout=5)
        self.channel.close()
        assert not self.process.is_alive(), 'Fake SSE provider did not stop'
