"""Resolve macOS system and PAC proxy settings on the network worker."""
from ctypes import CDLL, CFUNCTYPE, Structure, byref, c_bool, c_char_p, c_double, c_int, c_long, c_void_p, create_string_buffer
from functools import lru_cache


class _StreamContext(Structure):
    _fields_ = [('version', c_long), ('info', c_void_p), ('retain', c_void_p),
                ('release', c_void_p), ('copy_description', c_void_p)]


@lru_cache(maxsize=1)
def _frameworks():
    core = CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    network = CDLL('/System/Library/Frameworks/CFNetwork.framework/CFNetwork')
    callback = CFUNCTYPE(None, c_void_p, c_void_p, c_void_p)
    for library, name, result, arguments in (
        (core, 'CFURLCreateWithBytes', c_void_p, [c_void_p, c_char_p, c_long, c_int, c_void_p]),
        (core, 'CFRelease', None, [c_void_p]),
        (core, 'CFArrayGetCount', c_long, [c_void_p]),
        (core, 'CFArrayGetValueAtIndex', c_void_p, [c_void_p, c_long]),
        (core, 'CFDictionaryGetValue', c_void_p, [c_void_p, c_void_p]),
        (core, 'CFStringGetCString', c_bool, [c_void_p, c_char_p, c_long, c_int]),
        (core, 'CFNumberGetValue', c_bool, [c_void_p, c_int, c_void_p]),
        (core, 'CFRunLoopGetCurrent', c_void_p, []),
        (core, 'CFRunLoopAddSource', None, [c_void_p, c_void_p, c_void_p]),
        (core, 'CFRunLoopSourceInvalidate', None, [c_void_p]),
        (core, 'CFRunLoopRunInMode', c_int, [c_void_p, c_double, c_bool]),
        (network, 'CFNetworkCopySystemProxySettings', c_void_p, []),
        (network, 'CFNetworkCopyProxiesForURL', c_void_p, [c_void_p, c_void_p]),
        (network, 'CFNetworkExecuteProxyAutoConfigurationURL', c_void_p, [c_void_p, c_void_p, callback, c_void_p]),
        (network, 'CFNetworkExecuteProxyAutoConfigurationScript', c_void_p, [c_void_p, c_void_p, callback, c_void_p]),
    ):
        function = getattr(library, name)
        function.restype = result
        function.argtypes = arguments
    return core, network, callback


def macos_web_proxy(url):
    core, network, callback = _frameworks()
    utf8 = 0x08000100

    def symbol(name):
        return c_void_p.in_dll(network, name)

    def field(entry, name):
        return core.CFDictionaryGetValue(entry, symbol(name))

    def string(value):
        if not value:
            return ''
        buffer = create_string_buffer(4096)
        if not core.CFStringGetCString(value, buffer, len(buffer), utf8):
            raise ValueError('Invalid system proxy setting')
        return buffer.value.decode()

    types = {string(symbol('kCFProxyType' + name)): name for name in
             ('None', 'HTTP', 'HTTPS', 'SOCKS', 'AutoConfigurationURL', 'AutoConfigurationJavaScript')}

    def first_route(rows, evaluate_pac=False):
        if not rows or core.CFArrayGetCount(rows) == 0:
            raise ValueError('System proxy returned no route')
        for index in range(core.CFArrayGetCount(rows)):
            row = core.CFArrayGetValueAtIndex(rows, index)
            kind = types.get(string(field(row, 'kCFProxyTypeKey')))
            if kind == 'None':
                return ()
            if kind in ('HTTP', 'HTTPS', 'SOCKS'):
                port = c_int()
                value = field(row, 'kCFProxyPortNumberKey')
                if not value or not core.CFNumberGetValue(value, 9, byref(port)):
                    raise ValueError('Invalid system proxy port')
                return ('socks5' if kind == 'SOCKS' else 'http', string(field(row, 'kCFProxyHostNameKey')),
                        port.value, string(field(row, 'kCFProxyUsernameKey')), string(field(row, 'kCFProxyPasswordKey')))
            if evaluate_pac and kind in ('AutoConfigurationURL', 'AutoConfigurationJavaScript'):
                return pac(row, kind)
        raise ValueError('System proxy returned an unsupported route')

    def pac(entry, kind):
        result = []
        @callback
        def complete(_context, rows, error):
            try:
                if error:
                    raise ValueError('System PAC could not resolve the target')
                result.append(first_route(rows))
            except ValueError as cause:
                result.append(cause)

        argument = field(entry, 'kCFProxy' + kind + 'Key')
        execute = (network.CFNetworkExecuteProxyAutoConfigurationURL if kind == 'AutoConfigurationURL'
                   else network.CFNetworkExecuteProxyAutoConfigurationScript)
        context = _StreamContext()
        source = execute(argument, target, complete, byref(context)) if argument else None
        if not source:
            raise ValueError('System PAC is unavailable')
        try:
            mode = c_void_p.in_dll(core, 'kCFRunLoopDefaultMode')
            core.CFRunLoopAddSource(core.CFRunLoopGetCurrent(), source, mode)
            core.CFRunLoopRunInMode(mode, 4, True)
        finally:
            core.CFRunLoopSourceInvalidate(source)
            core.CFRelease(source)
        if not result:
            raise ValueError('System PAC timed out')
        if isinstance(result[0], ValueError):
            raise result[0]
        return result[0]

    raw = url.encode()
    target = core.CFURLCreateWithBytes(None, raw, len(raw), utf8, None)
    settings = network.CFNetworkCopySystemProxySettings()
    routes = None
    try:
        if not target or not settings:
            raise ValueError('System proxy settings are unavailable')
        routes = network.CFNetworkCopyProxiesForURL(target, settings)
        return first_route(routes, evaluate_pac=True)
    finally:
        for item in (routes, settings, target):
            if item:
                core.CFRelease(item)
