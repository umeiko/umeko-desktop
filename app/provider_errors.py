"""Shared provider error formatting for the gateway and model discovery."""
import re
from umeko_provider_sdk.errors import MAX_ERROR_LENGTH, format_http_error, safe_text

_TIMEOUT_OR_STREAM_SUMMARY_PATTERNS = (
    r'发出请求后等待响应头超时，请检查网络或在供应商的网络设置中调大流式空闲超时',
    r'收到响应头后等待首条模型输出超时，请检查网络或在供应商的网络设置中调大流式空闲超时',
    r'流式输出中途长时间未收到数据而超时，请检查网络或在供应商的网络设置中调大流式空闲超时',
    r'等待模型输出超时，请检查网络或在供应商的网络设置中调大流式空闲超时',
    r'供应商请求超时，请检查网络或超时设置',
    r'接收模型输出时未收到正常结束标记即断流，请稍后重试',
    r'接收模型输出时连接中断，请稍后重试',
)


def diagnostic_notice(message):
    """Remove Pi's transport wrapper and report marker, retaining the summary."""
    for pattern in (
        r'模型组中的可用模型均请求失败.*?(?=\s*\[Umeko:|$)',
        r'供应商返回 HTTP \d+：.*?(?=\s*\[Umeko:|$)',
        *_TIMEOUT_OR_STREAM_SUMMARY_PATTERNS,
        r'无法连接供应商：.*?(?=\s*\[Umeko:|$)',
    ):
        match = re.search(pattern, message)
        if match:
            return match[0].strip()
    # Older transcripts still contain only the report marker.
    return '供应商请求失败，请查看请求详情'


def is_staged_continue_failure(message):
    """Offer staged continuation after exhausted timeout or stream-interruption failures."""
    text = str(message or '')
    if not text:
        return False
    if re.search(r'insufficient_quota|quota exceeded|额度不足|余额不足|invalid.?api.?key|authentication|HTTP 401|HTTP 402|HTTP 403|HTTP 404|HTTP 400|HTTP 422', text, re.I):
        return False
    return bool(re.search(
        r'发出请求后等待响应头超时|收到响应头后等待首条模型输出超时|流式输出中途长时间未收到数据而超时|'
        r'等待模型输出超时|供应商请求超时|接收模型输出时未收到正常结束标记即断流|接收模型输出时连接中断|'
        r'Upstream stream ended before completion|供应商返回 HTTP (?:408|504)\b|供应商服务端处理超时|'
        r'模型组中的可用模型均请求失败|stream interrupted|timed? out',
        text, re.I,
    ))
