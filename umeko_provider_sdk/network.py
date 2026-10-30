"""Per-provider networking and opt-in, credential-redacted request diagnostics."""
from contextlib import contextmanager
from contextvars import ContextVar
import urllib.request
import urllib.parse
import re
import os
import ssl
from pathlib import Path

policy = ContextVar('umeko_network_policy', default=None)
trace = ContextVar('umeko_network_trace', default=None)


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
    def __init__(self, response, record):
        self.response, self.record = response, record
    def __getattr__(self, name):
        return getattr(self.response, name)
    def _read(self, method, *args):
        data = getattr(self.response, method)(*args)
        self.record['response']['body'] += data.decode('utf-8', 'replace')
        return data
    def read(self, *args):
        return self._read('read', *args)
    def readline(self, *args):
        return self._read('readline', *args)
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
