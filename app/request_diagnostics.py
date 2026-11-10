"""Private local failure reports. No credentials or reports are sent to telemetry."""
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from PySide6.QtCore import QObject, Signal
from umeko_provider_sdk.network import redact, secret_values
from .network_retry import transient_failure, certificate_failure, describe_failure
from .provider_errors import format_http_error, safe_text


class RequestFailure(ValueError):
    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


class RequestDiagnostics(QObject):
    changed = Signal()

    def __init__(self, directory, parent=None):
        super().__init__(parent)
        self.directory = directory / 'request-errors'
        self.lock = threading.Lock()

    def failure(self, provider, request, response, error, http=None):
        record = {'id': str(uuid.uuid4()), 'at': datetime.now(timezone.utc).isoformat(),
                  'provider': provider.get('name', ''), 'request': request,
                  'response': response, 'error': describe_failure(error), 'http': http or []}
        record = redact(record, [provider.get('key', '')] + secret_values(record))
        failed_response = record['http'][-1].get('response', record['response']) if record['http'] else record['response']
        status = failed_response.get('status')
        code = certificate_failure(error)
        if str(status).isdigit() and int(status) >= 400:
            message = format_http_error(status, failed_response.get('body', ''), failed_response.get('headers', {}))
        elif code:
            message = f'TLS certificate validation failed ({code}); check the provider\'s Network settings and CA file, then open request details'
        elif str(error).startswith('供应商返回 HTTP 200：'):
            message = str(error)
        elif isinstance(error, TimeoutError) or isinstance(getattr(error, 'reason', None), TimeoutError) or str(error) == '供应商请求超时，请检查网络或超时设置':
            message = '供应商请求超时，请检查网络或超时设置'
        else:
            message = '供应商请求失败：' + safe_text(str(error), [provider.get('key', '')])
        record['summary'] = safe_text(message, [provider.get('key', '')])
        with self.lock:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = self.directory / (record['id'] + '.json')
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
            path.chmod(0o600)
            for old in sorted(self.directory.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)[30:]:
                old.unlink()
        self.changed.emit()
        managed = bool(record['http'] and record['http'][-1].get('httpRetryManaged'))
        failure = RequestFailure(f'{record["summary"]} [Umeko:{record["id"]}]',
                                 transient_failure(error, http or []) and not managed)
        failure.http_retry_managed = managed
        failure.tls_code = code
        return failure

    def read(self, identifier):
        if not re.fullmatch(r'[a-f0-9-]{36}', identifier):
            return ''
        try:
            return (self.directory / (identifier + '.json')).read_text(encoding='utf-8')
        except OSError:
            return ''
