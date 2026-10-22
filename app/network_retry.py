"""Classify transient transport failures without retrying login/configuration errors."""
import json
import re


def transient_failure(error, http=()):
    responses = [item.get('response', {}) for item in http]
    detail = str(error) + ' ' + json.dumps([r.get('body') for r in responses], ensure_ascii=False)
    if re.search(r'insufficient_quota|quota exceeded|out of budget|billing|usage limit reached|invalid.?api.?key|unauthorized|authentication|certificate|CERT_|self.signed|额度不足|余额不足', detail, re.I):
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
    return {'type': 'upstream_error', 'code': 'umeko_stream_interrupted' if retryable else 'umeko_request_failed',
            'retryable': retryable, 'message': ('Network error: stream interrupted. ' if retryable else '') + str(error)}
