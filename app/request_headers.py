"""User-editable headers for Umeko's built-in model transports only."""
import re
import urllib.request

DEFAULTS = [
    {'id': 'content-type', 'name': 'Content-Type', 'value': 'application/json', 'enabled': True},
    {'id': 'user-agent', 'name': 'User-Agent', 'value': 'Umeko-Desktop', 'enabled': True},
    {'id': 'authorization', 'name': 'Authorization', 'value': 'Bearer {{apiKey}}', 'enabled': True},
    {'id': 'x-api-key', 'name': 'x-api-key', 'value': '{{apiKey}}', 'enabled': True},
    {'id': 'anthropic-version', 'name': 'anthropic-version', 'value': '2023-06-01', 'enabled': True},
]
SCOPES = {'authorization': 'openai', 'x-api-key': 'anthropic', 'anthropic-version': 'anthropic'}
MANAGED = {'host', 'content-length', 'transfer-encoding', 'connection', 'proxy-authorization',
           'proxy-connection', 'upgrade', 'trailer', 'te'}


def validate(value):
    if not isinstance(value, list) or len(value) > 32:
        raise ValueError('请求头最多可设置 32 项')
    rows, identifiers = [], set()
    for row in value:
        if (not isinstance(row, dict) or set(row) != {'id', 'name', 'value', 'enabled'}
                or not isinstance(row['id'], str) or not re.fullmatch(r'[a-z0-9-]{1,64}', row['id'])
                or row['id'] in identifiers or type(row['enabled']) is not bool):
            raise ValueError('请求头配置格式无效')
        name, text = row['name'], row['value']
        if (not isinstance(name, str) or len(name) > 128
                or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name)):
            raise ValueError('请求头名称只能包含英文字母、数字和 HTTP 字段符号')
        if name.lower() in MANAGED:
            raise ValueError('此请求头由网络传输管理，不能自定义')
        if (not isinstance(text, str) or len(text) > 4096
                or any(ord(c) < 32 or ord(c) == 127 or ord(c) > 255 for c in text)):
            raise ValueError('请求头值不能包含换行、控制字符或非 Latin-1 字符，且最多 4096 字符')
        identifiers.add(row['id'])
        rows.append(dict(row))
    rows = [dict(row) for row in DEFAULTS if row['id'] not in identifiers] + rows
    if len(rows) > 32:
        raise ValueError('请求头最多可设置 32 项')
    for protocol in ('openai', 'anthropic'):
        names = [row['name'].lower() for row in rows if row['enabled'] and SCOPES.get(row['id'], protocol) == protocol]
        if len(names) != len(set(names)):
            raise ValueError('启用的请求头名称不能重复（不区分大小写）')
    return rows


def build(value, provider):
    rows = validate(value if value is not None else [])
    protocol = 'anthropic' if provider.get('api') == 'anthropic' else 'openai'
    rows = [row for row in rows if SCOPES.get(row['id'], protocol) == protocol]
    headers = {row['name']: row['value'].replace('{{apiKey}}', provider.get('key', ''))
               for row in rows if row['enabled']}
    if any(len(text) > 4096 or any(ord(c) < 32 or ord(c) == 127 or ord(c) > 255 for c in text) for text in headers.values()):
        raise ValueError('展开密钥后的请求头值无效或超过 4096 字符')
    # Prevent urllib/undici from silently restoring disabled or renamed defaults.
    present = {name.lower() for name in headers}
    omitted = {row['name'].lower() for row in rows if not row['enabled']}
    omitted.update(row['name'].lower() for row in DEFAULTS if SCOPES.get(row['id'], protocol) == protocol)
    return headers, omitted - present


class OmitHeaders(urllib.request.BaseHandler):
    handler_order = 600  # Run after urllib's default Content-Type/User-Agent insertion.

    def __init__(self, omitted):
        self.omitted = omitted

    def http_request(self, request):
        for name in tuple(request.header_items()):
            if name[0].lower() in self.omitted:
                request.remove_header(name[0])
        return request

    https_request = http_request
