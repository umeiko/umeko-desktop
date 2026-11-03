"""Disposable, windowless market host and local public-release fixtures."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TEMP_ROOT = ROOT.parent / 'outputs/p491-temp'
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
os.environ.setdefault('QT_QUICK_CONTROLS_STYLE', 'Basic')
from PySide6.QtCore import QObject, Property, Signal
from app.desktop_plugins import DesktopPlugins
from app.widget_market import MarketCatalog, RELEASES


def temporary_directory(prefix):
    import tempfile
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix=prefix, dir=TEMP_ROOT)


def wait_for(predicate, app, message, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(.005)
    raise AssertionError(message() if callable(message) else message)


def variant(value):
    return value.toVariant() if hasattr(value, 'toVariant') else value


def package(identifier='sample-widget', version='1.0.0', name='Sample Widget'):
    manifest = {'kind': 'umeko-plugin', 'apiVersion': 1, 'id': identifier,
        'version': version, 'name': name, 'summary': 'Local SDK fixture',
        'description': 'A local Widget package used for integration tests.',
        'entrypoint': 'main.py:create_plugin', 'permissions': ['workspace.read'],
        'config': 'config.json', 'configSchema': 'config.schema.json',
        'agent': {'document': 'AGENT.md', 'methods': {}}}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for path, body in {'manifest.json': json.dumps(manifest),
            'main.py': 'raise RuntimeError("A newly imported Widget must remain disabled")',
            'README.md': 'Local integration fixture.', 'AGENT.md': 'Local fixture.',
            'config.json': '{"choice":"default"}',
            'config.schema.json': '{"type":"object","properties":{"choice":{"type":"string"}},"additionalProperties":false}'}.items():
            archive.writestr(path, body)
    return manifest, buffer.getvalue()


class LocalGitHub:
    """URL-shaped fixture routing only; this class never opens a socket."""
    def __init__(self, specs=None):
        self.routes, self.calls = {}, []
        releases = []
        for identifier, version, name in specs or [('sample-widget', '1.0.0', 'Sample Widget')]:
            manifest, body = package(identifier, version, name)
            tag = identifier + '-v' + version
            url = 'https://github.com/umeiko/umeko-desktop-widgets/releases/download/' + tag + '/' + identifier + '-' + version + '.zip'
            raw = 'https://raw.githubusercontent.com/umeiko/umeko-desktop-widgets/' + tag + '/widgets/' + identifier + '/manifest.json'
            self.routes[url] = {'status': 200, 'body': body, 'headers': {}}
            self.routes[raw] = {'status': 200, 'body': json.dumps(manifest), 'headers': {}}
            releases.append({'tag_name': tag, 'published_at': '2026-11-01T12:00:00Z',
                'assets': [{'name': identifier + '-' + version + '.zip', 'size': len(body), 'browser_download_url': url}]})
        self.routes[RELEASES] = {'status': 200, 'headers': {'etag': '"local-market"'}, 'body': json.dumps(releases)}

    def __call__(self, url, headers=None, destination=None):
        self.calls.append((url, destination))
        value = self.routes[url]
        if isinstance(value, Exception):
            raise value
        return dict(value)


class Pool(QObject):
    event = Signal(object, object)
    def __init__(self, view):
        super().__init__()
        self.records = {view.key: view}


class Backend(QObject):
    changed = Signal()
    viewChanged = Signal()
    chatChanged = Signal()
    toast = Signal(str)
    jobDone = Signal(str, object)
    documentRequested = Signal(str, str, str)
    widgetDocumentRequested = Signal(str, str, str, str)
    editorText = Signal(str)

    def __init__(self, directory, language='en'):
        super().__init__()
        self.root = ROOT
        self.store = SimpleNamespace(directory=Path(directory) / 'profile')
        self.store.directory.mkdir(parents=True)
        self._language = language
        self._view = SimpleNamespace(key='market-session', id='market-session',
            workspace=str(Path(directory) / 'workspace'), title='Test session',
            busy=False, global_agent='', messages=[], subagents_active=False)
        Path(self._view.workspace).mkdir()
        self._pool = Pool(self._view)
        self.piManagement = SimpleNamespace(busy=False)
        self.busy = self.kernelBusy = False
        self.pendingApproval = {}
        self.executor = ThreadPoolExecutor(max_workers=1)
        settings = self.store.directory / 'desktop-plugins/settings.json'
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({'enabled': {'desktop-pet': False, 'global-agents': False}}), encoding='utf-8')
        self._manager = DesktopPlugins(self)
        self.replies = {}
        self._manager.hostResponse.connect(lambda widget, key, value: self.replies.__setitem__(key, value))

    @Property(QObject, constant=True)
    def desktopPlugins(self): return self._manager
    @Property(str, notify=changed)
    def language(self): return self._language
    @Property(float, constant=True)
    def fontScale(self): return 1.0
    @Property(str, constant=True)
    def lineSpacing(self): return 'standard'
    @Property('QVariantMap', constant=True)
    def config(self):
        from PySide6.QtGui import QGuiApplication
        app = QGuiApplication.instance()
        return {'fontFamily': app.font().family() if isinstance(app, QGuiApplication) else 'sans-serif', 'theme': 'light'}
    @Property('QVariantMap', constant=True)
    def themeStyle(self): return {'base': 'light', 'colors': {}}

    def _job(self, name, operation):
        def execute():
            try: result = {'ok': True, 'value': operation()}
            except Exception as error: result = {'ok': False, 'value': str(error)}
            self.jobDone.emit(name, result)
        self.executor.submit(execute)

    def _skills_widget_changed(self, *_): pass

    def close(self):
        self.executor.shutdown(wait=True)
        self._manager.close()


def local_catalog(backend, specs=None):
    fake = LocalGitHub(specs)
    jobs = backend.desktopPlugins.hostServices._market_service()
    jobs.catalog = MarketCatalog(backend.store.directory, root=ROOT, fetcher=fake)
    return fake


def request(backend, app, operation, args=None, confirm=None):
    manager = backend.desktopPlugins
    key = manager.requestHost(operation, json.dumps(args or {}))
    if not key:
        raise AssertionError('Host request rejected before dispatch: ' + operation)
    host = manager.hostServices
    wait_for(lambda: key in backend.replies or host.pendingApproval.get('id') == key,
        app, 'Host request did not settle: ' + operation)
    if host.pendingApproval.get('id') == key and confirm is not None:
        host.respondApproval(confirm)
        wait_for(lambda: key in backend.replies, app, 'Confirmed operation did not settle: ' + operation)
    return key
