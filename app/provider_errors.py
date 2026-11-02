"""Shared provider error formatting for the gateway and model discovery."""
from umeko_provider_sdk.errors import MAX_ERROR_LENGTH, format_http_error, safe_text


def diagnostic_notice(message):
    """Remove Pi's transport wrapper and report marker, retaining the summary."""
    import re
    match = re.search(r'供应商返回 HTTP \d+：.*?(?=\s*\[Umeko:|$)', message)
    if match:
        return match[0].strip()
    if '供应商请求超时，请检查网络或超时设置' in message:
        return '供应商请求超时，请检查网络或超时设置'
    # Older transcripts still contain only the report marker.
    return '供应商请求失败，请查看请求详情'
