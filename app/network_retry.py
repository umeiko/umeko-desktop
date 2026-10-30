"""Classify transient transport failures without retrying login/configuration errors."""
import json
import re
import ssl


def describe_failure(error, seen=None):
    if not isinstance(error, BaseException):
        return str(error)
    seen = set() if seen is None else seen
    if id(error) in seen:
        return '[Circular error]'
    seen.add(id(error))
    result = {'name': type(error).__name__, 'message': str(error)}
    code = getattr(error, 'code', None)
    if code is not None:
        result['code'] = code
    if getattr(error, 'verify_message', None):
        result.update(verifyCode=error.verify_code, verifyMessage=error.verify_message)
    nested = getattr(error, 'reason', None) or error.__cause__ or error.__context__
    if nested:
        result['cause'] = describe_failure(nested, seen)
    if getattr(error, 'exceptions', None):
        result['errors'] = [describe_failure(item, seen) for item in error.exceptions]
    return result


def certificate_failure(error):
    pending, seen = [error], set()
    while pending:
        current = pending.pop()
        if not isinstance(current, BaseException) or id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, ssl.SSLCertVerificationError):
            return 'CERTIFICATE_VERIFY_FAILED'
        # Only structured codes identify TLS failures; messages may quote a
        # certificate filename or contain unrelated request/response content.
        for value in (getattr(current, 'code', None), getattr(current, 'reason', None),
                      getattr(current, 'tls_code', None)):
            if isinstance(value, str) and re.fullmatch(r'UMEKO_CA_[A-Z_]+|ERR_TLS_CERT_[A-Z_]+|CERTIFICATE_VERIFY_FAILED|SELF_SIGNED_CERT_IN_CHAIN|DEPTH_ZERO_SELF_SIGNED_CERT|UNABLE_TO_VERIFY_LEAF_SIGNATURE|UNABLE_TO_GET_ISSUER_CERT(?:_LOCALLY)?|CERT_[A-Z_]+', value, re.I):
                return value.upper()
        pending.extend((getattr(current, 'reason', None), current.__cause__, current.__context__))
        pending.extend(getattr(current, 'exceptions', ()))
    return ''


def transient_failure(error, http=()):
    if certificate_failure(error):
        return False
    responses = [item.get('response', {}) for item in http]
    detail = json.dumps(describe_failure(error), ensure_ascii=False) + ' ' + json.dumps([r.get('body') for r in responses if str(r.get('status', '')).isdigit() and int(r['status']) >= 400], ensure_ascii=False)
    if re.search(r'insufficient_quota|quota exceeded|out of budget|billing|usage limit reached|invalid.?api.?key|unauthorized|authentication|额度不足|余额不足', detail, re.I):
        return False
    status = next((r.get('status') for r in reversed(responses) if r.get('status')), 0)
    try:
        status = int(status)
    except (TypeError, ValueError):
        status = 0
    if 400 <= status < 500 and status not in (408, 425, 429):
        return False
    if status in (408, 425, 429) or status >= 500:
        return True
    return bool(re.search(r'ECONNRESET|ECONNREFUSED|ETIMEDOUT|ENOTFOUND|EAI_AGAIN|network.?error|fetch failed|connection(?:reset|aborted|refused)error|connection (?:reset|lost|closed|refused)|socket (?:hang up|closed)|timed? out|timeout|terminated|incomplete.?read|remote.?disconnected|premature|stream (?:interrupted|ended|failed)|overloaded|rate.?limit|server_busy|temporarily unavailable|供应商流已中断|连接.*(?:中断|重置|超时)|网络.*(?:中断|超时)', detail, re.I))


def upstream_failure(error):
    retryable = bool(getattr(error, 'retryable', False))
    return {'type': 'upstream_error', 'code': 'umeko_tls_certificate' if getattr(error, 'tls_code', '') else 'umeko_stream_interrupted' if retryable else 'umeko_request_failed',
            **({'tlsCode': error.tls_code} if getattr(error, 'tls_code', '') else {}),
            'retryable': retryable, 'message': ('Network error: stream interrupted. ' if retryable else '') + str(error)}
