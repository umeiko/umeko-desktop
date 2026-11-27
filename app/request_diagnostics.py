"""Private local request reports. Credentials are redacted before persistence."""
from http.client import IncompleteRead, RemoteDisconnected
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from PySide6.QtCore import QObject, Signal
from umeko_provider_sdk.network import redact, secret_values
from .network_retry import transient_failure, certificate_failure, describe_failure
from .provider_errors import format_http_error, safe_text

_STREAM_PHASE_LABELS = {
    'waiting_headers': '发出请求后等待响应头',
    'waiting_first_sse': '收到响应头后等待首条 SSE 事件',
    'waiting_body': '收到响应头后等待响应正文',
    'stream_idle': '流式输出中途长时间无数据',
    'incomplete_stream': '未收到正常结束标记即断流',
    'http_error': '供应商返回 HTTP 错误',
    'completed': '已正常结束',
}


def _stream_diagnostics(http_calls):
    for call in reversed(http_calls or ()):
        timing = call.get('timing')
        if isinstance(timing, dict):
            phase = str(timing.get('phase') or '')
            return {**timing, 'phaseLabel': _STREAM_PHASE_LABELS.get(phase, phase)}
    return None


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
        self.latest = {}

    @staticmethod
    def _secrets(provider, record):
        # Custom names can carry credentials as well as standard auth headers.
        header_values = [value for call in record.get('http', [])
                         for value in call.get('request', {}).get('headers', {}).values()]
        return [provider.get('key', '')] + secret_values(record) + header_values

    @staticmethod
    def _details(record):
        result = []
        for call in record.get('http', []):
            for detail in call.get('compatibility', []):
                if detail not in result:
                    result.append(detail)
        return result

    def latest_compatibility(self, provider_id, language='zh'):
        with self.lock:
            record = self.latest.get(provider_id)
            if not record:
                return {'compatibilityNotice': '', 'compatibilityReportId': ''}
            lines = []
            for detail in record['details']:
                name, days = detail['parameter'], detail['ageDays']
                if language == 'en':
                    action = f'changed {name} to auto' if detail['action'] == 'auto' else f'omitted {name}'
                    unit = 'day' if days == 1 else 'days'
                    age = 'recorded today' if days == 0 else f'recorded {days} {unit} ago'
                    lines.append(f'Previous rejection: {action} ({age})')
                else:
                    action = f'将 {name} 改为 auto' if detail['action'] == 'auto' else f'省略 {name}'
                    age = '今天记录' if days == 0 else f'{days} 天前记录'
                    lines.append(f'已按此前的拒绝记录{action}（{age}）')
            if not lines:
                lines.append('Request succeeded after retry' if language == 'en' else '请求已重试成功')
            return {'compatibilityNotice': '；'.join(lines), 'compatibilityReportId': record['id']}

    def _persist(self, record):
        with self.lock:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = self.directory / (record['id'] + '.json')
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
            path.chmod(0o600)
            details = self._details(record)
            retried = 'error' not in record and any(call.get('parameterRetry') for call in record.get('http', []))
            if (details or retried) and record.get('providerId'):
                self.latest[record['providerId']] = {'id': record['id'], 'details': details}
            elif record.get('providerId'):
                self.latest.pop(record['providerId'], None)
            expired = sorted(self.directory.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)[30:]
            for old in expired:
                old.unlink()
            removed = {old.stem for old in expired}
            self.latest = {key: value for key, value in self.latest.items() if value['id'] not in removed}
        self.changed.emit()

    def compatibility(self, provider, request, http):
        """Keep a successful cached adjustment accessible through request details."""
        if not (self._details({'http': http}) or any(call.get('parameterRetry') for call in http)):
            with self.lock:
                cleared = self.latest.pop(provider.get('id', ''), None)
            if cleared:
                self.changed.emit()
            return ''
        record = {'id': str(uuid.uuid4()), 'at': datetime.now(timezone.utc).isoformat(),
                  'providerId': provider.get('id', ''), 'provider': provider.get('name', ''),
                  'request': request, 'response': http[-1].get('response', {}) if http else {}, 'http': http}
        timing = _stream_diagnostics(http)
        if timing:
            record['streamDiagnostics'] = timing
        record = redact(record, self._secrets(provider, record))
        self._persist(record)
        return record['id']

    def failure(self, provider, request, response, error, http=None):
        http_calls = http or []
        record = {'id': str(uuid.uuid4()), 'at': datetime.now(timezone.utc).isoformat(),
                  'providerId': provider.get('id', ''), 'provider': provider.get('name', ''), 'request': request,
                  'response': response, 'error': describe_failure(error), 'http': http_calls}
        timing = _stream_diagnostics(http_calls)
        if timing:
            record['streamDiagnostics'] = timing
        secrets = self._secrets(provider, record)
        record = redact(record, secrets)
        failed_response = record['http'][-1].get('response', record['response']) if record['http'] else record['response']
        status = failed_response.get('status')
        phase = (record.get('streamDiagnostics') or {}).get('phase', '')
        code = certificate_failure(error)
        error_text = str(error)
        if str(status).isdigit() and int(status) >= 400:
            message = format_http_error(status, failed_response.get('body', ''), failed_response.get('headers', {}))
        elif code:
            message = f'TLS certificate validation failed ({code}); check the provider\'s Network settings and CA file, then open request details'
        elif error_text.startswith('供应商返回 HTTP 200：'):
            message = error_text
        elif isinstance(error, TimeoutError) or isinstance(getattr(error, 'reason', None), TimeoutError) or error_text in (
                '发出请求后等待响应头超时，请检查网络或在供应商的网络设置中调大流式空闲超时',
                '收到响应头后等待首条模型输出超时，请检查网络或在供应商的网络设置中调大流式空闲超时',
                '流式输出中途长时间未收到数据而超时，请检查网络或在供应商的网络设置中调大流式空闲超时',
                '等待模型输出超时，请检查网络或在供应商的网络设置中调大流式空闲超时',
                '供应商请求超时，请检查网络或超时设置'):
            if phase == 'waiting_headers' or error_text.startswith('发出请求后等待响应头超时'):
                message = '发出请求后等待响应头超时，请检查网络或在供应商的网络设置中调大流式空闲超时'
            elif phase == 'waiting_first_sse' or error_text.startswith('收到响应头后等待首条模型输出超时'):
                message = '收到响应头后等待首条模型输出超时，请检查网络或在供应商的网络设置中调大流式空闲超时'
            elif phase == 'stream_idle' or error_text.startswith('流式输出中途长时间未收到数据而超时'):
                message = '流式输出中途长时间未收到数据而超时，请检查网络或在供应商的网络设置中调大流式空闲超时'
            else:
                message = '等待模型输出超时，请检查网络或在供应商的网络设置中调大流式空闲超时'
        elif isinstance(error, (ConnectionError, IncompleteRead, RemoteDisconnected)) or \
                'Upstream stream ended before completion' in error_text or error_text in (
                '接收模型输出时未收到正常结束标记即断流，请稍后重试',
                '接收模型输出时连接中断，请稍后重试'):
            if phase == 'incomplete_stream' or 'Upstream stream ended before completion' in error_text or \
                    error_text.startswith('接收模型输出时未收到正常结束标记即断流'):
                message = '接收模型输出时未收到正常结束标记即断流，请稍后重试'
            else:
                message = '接收模型输出时连接中断，请稍后重试'
        elif error_text.startswith('无法连接供应商：'):
            message = error_text
        else:
            message = '供应商请求失败：' + safe_text(error_text, [provider.get('key', '')])
        record['summary'] = safe_text(message, secrets)
        self._persist(record)
        managed = bool(record['http'] and record['http'][-1].get('httpRetryManaged'))
        failure = RequestFailure(f'{record["summary"]} [Umeko:{record["id"]}]',
                                 transient_failure(error, http_calls) and not managed)
        failure.http_retry_managed = managed
        failure.tls_code = code
        failure.gateway_timeout = failure.retryable and (
            status == 504 or (
                phase in ('waiting_first_sse', 'stream_idle')
                and (isinstance(error, TimeoutError) or isinstance(getattr(error, 'reason', None), TimeoutError))
            )
        )
        return failure

    def read(self, identifier):
        if not re.fullmatch(r'[a-f0-9-]{36}', identifier):
            return ''
        try:
            return (self.directory / (identifier + '.json')).read_text(encoding='utf-8')
        except OSError:
            return ''
