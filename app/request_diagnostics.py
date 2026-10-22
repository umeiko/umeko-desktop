"""Private local failure reports. No credentials or reports are sent to telemetry."""
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from PySide6.QtCore import QObject, Signal
from umeko_provider_sdk.network import redact, secret_values
from .network_retry import transient_failure


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
                  'response': response, 'error': str(error), 'http': http or []}
        record = redact(record, [provider.get('key', '')] + secret_values(record))
        with self.lock:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = self.directory / (record['id'] + '.json')
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
            path.chmod(0o600)
            for old in sorted(self.directory.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)[30:]:
                old.unlink()
        self.changed.emit()
        return RequestFailure(f'供应商请求失败，请查看请求详情 [Umeko:{record["id"]}]', transient_failure(error, http or []))

    def read(self, identifier):
        if not re.fullmatch(r'[a-f0-9-]{36}', identifier):
            return ''
        try:
            return (self.directory / (identifier + '.json')).read_text(encoding='utf-8')
        except OSError:
            return ''
