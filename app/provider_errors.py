"""Shared provider error formatting for the gateway and model discovery."""
from umeko_provider_sdk.errors import MAX_ERROR_LENGTH, format_http_error, safe_text


def diagnostic_notice(message):
    """Remove Pi's transport wrapper and report marker, retaining the summary."""
    import re
    for pattern in (
        r'模型组中的可用模型均请求失败.*?(?=\s*\[Umeko:|$)',
        r'供应商返回 HTTP \d+：.*?(?=\s*\[Umeko:|$)',
        r'等待模型输出超时，请检查网络或在供应商的网络设置中调大流式空闲超时',
        r'供应商请求超时，请检查网络或超时设置',
        r'接收模型输出时连接中断，请稍后重试',
        r'无法连接供应商：.*?(?=\s*\[Umeko:|$)',
    ):
        match = re.search(pattern, message)
        if match:
            return match[0].strip()
    # Older transcripts still contain only the report marker.
    return '供应商请求失败，请查看请求详情'
