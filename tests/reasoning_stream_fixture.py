"""Local fake provider isolated from Qt's Python callbacks and event pumping."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mmap
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import time


class _Counter:
    def __init__(self, path):
        self.file = path.open('r+b')
        self.mapping = mmap.mmap(self.file.fileno(), 4)

    @property
    def value(self):
        return struct.unpack_from('<i', self.mapping)[0]

    @value.setter
    def value(self, value):
        struct.pack_into('<i', self.mapping, 0, value)

    def close(self):
        self.mapping.close()
        self.file.close()


class _Signal:
    def __init__(self, path):
        self.path = path

    def set(self):
        self.path.touch()


def _serve(directory):
    sent = _Counter(directory / 'counter')
    events = (directory / 'events.jsonl').open('ab', buffering=0)
    release, stop = threading.Event(), threading.Event()
    lock = threading.Lock()

    def report(value):
        with lock:
            events.write((json.dumps(value) + '\n').encode())

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
    ready = directory / 'ready.json'
    temporary = directory / 'ready.tmp'
    temporary.write_text(json.dumps({'port': server.server_port}), encoding='utf-8')
    temporary.replace(ready)
    try:
        deadline = time.monotonic() + 120
        while not (directory / 'stop').exists() and time.monotonic() < deadline:
            if (directory / 'release').exists():
                release.set()
            time.sleep(.01)
    finally:
        stop.set()
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        events.close()
        sent.close()


class ReasoningStream:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def __init__(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='umeko-thinking-provider-')
        self.directory = Path(self.temporary.name)
        (self.directory / 'counter').write_bytes(b'\0' * 4)
        (self.directory / 'events.jsonl').touch()
        self.sent = _Counter(self.directory / 'counter')
        self.release = _Signal(self.directory / 'release')
        self.stop = _Signal(self.directory / 'stop')
        self.requests, self.errors = [], []
        self.events = (self.directory / 'events.jsonl').open('rb', buffering=0)
        self.log = (self.directory / 'server.log').open('wb')
        self.buffer = b''
        self.process = None
        try:
            # Do not reimport the Qt smoke script via multiprocessing.spawn.
            # The child executes only this stdlib-only fixture entrypoint.
            self.process = subprocess.Popen(
                [sys.executable, '-u', str(Path(__file__).resolve()), '--serve', str(self.directory)],
                stdout=self.log, stderr=subprocess.STDOUT,
                creationflags=0x08000000 if os.name == 'nt' else 0)
            deadline = time.monotonic() + 10
            while not (self.directory / 'ready.json').exists():
                if self.process.poll() is not None or time.monotonic() >= deadline:
                    raise AssertionError(('Fake SSE provider did not start', self.diagnostics()))
                time.sleep(.01)
            ready = json.loads((self.directory / 'ready.json').read_text(encoding='utf-8'))
            self.server_port = ready['port']
        except BaseException:
            self.close()
            raise

    def poll(self):
        if self.process.poll() is not None:
            raise AssertionError(('Fake SSE provider exited early', self.diagnostics()))
        self.buffer += self.events.read()
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            value = json.loads(line)
            if value['type'] == 'request':
                self.requests.append((value['path'], value['model']))
            elif value['type'] == 'error':
                self.errors.append(value)

    def diagnostics(self):
        return {'exitCode': self.process.poll(),
                'log': (self.directory / 'server.log').read_text(encoding='utf-8', errors='replace')[-2000:]}

    def close(self):
        self.stop.set()
        self.release.set()
        try:
            if self.process:
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.terminate()  # Only this fixture's fake provider.
                    self.process.wait(timeout=5)
        finally:
            self.events.close()
            self.log.close()
            self.sent.close()
            self.temporary.cleanup()


if __name__ == '__main__':
    assert len(sys.argv) == 3 and sys.argv[1] == '--serve'
    _serve(Path(sys.argv[2]))
