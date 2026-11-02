"""Bounded, credential-redacted summaries of provider HTTP responses."""
import json
import re
from html import unescape

from .network import redact, secret_values

MAX_ERROR_LENGTH = 1000


def safe_text(value, secrets=()):
    text = redact(str(value), secrets)
    text = re.sub(r'(?im)\b(?:set-cookie|cookie)\s*:\s*[^\r\n]+', 'Cookie: [REDACTED]', text)
    # Providers sometimes echo credentials in prose instead of structured fields.
    text = re.sub(r'(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+', r'\1 [REDACTED]', text)
    text = re.sub(r'''(?ix)(["']?(?:authorization|proxy-authorization|x-api-key|api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|client[_-]?secret|cookie|set-cookie)["']?\s*[:=]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;}]+)''', r'\1[REDACTED]', text)
    text = re.sub(r'\bsk-[A-Za-z0-9_-]+|\bAKIA[A-Z0-9]{16}\b|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[REDACTED]', text)
    return text


def _line(value):
    text = str(value)
    text = re.sub(r'(?is)<(script|style)\b[^>]*>.*?(?:</\1\s*>|$)', ' ', text)
    text = re.sub(r'(?s)<!--.*?-->|<[^>]+>', ' ', text)
    return re.sub(r'[\s\x00-\x1f\x7f]+', ' ', unescape(text)).strip()


def format_http_error(status, body='', headers=None, secrets=()):
    """Keep upstream wording; translate the surrounding UI text with I18n.t."""
    headers = headers or {}
    if isinstance(body, bytes):
        body = body.decode('utf-8', 'replace')
    try:
        payload = json.loads(body) if isinstance(body, str) else body
    except (ValueError, TypeError, RecursionError):
        payload = None
    secrets = list(secrets) + secret_values(payload) + secret_values(headers)
    details = payload.get('error', payload) if isinstance(payload, dict) else payload
    reason, metadata = '', []
    if isinstance(details, dict):
        reason = details.get('message') or details.get('detail') or ''
        if not reason and details is not payload:
            reason = payload.get('message') or payload.get('detail') or ''
        for name in ('type', 'param', 'code'):
            value = details.get(name)
            if value is not None and value != '':
                metadata.append(f'{name}={value}')
    elif isinstance(details, str):
        reason = details
    if not isinstance(reason, str):
        reason = json.dumps(reason, ensure_ascii=False)
    reason = _line(safe_text(_line(reason or body or ''), secrets))
    metadata_text = (' [' + ', '.join(_line(safe_text(_line(item), secrets))[:100] for item in metadata) + ']') if metadata else ''
    reason = reason or '服务器未返回错误详情'
    try:
        status = int(status)
    except (ValueError, TypeError):
        status = 0
    if status in (401, 403):
        hint = '请检查 API 密钥与权限'
    elif status == 404:
        hint = '请检查地址或模型名称'
    elif status == 408:
        hint = '请求超时，请检查网络或超时设置'
    elif status == 413:
        hint = '请求过大或上下文过长'
    elif status == 429:
        hint = '请求受到限流，请稍后重试'
    elif 500 <= status <= 599:
        hint = '供应商服务端错误'
    elif re.search(r'context[_ -]?(?:length|window)|maximum context|too many tokens|上下文.{0,8}(?:超|长)|上下文长度', reason + metadata_text, re.I):
        hint = '请求过大或上下文过长'
    else:
        hint = ''
    retry_after = next((value for key, value in headers.items() if key.lower() == 'retry-after'), '')
    suffix = metadata_text + (('（提示：' + hint + '）') if hint else '')
    if status == 429 and retry_after:
        suffix += ' [Retry-After: ' + _line(safe_text(retry_after, secrets))[:100] + ']'
    prefix = f'供应商返回 HTTP {status}：'
    available = MAX_ERROR_LENGTH - len(prefix) - len(suffix)
    if len(reason) > available:
        reason = reason[:available - 1] + '…'
    return prefix + reason + suffix
