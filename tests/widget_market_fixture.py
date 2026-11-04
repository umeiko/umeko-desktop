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


# Public examples for the real application captures. Billion Context's Chinese
# metadata matches its published 1.0.0 manifest. All fixture workers are inert.
PUBLIC_WIDGETS = {
    'billion-context': {
        'version': '1.0.0', 'name': 'Billion Context', 'icon': 'layers',
        'lifecycle': 'application', 'permissions': ['process.execute'],
        'summary': '长上下文安装检查与状态',
        'description': '默认关闭。检查全局 billion-context 安装和本地代理状态，提供安装引导与管理入口，不包含压缩包本身。',
        'en': {'name': 'Billion Context', 'summary': 'Long-context installation checks and status',
            'description': 'Disabled by default. Checks the global billion-context installation and local proxy status, and provides installation guidance and management entry points. Does not include the archive itself.'}},
    'focus-timer': {
        'version': '1.0.0', 'name': '专注计时', 'icon': 'layers',
        'lifecycle': 'session', 'permissions': [], 'summary': '专注与休息计时',
        'description': '设置专注与休息时长，查看当前计时状态。',
        'en': {'name': 'Focus Timer', 'summary': 'Focus and break timer',
            'description': 'Set focus and break durations and view the current timer status.'}},
    'clipboard-notes': {
        'version': '1.1.0', 'name': '剪贴板便笺', 'icon': 'layers',
        'lifecycle': 'session', 'permissions': ['workspace.read'], 'summary': '随手保存常用片段',
        'description': '保存常用片段，并在当前聊天中查看和复制。',
        'en': {'name': 'Clipboard Notes', 'summary': 'Keep frequently used snippets',
            'description': 'Save frequently used snippets to view and copy in the current chat.'}},
}


def public_manifest(identifier, language='zh', version=None):
    source = dict(PUBLIC_WIDGETS[identifier]); translated = source.pop('en')
    if language == 'en': source.update(translated)
    return {'kind': 'umeko-plugin', 'apiVersion': 1, 'id': identifier,
        **source, 'version': version or source['version'], 'author': 'Umeko',
        'entrypoint': 'main.py:create_plugin', 'page': 'qml/Main.qml',
        'config': 'config.json', 'configSchema': 'config.schema.json',
        'readme': 'README.md', 'agent': {'document': 'AGENT.md', 'methods': {}}}


def public_files(identifier, version=None):
    return {'manifest.json': json.dumps(public_manifest(identifier, version=version), ensure_ascii=False),
        'main.py': 'from umeko_plugin_sdk import Plugin\ndef create_plugin(context): return Plugin(context)\n',
        'qml/Main.qml': 'import QtQuick\nRectangle { required property var sdk; objectName: "focusTimerPage"; color: sdk.colors.surface; Text { anchors.centerIn: parent; text: sdk.language === "en" ? "Ready to focus" : "准备专注"; color: sdk.colors.ink } }',
        'README.md': '# ' + PUBLIC_WIDGETS[identifier]['name'], 'AGENT.md': 'Use this Widget only when explicitly enabled.',
        'config.json': '{}', 'config.schema.json': '{"type":"object"}'}


class PublicGitHub(LocalGitHub):
    def __init__(self):
        self.routes, self.calls = {}, []; releases = []
        for identifier, source in PUBLIC_WIDGETS.items():
            version = source['version']; tag = identifier + '-v' + version
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w') as archive:
                for name, body in public_files(identifier).items(): archive.writestr(name, body)
            url = 'https://github.com/umeiko/umeko-desktop-widgets/releases/download/' + tag + '/' + identifier + '-' + version + '.zip'
            raw = 'https://raw.githubusercontent.com/umeiko/umeko-desktop-widgets/' + tag + '/widgets/' + identifier + '/manifest.json'
            self.routes[url] = {'status': 200, 'body': buffer.getvalue(), 'headers': {}}
            self.routes[raw] = {'status': 200, 'body': json.dumps(public_manifest(identifier)), 'headers': {}}
            releases.append({'tag_name': tag, 'published_at': '2026-11-02T08:30:00Z',
                'assets': [{'name': identifier + '-' + version + '.zip', 'size': len(buffer.getvalue()), 'browser_download_url': url}]})
        self.routes[RELEASES] = {'status': 200, 'headers': {'etag': '"public-widgets"'}, 'body': json.dumps(releases)}


class PublicCatalog(MarketCatalog):
    """Actual local catalog/cache behavior, with fixture-only language variants."""
    def __init__(self, backend):
        self.backend = backend; self.fixture = PublicGitHub()
        super().__init__(backend.store.directory, root=ROOT, fetcher=self.fixture)

    def localized(self, row):
        return {**row, **PUBLIC_WIDGETS[row['id']]['en']} if self.backend.language == 'en' else row

    def refresh(self, force=False):
        value = super().refresh(force)
        return {**value, 'rows': [self.localized(row) for row in value['rows']]}

    def prepare(self, identifier):
        value = super().prepare(identifier)
        return {**value, 'manifest': self.localized(value['manifest'])}
