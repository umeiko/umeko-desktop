"""Per-provider networking and opt-in, credential-redacted request diagnostics."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import http.client
import urllib.request
import urllib.parse
import re
import os
import ssl
import sys
import time
from pathlib import Path

policy = ContextVar('umeko_network_policy', default=None)
trace = ContextVar('umeko_network_trace', default=None)
_MACOS_CA_FILE = Path('/etc/ssl/cert.pem')
DEFAULT_CONNECT_TIMEOUT_SECONDS = 15.0


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def set_response_timeout(response, timeout_seconds):
    """Adjust the underlying socket read timeout after headers or first SSE event."""
    raw = getattr(response, 'response', response)
    fp = getattr(raw, 'fp', None)
    sock = getattr(getattr(fp, 'raw', fp), '_sock', None) or getattr(raw, '_sock', None)
    if sock is not None and hasattr(sock, 'settimeout'):
        try:
            sock.settimeout(timeout_seconds)
            return True
        except OSError:
            return False
    return False


class SplitTimeoutHTTPHandler(urllib.request.HTTPHandler):
    """Apply a short TCP connect timeout separately from header/stream read timeout."""
    def __init__(self, *, connect_timeout=DEFAULT_CONNECT_TIMEOUT_SECONDS, debuglevel=0):
        super().__init__(debuglevel=debuglevel)
        self._connect_timeout = connect_timeout

    def http_open(self, req):
        connect_limit = self._connect_timeout
        class _Connection(http.client.HTTPConnection):
            def connect(self):
                read_timeout = self.timeout
                self.timeout = min(connect_limit, read_timeout) if isinstance(read_timeout, (int, float)) else connect_limit
                try:
                    super().connect()
                finally:
                    self.timeout = read_timeout
                if self.sock is not None and read_timeout is not None:
                    self.sock.settimeout(read_timeout)
        return self.do_open(_Connection, req)


class SplitTimeoutHTTPSHandler(urllib.request.HTTPSHandler):
    """Apply a short TCP/TLS connect timeout separately from header/stream read timeout."""
    def __init__(self, *, context=None, connect_timeout=DEFAULT_CONNECT_TIMEOUT_SECONDS, debuglevel=0):
        super().__init__(debuglevel=debuglevel, context=context)
        self._connect_timeout = connect_timeout

    def https_open(self, req):
        connect_limit = self._connect_timeout
        class _Connection(http.client.HTTPSConnection):
            def connect(self):
                read_timeout = self.timeout
                self.timeout = min(connect_limit, read_timeout) if isinstance(read_timeout, (int, float)) else connect_limit
                try:
                    super().connect()
                finally:
                    self.timeout = read_timeout
                if self.sock is not None and read_timeout is not None:
                    self.sock.settimeout(read_timeout)
        return self.do_open(_Connection, req, context=self._context)


def validate_ca_file(value):
    if not value or not value.strip():
        return ''
    try:
        value = value.strip()
        if value.startswith('file:'):
            value = urllib.request.url2pathname(urllib.parse.urlsplit(value).path)
        path = Path(value).expanduser().resolve()
        if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError('Expected a readable PEM file up to 4 MiB')
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cafile=str(path))
        return str(path)
    except (ValueError, OSError) as cause:
        error = ValueError('CA 证书文件不存在、不可读或不是有效的 PEM 证书（最大 4 MiB）')
        error.code = 'UMEKO_CA_FILE_INVALID'
        raise error from cause


def tls_context(settings=None):
    """Extend platform trust for this provider only; keep peer/hostname checks."""
    settings = policy.get() if settings is None else settings
    context = ssl.create_default_context()
    if sys.platform == 'darwin':
        # Bundled OpenSSL can point to a Python installation absent on this Mac.
        defaults = ssl.get_default_verify_paths()
        if not (defaults.cafile or defaults.capath) and _MACOS_CA_FILE.is_file():
            context.load_verify_locations(cafile=str(_MACOS_CA_FILE))
    files = (os.environ.get('NODE_EXTRA_CA_CERTS'), os.environ.get('UMEKO_MODEL_CA_FILE'), (settings or {}).get('caFile'))
    for path in dict.fromkeys(file for file in files if file):
        context.load_verify_locations(cafile=validate_ca_file(path))
    return context


@contextmanager
def network_scope(settings=None, records=None):
    p = policy.set(settings)
    t = trace.set(trace.get() if records is None else records)
    try:
        yield
    finally:
        trace.reset(t)
        policy.reset(p)


def proxy_handler(settings=None, environment_proxy=True):
    settings = policy.get() if settings is None else settings
    mode = (settings or {}).get('mode', 'system' if environment_proxy else 'direct')
    if mode == 'direct':
        return urllib.request.ProxyHandler({})
    if mode == 'custom':
        address = settings.get('url', '')
        class ExplicitProxy(urllib.request.ProxyHandler):
            def proxy_open(self, request, proxy, protocol):
                # A custom provider proxy is explicit; system NO_PROXY must not
                # silently override it. Credentials belong to the system proxy.
                url = urllib.parse.urlsplit(proxy)
                original = request.type
                request.set_proxy(url.netloc, url.scheme)
                if original != url.scheme and original != 'https':
                    return self.parent.open(request, timeout=request.timeout)
        return ExplicitProxy({'http': address, 'https': address})
    return urllib.request.ProxyHandler()


class TracedResponse:
    def __init__(self, response, record, *, started_mono=None, started_at=None, headers_mono=None, headers_at=None):
        self.response, self.record = response, record
        now_mono = time.monotonic()
        now_iso = _utc_now()
        self._started_mono = now_mono if started_mono is None else started_mono
        self._headers_mono = now_mono if headers_mono is None else headers_mono
        self._first_event_mono = None
        self._last_data_mono = None
        self._bytes_received = 0
        self._sse_events = 0
        self._heartbeat_count = 0
        self._sse_line_tail = ''
        self._completed_normally = False
        content_type = ''
        if getattr(response, 'headers', None) is not None:
            content_type = str(response.headers.get('Content-Type', '') or '').lower()
        self._is_sse = 'event-stream' in content_type
        self.record['timing'] = {
            'phase': 'waiting_first_sse' if self._is_sse else 'waiting_body',
            'requestStartedAt': started_at or now_iso,
            'headersReceivedAt': headers_at or now_iso,
            'headersMs': max(0, round((self._headers_mono - self._started_mono) * 1000)),
            'firstEventAt': None,
            'firstEventMs': None,
            'lastDataAt': None,
            'lastDataToErrorMs': None,
            'totalMs': None,
            'bytesReceived': 0,
            'sseEvents': 0,
            'heartbeatCount': 0,
            'completedNormally': False,
        }

    def __getattr__(self, name):
        return getattr(self.response, name)

    def _observe_chunk(self, data):
        if not data:
            return
        now_mono = time.monotonic()
        now_iso = _utc_now()
        self._bytes_received += len(data)
        self._last_data_mono = now_mono
        decoded = data.decode('utf-8', 'replace')
        self.record['response']['body'] += decoded
        if self._is_sse:
            combined = self._sse_line_tail + decoded
            lines = combined.split('\n')
            self._sse_line_tail = lines.pop()
            for line in lines:
                if line.rstrip('\r').startswith(':'):
                    self._heartbeat_count += 1
        timing = self.record['timing']
        timing['lastDataAt'] = now_iso
        timing['bytesReceived'] = self._bytes_received
        timing['heartbeatCount'] = self._heartbeat_count

    def mark_event(self):
        now_mono = time.monotonic()
        timing = self.record['timing']
        if self._first_event_mono is None:
            self._first_event_mono = now_mono
            timing['firstEventAt'] = _utc_now()
            timing['firstEventMs'] = max(0, round((now_mono - self._started_mono) * 1000))
            timing['phase'] = 'streaming'
        self._sse_events += 1
        timing['sseEvents'] = self._sse_events

    def mark_completed(self):
        now_mono = time.monotonic()
        self._completed_normally = True
        timing = self.record['timing']
        timing['completedNormally'] = True
        timing['phase'] = 'completed'
        timing['totalMs'] = max(0, round((now_mono - self._started_mono) * 1000))

    def mark_failed(self, error):
        timing = self.record['timing']
        if timing['lastDataToErrorMs'] is not None:
            return
        now_mono = time.monotonic()
        timing['completedNormally'] = False
        timing['totalMs'] = max(0, round((now_mono - self._started_mono) * 1000))
        anchor = self._last_data_mono if self._last_data_mono is not None else self._headers_mono
        timing['lastDataToErrorMs'] = max(0, round((now_mono - anchor) * 1000))
        if isinstance(error, (http.client.IncompleteRead, http.client.RemoteDisconnected, ConnectionError)) or \
                'Upstream stream ended before completion' in str(error):
            timing['phase'] = 'incomplete_stream'
        elif isinstance(error, TimeoutError) or isinstance(getattr(error, 'reason', None), TimeoutError):
            if self._is_sse:
                timing['phase'] = 'waiting_first_sse' if self._first_event_mono is None else 'stream_idle'
            else:
                timing['phase'] = 'waiting_body'
        elif timing.get('phase') not in ('waiting_headers', 'waiting_first_sse', 'stream_idle', 'incomplete_stream'):
            timing['phase'] = 'stream_error'

    def _read(self, method, *args):
        try:
            data = getattr(self.response, method)(*args)
        except (OSError, http.client.HTTPException) as error:
            self.mark_failed(error)
            raise
        self._observe_chunk(data)
        return data

    def read(self, *args):
        return self._read('read', *args)

    def readline(self, *args):
        return self._read('readline', *args)

    def read1(self, *args):
        return self._read('read1' if hasattr(self.response, 'read1') else 'read', *args)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.response.close()

    def __iter__(self):
        return iter(self.readline, b'')


def secret_values(value):
    found = []
    def add(item):
        if isinstance(item, str):
            found.extend([item, re.sub(r'^Bearer\s+', '', item, flags=re.I)])
        elif isinstance(item, dict):
            for child in item.values(): add(child)
        elif isinstance(item, list):
            for child in item: add(child)
    def walk(item):
        if isinstance(item, dict):
            for key, child in item.items():
                normalized = key.lower().replace('-', '_')
                if re.search(r'authorization|api_?key|cookie|password|token$|client_secret', normalized): add(child)
                else: walk(child)
        elif isinstance(item, list):
            for child in item: walk(child)
    walk(value)
    return found


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {k: '[REDACTED]' if re.search(r'authorization|api_?key|cookie|password|token$|client_secret', k.lower().replace('-', '_'))
                else redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if isinstance(secret, str) and len(secret) >= 3:
                value = value.replace(secret, '[REDACTED]')
        value = re.sub(r'(https?://)[^\s/@]+:[^\s/@]+@', r'\1[REDACTED]@', value)
        return value
    return value
