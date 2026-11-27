"""Lazy-started persistent Node helper for desktop-level remote operations.

Serves WorkspacePicker, DesktopSettings add/test, and the plugin WorkspaceExecutor
even when no Pi session is active. Emits live connection state to RemoteEnvironments.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path

from .pi_runtime import CREATE_NO_WINDOW, node_environment, node_executable
from .remote_environments import network_config


class RemoteServiceClient:
    def __init__(self, controller):
        self._controller = controller
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._process = None
        self._reader = None
        self._pending: dict[str, tuple[threading.Event, dict]] = {}
        self._closed = False
        self._on_state = None

    def set_state_handler(self, handler):
        self._on_state = handler

    def _service_script(self) -> Path:
        release = getattr(self._controller, '_release', None)
        if release:
            candidate = Path(release) / 'remote-service.mjs'
            if candidate.is_file():
                return candidate
        root = Path(self._controller.root)
        from .pi_runtime import RELEASE_NAME
        bundled = root / 'runtime' / 'releases' / RELEASE_NAME / 'remote-service.mjs'
        if bundled.is_file():
            return bundled
        return root / 'runtime' / 'remote-service.mjs'

    def _test_ssh_command(self):
        if ('--remote-environments-smoke' in sys.argv or '--remote-workdir-smoke' in sys.argv) and os.environ.get('QT_QPA_PLATFORM') == 'offscreen':
            raw = os.environ.get('UMEKO_TEST_SSH_COMMAND')
            if raw:
                try:
                    return json.loads(raw)
                except ValueError:
                    return None
        return None

    def _ensure_started(self):
        with self._lock:
            if self._closed:
                raise RuntimeError('Remote service is closed')
            if self._process is not None and self._process.poll() is None:
                return self._process
            script = self._service_script()
            if not script.is_file():
                raise RuntimeError('Remote service runtime is missing: ' + str(script))
            env = node_environment()
            process = subprocess.Popen(
                [node_executable(), str(script)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=env,
                creationflags=CREATE_NO_WINDOW,
            )
            from .windows_job import assign_subprocess
            assign_subprocess(process)
            self._process = process
            reader = threading.Thread(target=self._read_loop, args=(process,), daemon=True, name='umeko-remote-service')
            self._reader = reader
            reader.start()
            return process

    def _read_loop(self, process):
        stdout = process.stdout
        if stdout is None:
            return
        try:
            for raw in stdout:
                line = raw.decode('utf-8', 'replace').strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                kind = event.get('type')
                if kind == 'response':
                    req_id = event.get('id')
                    with self._lock:
                        waiter = self._pending.pop(req_id, None)
                    if waiter is not None:
                        waiter[1]['result'] = event.get('result', {'ok': False, 'error': 'Empty response'})
                        waiter[0].set()
                elif kind == 'remote_environment_state':
                    handler = self._on_state
                    if callable(handler):
                        try:
                            handler(event)
                        except Exception:
                            pass
        finally:
            with self._lock:
                if self._process is process:
                    self._process = None
                pending = list(self._pending.values())
                self._pending.clear()
            for done, box in pending:
                box['result'] = {'ok': False, 'error': 'Remote service exited'}
                done.set()

    def call(self, method: str, params: dict | None = None, *, timeout: float = 120.0) -> dict:
        process = self._ensure_started()
        req_id = uuid.uuid4().hex
        done = threading.Event()
        box: dict = {}
        with self._lock:
            self._pending[req_id] = (done, box)
        payload_params = dict(params or {})
        if method not in ('sshHosts', 'shutdown'):
            registry = getattr(self._controller, '_remote_environments', None)
            if registry is not None:
                payload_params['environments'] = registry.configured()
            payload_params['remoteNetwork'] = network_config(self._controller.store)
            test_ssh = self._test_ssh_command()
            if test_ssh is not None:
                payload_params['remoteTestSshCommand'] = test_ssh
        message = json.dumps({'id': req_id, 'method': method, 'params': payload_params}, ensure_ascii=True) + '\n'
        try:
            with self._write_lock:
                if process.stdin is None:
                    raise OSError('Remote service stdin closed')
                process.stdin.write(message.encode('utf-8'))
                process.stdin.flush()
        except OSError as error:
            with self._lock:
                self._pending.pop(req_id, None)
            return {'ok': False, 'error': str(error)}
        if not done.wait(timeout=timeout):
            with self._lock:
                self._pending.pop(req_id, None)
            try:
                cancel = json.dumps({'type': 'cancel', 'id': req_id}) + '\n'
                with self._write_lock:
                    if process.stdin is not None:
                        process.stdin.write(cancel.encode('utf-8'))
                        process.stdin.flush()
            except OSError:
                pass
            return {'ok': False, 'error': 'Remote request timed out'}
        return box.get('result', {'ok': False, 'error': 'Remote request failed'})

    def close_environment(self, name: str):
        with self._lock:
            running = self._process is not None and self._process.poll() is None
        if running:
            self.call('close', {'name': name}, timeout=5.0)

    def refresh_network(self):
        with self._lock:
            process = self._process
        if process is None or process.poll() is not None:
            return
        message = {'method': 'setConfig', 'params': {'remoteNetwork': network_config(self._controller.store)}}
        with self._write_lock:
            try:
                process.stdin.write((json.dumps(message) + '\n').encode('utf-8'))
                process.stdin.flush()
            except (OSError, ValueError):
                pass

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            process = self._process
            self._process = None
            pending = list(self._pending.values())
            self._pending.clear()
        for done, box in pending:
            box['result'] = {'ok': False, 'error': 'Remote service closed'}
            done.set()
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.write(b'{"id":"shutdown","method":"shutdown","params":{}}\n')
                process.stdin.flush()
                process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                process.kill()
