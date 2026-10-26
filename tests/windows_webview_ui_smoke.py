"""Check the real WebView2 child window, not just successful HTTP requests."""
import ctypes
import json
import os
import socket
import sys
import tempfile
import threading
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['QT_QPA_PLATFORM'] = 'windows'
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QMetaObject, QPoint, Qt
from PySide6.QtTest import QTest
from main import create_application


class Handler(BaseHTTPRequestHandler):
    counts = {}
    fail = True

    def do_GET(self):
        self.counts[self.path] = self.counts.get(self.path, 0) + 1
        if self.path == '/fail' and self.fail:
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        name = 'Second' if self.path == '/second' else 'Preview'
        raw = ('<!doctype html><meta charset="utf-8"><title>Loading</title>'
               '<script>document.title=' + json.dumps(name) + '</script>'
               '<body style="background:#fcfcfa;color:#29352f;font:18px sans-serif;padding:35px">'
               '<h1>' + name + '</h1><p>Umeko WebView</p><input placeholder="输入中文测试"></body>').encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html;charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


user32 = ctypes.windll.user32
CALLBACK = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumChildWindows.argtypes = [wintypes.HWND, CALLBACK, wintypes.LPARAM]
user32.IsWindowVisible.argtypes = [wintypes.HWND]


def browser_children(window):
    children = []

    @CALLBACK
    def visit(handle, unused):
        name = ctypes.create_unicode_buffer(200)
        user32.GetClassNameW(handle, name, len(name))
        if name.value == 'Chrome_RenderWidgetHostHWND':
            rect = wintypes.RECT()
            user32.GetWindowRect(handle, ctypes.byref(rect))
            children.append((bool(user32.IsWindowVisible(handle)), rect.right - rect.left, rect.bottom - rect.top))
        return True

    user32.EnumChildWindows(int(window.winId()), visit, 0)
    return children


with tempfile.TemporaryDirectory(prefix='umeko-windows-webview-') as temporary:
    os.environ['UMEKO_DATA_DIR'] = str(Path(temporary) / 'profile')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = 'http://127.0.0.1:' + str(server.server_port)
    app, engine, controller = create_application()
    window = engine.rootObjects()[0]
    window.setPosition(app.primaryScreen().availableGeometry().topLeft() + QPoint(40, 40))
    window.raise_()
    window.requestActivate()
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))

    def find(name):
        pending = [window.contentItem()]
        while pending:
            item = pending.pop()
            if item.objectName() == name:
                return item
            if item.objectName() != 'webSurfaceLoader':
                pending.extend(item.childItems())
        raise AssertionError(name)

    def wait(check):
        for _ in range(600):
            QTest.qWait(25)
            if check():
                return
        raise AssertionError('Timeout: ' + str(warnings))

    def invoke(item, method):
        assert QMetaObject.invokeMethod(item, method, Qt.DirectConnection)

    def rendered():
        children = browser_children(window)
        return len(children) == 1 and children[0][0] and children[0][1] > 100 and children[0][2] > 100

    try:
        assert controller.webviewAvailable
        pane, loader = find('webPane'), find('webSurfaceLoader')
        controller.webRequested.emit(url + '/preview', 'Preview')
        QTest.qWait(50)
        assert pane.property('moving') and loader.property('item') is None
        wait(lambda: loader.property('item') is not None and not pane.property('moving'))
        view = loader.property('item')
        wait(lambda: view.property('title') == 'Preview' and not view.property('loading'))
        wait(rendered)
        output = ROOT / 'artifacts/screenshots'
        output.mkdir(parents=True, exist_ok=True)
        QTest.qWait(250)
        screen = window.screen()
        pixmap = screen.grabWindow(0)
        area = window.geometry().translated(-screen.geometry().topLeft())
        ratio = pixmap.devicePixelRatio()
        pixmap.copy(round(area.x() * ratio), round(area.y() * ratio), round(area.width() * ratio), round(area.height() * ratio)).save(str(output / 'windows-webview-rendered.png'))
        count = Handler.counts['/preview']
        controller.webRequested.emit(url + '/preview', 'Preview')
        wait(lambda: Handler.counts['/preview'] > count and not view.property('loading'))
        assert loader.property('item') is view
        address = find('webAddress')
        address.setProperty('text', url + '/second')
        invoke(address, 'accepted')
        wait(lambda: view.property('title') == 'Second' and not view.property('loading'))
        invoke(find('webBackButton'), 'clicked')
        wait(lambda: view.property('title') == 'Preview' and not view.property('loading'))
        original = pane.width()
        window.setProperty('webPreferredWidth', original + 80)
        invoke(pane, 'snapWidth')
        QTest.qWait(100)
        assert pane.width() > original + 70 and loader.property('item') is view
        pane.setProperty('blocked', True)
        QTest.qWait(150)
        assert not any(child[0] for child in browser_children(window))
        pane.setProperty('blocked', False)
        wait(rendered)
        invoke(find('closeWebPaneButton'), 'clicked')
        wait(lambda: loader.property('item') is None and not pane.property('moving'))
        assert not browser_children(window)
        controller.webRequested.emit(url + '/preview', 'Preview')
        wait(lambda: loader.property('item') is not None and not pane.property('moving'))
        view = loader.property('item')
        wait(lambda: view.property('title') == 'Preview' and not view.property('loading'))
        wait(rendered)
        controller.webRequested.emit(url + '/fail', 'Failure')
        wait(lambda: bool(view.property('errorMessage')) and find('webLoadError').isVisible())
        assert not loader.isVisible()
        Handler.fail = False
        invoke(find('retryWebLoadButton'), 'clicked')
        wait(lambda: not view.property('errorMessage') and not view.property('loading') and view.property('title') == 'Preview')
        wait(rendered)
        assert not find('webLoadError').isVisible()
        assert not warnings, warnings
        print('WINDOWS_WEBVIEW_OK: native rendering, JavaScript, reload, navigation/back, resize, hide/show, close/reopen, failure/retry')
    finally:
        controller.close()
        import shiboken6
        shiboken6.delete(engine)
        server.shutdown()
