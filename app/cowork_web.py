"""Desktop-owned proxy settings for Cowork web requests and connection tests."""
from __future__ import annotations

import json
import secrets
import subprocess
import sys
from urllib.parse import quote, urlsplit
from urllib.request import getproxies_environment, proxy_bypass_environment

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtNetwork import QNetworkProxy, QNetworkProxyFactory, QNetworkProxyQuery

from umeko_provider_sdk.network import validate_ca_file

from .pi_runtime import CREATE_NO_WINDOW, node_environment, node_executable
from .storage import protect

_DEFAULTS = {'mode': 'system', 'proxy': '', 'caFile': '', 'username': '', 'credential': ''}
_PROXY_SCHEMES = {'http', 'https', 'socks5', 'socks5h'}


def _endpoint(value, schemes):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(char) < 33 for char in value):
        raise ValueError('请输入有效的地址 / Enter a valid URL')
    parsed = urlsplit(value)
    hostname = parsed.hostname
    if parsed.scheme not in schemes or not hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError('地址必须包含协议和主机名 / A scheme and hostname are required')
    port = parsed.port
    if port == 0 or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise ValueError('请输入协议、主机和端口 / Supply a scheme, hostname and port')
    address = f'[{hostname}]' if ':' in hostname else hostname.encode('idna').decode()
    default = {'http': 80, 'https': 443, 'socks5': 1080, 'socks5h': 1080}[parsed.scheme]
    return f'{parsed.scheme}://{address}' + (f':{port}' if port and port != default else '')


def _target(value):
    if not isinstance(value, str) or len(value) > 8192 or any(ord(char) < 32 for char in value):
        raise ValueError('Invalid request URL')
    parsed = urlsplit(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username is not None or parsed.port == 0:
        raise ValueError('Invalid request URL')
    return parsed


def _proxy_address(scheme, host, port, username='', password=''):
    if not host or not isinstance(port, int) or not 0 < port <= 65535:
        raise ValueError('Invalid system proxy address')
    host = f'[{host}]' if ':' in host and not host.startswith('[') else host
    url = _endpoint(f'{scheme}://{host}:{port}', _PROXY_SCHEMES)
    return _add_credentials(url, username, password)


def _add_credentials(url, username, password):
    if not username:
        return url
    scheme, address = url.split('://', 1)
    return f'{scheme}://{quote(username, safe="")}:{quote(password, safe="")}@{address}'


def system_web_proxy(url):
    target = _target(url)
    env = getproxies_environment()
    if proxy_bypass_environment(target.netloc, env) or proxy_bypass_environment(target.hostname, env):
        return ''
    address = env.get(target.scheme) or env.get('all')
    if address:
        address = address if '://' in address else 'http://' + address
        proxy = urlsplit(address)
        if proxy.scheme not in _PROXY_SCHEMES or not proxy.hostname or proxy.path not in ('', '/') or proxy.query or proxy.fragment:
            raise ValueError('Unsupported proxy environment setting')
        return address
    if sys.platform == 'darwin':
        from .cowork_macos_proxy import macos_web_proxy
        route = macos_web_proxy(url)
        return _proxy_address(*route) if route else ''
    for proxy in QNetworkProxyFactory.systemProxyForQuery(QNetworkProxyQuery(QUrl(url))):
        kind = proxy.type()
        if kind == QNetworkProxy.NoProxy:
            return ''
        if kind in (QNetworkProxy.HttpProxy, QNetworkProxy.Socks5Proxy):
            return _proxy_address('socks5' if kind == QNetworkProxy.Socks5Proxy else 'http',
                                  proxy.hostName(), proxy.port(), proxy.user(), proxy.password())
    raise ValueError('No supported system proxy route')


class CoworkWeb(QObject):
    changed = Signal()

    def __init__(self, cowork):
        super().__init__(cowork)
        self.b = cowork.b
        # The general Pi gateway token cannot request Cowork proxy credentials.
        self.scope = secrets.token_urlsafe(32)
        self._probe = None
        self._probe_result = {}
        self._saved = self._preferences(self.b.store.data.get('coworkWebNetwork', {}))
        self._secrets = {}
        self.b.jobDone.connect(self._finished)
        self.b.private_server.cowork_web_route = self.route

    @staticmethod
    def _preferences(raw):
        if not isinstance(raw, dict):
            raw = {}
        return {key: raw[key] if isinstance(raw.get(key), str) else default for key, default in _DEFAULTS.items()} | {
            'proxyDns': raw.get('proxyDns') is True,
        }

    @Property('QVariantMap', notify=changed)
    def settings(self):
        return {key: value for key, value in self._saved.items() if key != 'credential'} | {
            'hasPassword': bool(self._saved['credential']),
        }

    @Property(bool, notify=changed)
    def testing(self):
        return self._probe is not None

    @Property('QVariantMap', notify=changed)
    def result(self):
        return self._probe_result

    def _draft(self, raw):
        value = json.loads(raw)
        mode = value.get('mode', 'system')
        if mode not in ('system', 'custom', 'direct'):
            raise ValueError('请选择代理模式 / Select a proxy mode')
        proxy = _endpoint(value.get('proxy', '').strip(), _PROXY_SCHEMES) if mode == 'custom' else ''
        username, password = value.get('username', '').strip(), value.get('password', '')
        if not isinstance(password, str) or len(username) > 255 or len(password) > 1024:
            raise ValueError('代理凭据无效 / Invalid proxy credentials')
        if mode != 'custom':
            username = password = ''
        if not username and password:
            raise ValueError('请填写代理用户名 / Enter the proxy username')
        ca_file = validate_ca_file(value.get('caFile', ''))
        keep = (proxy and username and proxy == self._saved['proxy'] and username == self._saved['username']
                and value.get('clearPassword') is not True)
        return {'mode': mode, 'proxy': proxy, 'caFile': ca_file, 'username': username,
                'credential': self._saved['credential'] if keep else '',
                'proxyDns': value.get('proxyDns') is True}, password

    @Slot(str, result=bool)
    def save(self, raw):
        try:
            value, password = self._draft(raw)
            if password:
                credential = self.b.store._protect_secret('cowork-web-proxy', password)
                self._secrets = {credential: password}
                value['credential'] = credential
            old = self.b.store.data.get('coworkWebNetwork')
            self.b.store.data['coworkWebNetwork'] = value
            try:
                self.b.store.save()
            except (OSError, RuntimeError):
                if old is None:
                    self.b.store.data.pop('coworkWebNetwork', None)
                else:
                    self.b.store.data['coworkWebNetwork'] = old
                raise
        except (ValueError, TypeError, AttributeError, OSError, RuntimeError) as error:
            self._probe_result = {'ok': False, 'stage': 'settings', 'message': str(error)[:250]}
            self.changed.emit()
            return False
        self._saved = value
        self._probe_result = {}
        self.changed.emit()
        return True

    def route(self, body):
        if not isinstance(body, dict) or not isinstance(body.get('scope'), str):
            return {'ok': False, 'code': 'ROUTE_SCOPE', 'message': 'Invalid Cowork network scope'}
        token = body['scope']
        probe = self._probe
        if probe and token == probe[0]:
            value, password = probe[1:3]
        elif token == self.scope and self.b.store.data['desktop'].get('coworkEnabled'):
            value, password = self._saved, ''
        else:
            return {'ok': False, 'code': 'ROUTE_SCOPE', 'message': 'Cowork network scope is unavailable'}
        try:
            url = body.get('url')
            _target(url)
            mode = value['mode']
            route = ''
            if mode == 'system':
                route = system_web_proxy(url)
            elif mode == 'custom':
                credential = value['credential']
                if credential and not password:
                    if credential not in self._secrets:
                        self._secrets = {credential: protect(credential, True)}
                    password = self._secrets[credential]
                route = _add_credentials(value['proxy'], value['username'], password)
            return {'ok': True, 'proxy': route, 'caFile': value['caFile'], 'mode': mode,
                    'proxyDns': mode != 'direct' and value['proxyDns']}
        except (ValueError, OSError, RuntimeError):
            # Proxy URLs and credentials may be embedded in native errors.
            return {'ok': False, 'code': 'PROXY_CONFIG', 'message': 'Unable to resolve the configured proxy. Check the system proxy, PAC and credentials.'}

    @Slot(str, str)
    def test(self, raw, url):
        if self._probe:
            return
        try:
            _target(url)
            value, password = self._draft(raw) if raw else (self._saved, '')
        except (TypeError, ValueError, OSError, AttributeError) as error:
            self._probe_result = {'ok': False, 'stage': 'settings', 'message': str(error)[:250]}
            self.changed.emit()
            return
        scope = secrets.token_urlsafe(32)
        self._probe = (scope, value, password)
        self._probe_result = {}
        self.changed.emit()
        executable = self.b._release / 'bridge.mjs'
        address = f'http://127.0.0.1:{self.b.private_server.port}/'
        token = self.b.private_token

        def work():
            from .windows_job import run_managed
            result = run_managed([node_executable(), str(executable), '--cowork-web-test'],
                input=json.dumps(dict(url=url, gateway=address, token=token, scope=scope)),
                capture_output=True, text=True, encoding='utf-8', env=node_environment(),
                timeout=20, creationflags=CREATE_NO_WINDOW)
            try:
                response = json.loads(result.stdout)
                return response
            except ValueError:
                raise RuntimeError('连接测试未能运行 / Could not run the connection test') from None

        self.b._job('cowork-web:' + scope, work)

    def _finished(self, name, result):
        if not self._probe or name != 'cowork-web:' + self._probe[0]:
            return
        self._probe = None
        self._probe_result = result['value'] if result['ok'] else {
            'ok': False, 'stage': 'settings', 'message': '连接测试未能运行 / Could not run the connection test',
        }
        self.changed.emit()
