"""Optional standard-library HTTP helpers with TLS and scoped redirects."""
import http.cookiejar
import json
import urllib.error
import urllib.parse
import urllib.request
import traceback
from html.parser import HTMLParser
from http.cookies import SimpleCookie

from . import ProviderError
from .network import proxy_handler, tls_context, trace, TracedResponse


def response_cookies(headers):
    """Read all Set-Cookie headers, including values with commas in Expires."""
    values = {}
    for line in headers.get_all("Set-Cookie", []):
        jar = SimpleCookie()
        jar.load(line)
        values.update((key, morsel.value) for key, morsel in jar.items())
    return values


def _origin(url, allow_http=False):
    parsed = urllib.parse.urlsplit(url)
    if not parsed.hostname or parsed.username or parsed.password or parsed.scheme not in ("http", "https"):
        raise ProviderError("服务地址无效")
    if not allow_http and parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ProviderError("远程服务需要 HTTPS")
    return parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == "https" else 80)


def origin(url):
    return _origin(url)


class HttpSession:
    def __init__(self, allowed_urls, *, environment_proxy=True, allowed_http_urls=()):
        self.http_bases = []
        for url in allowed_http_urls:
            parsed = urllib.parse.urlsplit(url)
            if parsed.scheme != "http" or parsed.query or parsed.fragment:
                raise ProviderError("HTTP 许可必须是明确的服务基础地址")
            self.http_bases.append((_origin(url, True), parsed.path.rstrip("/")))
        self.origins = {self._origin(url) for url in allowed_urls if url}
        self.cookies = http.cookiejar.CookieJar()
        owner = self
        class Redirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                owner.validate(newurl)
                result = super().redirect_request(req, fp, code, msg, headers, newurl)
                if result and owner._origin(newurl) != owner._origin(req.full_url):
                    for key in ("Authorization", "Cookie", "X-auth-token", "X-refresh-token", "X-api-key", "Api-key"):
                        result.remove_header(key)
                return result
        handlers = [Redirect(), urllib.request.HTTPCookieProcessor(self.cookies)]
        handlers.append(proxy_handler(environment_proxy=environment_proxy))
        handlers.append(urllib.request.HTTPSHandler(context=tls_context()))
        self.opener = urllib.request.build_opener(*handlers)

    def _origin(self, url):
        parsed = urllib.parse.urlsplit(url)
        candidate = _origin(url, True)
        if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            path = urllib.parse.unquote(parsed.path)
            if any(segment in (".", "..") for segment in path.split("/")) or "\\" in path:
                raise ProviderError("HTTP 服务路径无效")
            if any(candidate == allowed and (path == base or path.startswith(base + "/"))
                   for allowed, base in self.http_bases):
                return candidate
        return origin(url)

    def validate(self, url):
        if self._origin(url) not in self.origins: raise ProviderError("登录返回了未配置的服务地址")

    def request(self, url, *, method="GET", headers=None, data=None, timeout=20):
        self.validate(url)
        headers = {"User-Agent":"Umeko-Provider/0.1", **(headers or {})}
        if isinstance(data, (dict, list)):
            data = json.dumps(data, ensure_ascii=False).encode()
            headers.setdefault("Content-Type", "application/json")
        elif isinstance(data, str): data = data.encode()
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        records = trace.get()
        record = {'request': {'url': url, 'method': method, 'headers': headers,
                  'body': data.decode('utf-8', 'replace') if isinstance(data, bytes) else data},
                  'response': {'status': None, 'headers': {}, 'body': ''}}
        if records is not None:
            records.append(record)
        try:
            response = self.opener.open(req, timeout=timeout)
            record['response'].update(status=response.status, headers=dict(response.headers))
            return TracedResponse(response, record) if records is not None else response
        except urllib.error.HTTPError as error:
            record['response'].update(status=error.code, headers=dict(error.headers), body=error.read().decode('utf-8', 'replace'))
            error.close()
            raise ProviderError("服务返回 HTTP " + str(error.code)) from None
        except OSError:
            record['exception'] = traceback.format_exc()
            raise ProviderError("无法连接服务，请检查网络和证书") from None


class ConsentForm(HTMLParser):
    """Read form controls without depending on attribute order or quote style."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.action, self.values = "", []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form" and not self.action: self.action = attrs.get("action", "")
        if tag == "input" and attrs.get("name") and (attrs.get("type", "").lower() == "hidden" or attrs["name"] == "scope"):
            self.values.append((attrs["name"], attrs.get("value", "")))
