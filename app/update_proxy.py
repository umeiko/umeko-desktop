"""Resolve the OS proxy off the GUI thread; never persist proxy credentials."""
import subprocess
import sys
import urllib.parse
import urllib.request
from PySide6.QtNetwork import QNetworkProxy, QNetworkProxyFactory, QNetworkProxyQuery
from PySide6.QtCore import QUrl


def system_proxy(url):
    if urllib.request.proxy_bypass(urllib.parse.urlsplit(url).hostname): return ''
    proxies = urllib.request.getproxies()
    for key in ('https', 'all', 'http'):
        if proxies.get(key):
            value = proxies[key]
            return value if '://' in value else 'http://' + value
    for proxy in QNetworkProxyFactory.systemProxyForQuery(QNetworkProxyQuery(QUrl(url))):
        if proxy.type() not in (QNetworkProxy.HttpProxy, QNetworkProxy.Socks5Proxy) or not proxy.hostName(): continue
        address = QUrl(); address.setScheme('socks5' if proxy.type() == QNetworkProxy.Socks5Proxy else 'http')
        address.setHost(proxy.hostName()); address.setPort(proxy.port())
        address.setUserName(proxy.user()); address.setPassword(proxy.password())
        return address.toString(QUrl.FullyEncoded)
    if sys.platform != 'linux': return ''
    def setting(schema, key):
        try:
            value = subprocess.run(['gsettings', 'get', 'org.gnome.system.proxy'+schema, key],
                capture_output=True, text=True, timeout=1.5).stdout.strip()
            return value[1:-1] if value.startswith("'") and value.endswith("'") else value
        except (OSError, subprocess.TimeoutExpired): return ''
    if setting('', 'mode') == 'manual':
        for schema in ('.https', '.http', '.socks'):
            host, port = setting(schema, 'host'), setting(schema, 'port')
            if not host or not port.isdigit() or not 0 < int(port) <= 65535: continue
            address = QUrl(); address.setScheme('socks5' if schema == '.socks' else 'http')
            address.setHost(host); address.setPort(int(port))
            if schema != '.socks' and setting('.http', 'use-authentication') == 'true':
                address.setUserName(setting('.http', 'authentication-user'))
                address.setPassword(setting('.http', 'authentication-password'))
            return address.toString(QUrl.FullyEncoded)
    return ''
