"""Background-thread helpers for the host's plugin-owned session service."""
from __future__ import annotations

import copy
import threading
from . import PluginError

OPERATIONS = frozenset({
    'sessions.acquire', 'sessions.submit', 'sessions.subscribe', 'sessions.wait',
    'sessions.cancel', 'sessions.history', 'sessions.release',
    'approvals.registerHandler', 'approvals.respond',
})


class Sessions:
    """Wait for host responses without blocking the worker's event reader.

    Call these methods only from plugin-created background threads. ``timeout``
    limits the local response wait, not the native run; None waits until a response
    or Context.close(). Raw Context.request_host remains nonblocking.
    """

    def __init__(self, context):
        self.context = context
        self._lock = threading.Lock()
        self._pending = {}

    def _call(self, operation, arguments, timeout):
        if threading.get_ident() == self.context._event_thread_id:
            raise PluginError('Session helpers must run in a background thread; use request_host in callbacks')
        if self.context.cancelled.is_set():
            raise PluginError('Plugin is stopping')
        item = {'event': threading.Event(), 'operation': operation}
        identifier = None

        def register(value):
            nonlocal identifier
            identifier = value
            with self._lock:
                if self.context.cancelled.is_set():raise PluginError('Plugin is stopping')
                self._pending[value] = item

        try:
            self.context._request_host(operation, arguments, before_emit=register)
            if not item['event'].wait(timeout):
                raise PluginError('Host response wait timed out; the native run was not cancelled')
            response = item.get('response')
            if response is None:raise PluginError('Plugin is stopping')
            if response.get('operation') != operation:raise PluginError('Host response operation does not match request')
            if response.get('ok') is not True:
                raise PluginError(str(response.get('error', 'Host operation failed')))
            return response.get('result')
        finally:
            with self._lock:self._pending.pop(identifier, None)

    def _receive(self, data):
        if not isinstance(data, dict):return
        with self._lock:
            item = self._pending.pop(data.get('requestId'), None)
            if item is not None:
                item['response'] = copy.deepcopy(data)
                item['event'].set()

    def _close(self):
        with self._lock:
            items = list(self._pending.values())
            self._pending.clear()
            for item in items:item['event'].set()

    def acquire(self, external_key, *, profile, namespace='default', create_if_missing=True, timeout=None):
        """Resolve the durable plugin/namespace/externalKey mapping using a host profile."""
        return self._call('sessions.acquire', {'namespace': namespace, 'externalKey': external_key,
            'createIfMissing': create_if_missing, 'profile': profile}, timeout)

    def submit(self, handle, request_id, content, *, timeout=None):
        """Submit one normal prompt; returns a runId and started/queued disposition."""
        return self._call('sessions.submit', {'handle': handle, 'requestId': request_id, 'content': content}, timeout)

    def subscribe(self, handle, *, timeout=None):
        """Deliver sessions.event frames to Plugin.on_event without blocking it."""
        return self._call('sessions.subscribe', {'handle': handle}, timeout)

    def wait(self, handle, run_id, *, timeout=None):
        """Return completed/failed/cancelled terminal output, not an acceptance receipt."""
        return self._call('sessions.wait', {'handle': handle, 'runId': run_id}, timeout)

    def cancel(self, handle, run_id=None, *, timeout=None):
        arguments = {'handle': handle}
        if run_id is not None:arguments['runId'] = run_id
        return self._call('sessions.cancel', arguments, timeout)

    def history(self, handle, limit=None, *, timeout=None):
        arguments = {'handle': handle}
        if limit is not None:arguments['limit'] = limit
        return self._call('sessions.history', arguments, timeout)

    def release(self, handle, *, timeout=None):
        return self._call('sessions.release', {'handle': handle}, timeout)

    def register_approval_handler(self, handle, *, timeout=None):
        return self._call('approvals.registerHandler', {'handle': handle}, timeout)

    def respond_approval(self, handle, request_id, decision, *, timeout=None):
        """Respond to this handle's approval_request with allow/deny/unhandled."""
        return self._call('approvals.respond', {'handle': handle, 'requestId': request_id, 'decision': decision}, timeout)
