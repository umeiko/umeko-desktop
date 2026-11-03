"""Real application/WebPane market tests and captures, fully offscreen.

Discovery starts one hidden child process. Catalog responses and ZIPs are local;
provider execution, browser navigation, native dialogs and notifications are
stubbed. No mouse, keyboard or other native input is injected.
"""
from __future__ import annotations
from contextlib import ExitStack
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software', QT_QUICK_CONTROLS_STYLE='Basic')
from PySide6.QtCore import QObject, QEventLoop, QTimer, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtQuick import QQuickWindow, QQuickItem
from PySide6.QtQml import QQmlExpression, qmlContext
from PySide6.QtTest import QTest
import shiboken6
from widget_market_fixture import (PublicCatalog, PUBLIC_WIDGETS, public_files,
    public_manifest, temporary_directory, variant, RELEASES, TEMP_ROOT)


def wait_for(predicate, app, message, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        # A real event loop also delivers DeferredDelete; processEvents alone
        # leaves removed asynchronous Loader items discoverable after closing.
        QTest.qWait(10)
        if predicate(): return
    raise AssertionError(message() if callable(message) else message)


class QuietTray(QObject):
    quitRequested = Signal()
    notificationRequested = Signal(str)
    def __init__(self, window, icon, parent):
        super().__init__(parent); self.tray = None
    def set_language(self, language): pass
    def restore(self): pass


class QuietNotifications(QObject):
    activated = Signal(str)
    def __init__(self, window, tray, root, parent): super().__init__(parent)
    @Slot(str, str, bool, bool)
    def task_finished(self, *args): pass


def no_model_execution(*args, **kwargs):
    raise AssertionError('No model execution is permitted')


class MarketUi:
    """The actual app window, native WebPane and DesktopPlugins host."""
    def __init__(self):
        from app.storage import Store
        self.temporary = temporary_directory('widget-market-app-')
        self.base = Path(self.temporary.name).resolve()
        self.patches = ExitStack()
        for name in ('profile', 'agent', 'workspace', 'home'):
            (self.base / name).mkdir()
        self.patches.enter_context(patch.dict(os.environ, {
            'UMEKO_DATA_DIR': str(self.base / 'profile'),
            'PI_CODING_AGENT_DIR': str(self.base / 'agent'),
            'HOME': str(self.base / 'home'), 'USERPROFILE': str(self.base / 'home'),
            'UMEKO_LANGUAGE': 'zh'}))
        seed = Store(self.base / 'profile')
        seed.data.update(workspace=str(self.base / 'workspace'), character='komari')
        seed.data['agent'].update(agentDir=str(self.base / 'agent'), safeMode=True)
        seed.data['desktop']['webDisplay'] = 'external'
        seed.data['providers'] = [{'id': 'test-provider', 'name': 'Test provider', 'api': 'openai',
            'baseUrl': 'https://example.invalid/v1', 'key': '', 'proxy': {'mode': 'direct'},
            'models': [{'alias': 'test-model', 'upstream': 'test-model'}]}]
        seed.data.update(selectedProvider='test-provider', selectedModel='test-model')
        seed.save()
        registry = self.base / 'profile/desktop-plugins/settings.json'
        registry.parent.mkdir(parents=True)
        registry.write_text(json.dumps({'enabled': {'desktop-pet': False, 'global-agents': False}}))
        self.patches.enter_context(patch('app.tray.TrayController', QuietTray))
        self.patches.enter_context(patch('app.notifications.TaskNotifications', QuietNotifications))
        self.patches.enter_context(patch('app.controller.Controller.loadNativeIndex', lambda self: None))
        self.owned_subprocesses = []
        original_popen = subprocess.Popen
        def owned_popen(*args, **kwargs):
            if os.name == 'nt': kwargs['creationflags'] = kwargs.get('creationflags', 0) | subprocess.CREATE_NO_WINDOW
            process = original_popen(*args, **kwargs)
            self.owned_subprocesses.append(process)
            return process
        self.patches.enter_context(patch.object(subprocess, 'Popen', owned_popen))
        self.patches.enter_context(patch('app.controller.Controller.send', no_model_execution))
        self.no_network = self.patches.enter_context(patch.object(socket.socket, 'connect', side_effect=AssertionError('No outgoing network is permitted')))
        self.browser = self.patches.enter_context(patch.object(QDesktopServices, 'openUrl', return_value=True))
        self.patches.enter_context(patch('PySide6.QtWidgets.QFileDialog.getOpenFileName', return_value=('', '')))
        from main import create_application
        self.app, self.engine, self.backend = create_application()
        self.app.setQuitOnLastWindowClosed(False)
        self.window = self.engine.rootObjects()[0]; self.window.resize(1320, 860)
        self.warnings = []
        self.engine.warnings.connect(lambda errors: self.warnings.extend(error.toString() for error in errors))
        self.manager = self.backend.desktopPlugins; self.host = self.manager.hostServices
        self.catalog = PublicCatalog(self.backend)
        self.host._market_service().catalog = self.catalog
        self.replies = {}
        self.manager.hostResponse.connect(lambda widget, key, value: self.replies.__setitem__(key, value))
        self.backend._view.id = 'widget-guide'; self.backend._view.title = 'Widget workspace'
        self.backend._ensure_project(str(self.base / 'workspace'))
        self.backend._sessions = [{'id': 'widget-guide', 'title': 'Widget workspace', 'workspace': str(self.base / 'workspace')}]
        self.reset()

    def find(self, name, required=True):
        stack = [self.window.contentItem()]
        while stack:
            item = stack.pop()
            if item.objectName() == name: return item
            if item.objectName() in ('webSurfaceLoader', 'htmlPreviewBrowser'): continue
            stack.extend(item.childItems())
        value = self.window.findChild(QObject, name)
        if value is None and required:
            raise AssertionError('QML object missing: ' + name + '\n' + '\n'.join(self.warnings))
        return value

    @property
    def widget(self): return self.find('widgetMarket')

    def js(self, source, target=None):
        target = target or self.widget
        expression = QQmlExpression(qmlContext(target), target, source)
        value = expression.evaluate()
        if expression.hasError(): raise AssertionError(expression.error().toString())
        return value[0] if isinstance(value, tuple) else value

    def idle(self):
        wait_for(lambda: self.find('widgetMarket', False) is not None and self.widget.property('initialized')
            and isinstance(variant(self.widget.property('rows')), list)
            and not variant(self.widget.property('pending')), self.app,
            lambda: 'Market did not settle: ' + repr(self.manager.page) + ' pending=' + repr(variant(self.widget.property('pending'))) + ' requests=' + repr([(value['operation'], value['arguments']) for value in self.host.requests.values()]) + '\n' + '\n'.join(self.warnings))

    def click(self, name):
        button = self.find(name)
        if not button.property('visible') or not button.property('enabled'):
            raise AssertionError('Action unavailable: ' + name)
        button.clicked.emit(); self.app.processEvents()

    def rows(self): return variant(self.widget.property('rows'))
    def row(self, identifier): return next(row for row in self.rows() if row['id'] == identifier)

    def language(self, language):
        self.backend.setLanguage(language)
        user = '帮我选择并管理这个工作区的 Widgets。' if language == 'zh' else 'Help me choose and manage Widgets for this workspace.'
        assistant = '可以在右侧查看发布信息、权限和安装状态。新安装的 Widget 需要你明确启用。' if language == 'zh' else 'Use the panel to review releases, permissions and installation status. Newly installed Widgets need your explicit enable action.'
        self.backend._view.messages = [{'role': 'user', 'text': user}, {'role': 'assistant', 'text': assistant}]
        self.backend.chatChanged.emit(); self.backend.changed.emit()
        if self.manager.page.get('id') == 'widget-market':
            self.js('load(false)'); self.idle()

    def reset(self, language='zh'):
        self.manager.closePage()
        wait_for(lambda: self.find('widgetMarket', False) is None, self.app, 'Prior Widget page did not unload')
        for identifier in list(PUBLIC_WIDGETS):
            self.manager.stop(identifier); self.manager.entries.pop(identifier, None)
        for identifier, installed in [('focus-timer', '1.0.0'), ('clipboard-notes', '1.0.0')]:
            folder = self.manager.root / 'packages' / identifier / installed
            for name, body in public_files(identifier, installed).items():
                target = folder / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(body, encoding='utf-8')
            self.manager.entries[identifier] = {**public_manifest(identifier, version=installed), 'builtin': False}
        self.catalog.fixture = self.catalog.fixture.__class__()
        self.catalog.fetcher = self.catalog.fixture
        self.manager.settings['enabled'].update({'focus-timer': True, 'clipboard-notes': False, 'billion-context': False})
        self.manager.settings.setdefault('sessions', {})[self.manager.storage_key] = ['widget-market', 'focus-timer']
        self.manager.save(); self.manager.changed.emit(); self.backend.setTheme('light')
        self.window.setProperty('page', 'chat'); self.language(language)
        if not self.manager.openPage('widget-market'): raise AssertionError('Menu openPage rejected Widget Market')
        pane = self.find('webPane'); pane.setProperty('preferredWidth', 500); self.js('snapWidth()', pane)
        self.idle(); self.find('widgetMarketSearch').setProperty('text', '')
        self.select('')
        self.browser.reset_mock(); self.warnings.clear()

    def select(self, identifier): self.js('selectedId=' + json.dumps(identifier))

    def start_install(self, identifier='billion-context'):
        self.js('install(' + json.dumps(self.row(identifier)) + ')')
        wait_for(lambda: bool(self.host.pendingApproval), self.app, 'Native import confirmation missing')

    def capture(self, name):
        loop = QEventLoop(); guard = QTimer(); guard.setSingleShot(True)
        guard.timeout.connect(loop.quit); self.window.afterAnimating.connect(loop.quit)
        self.window.requestUpdate(); guard.start(5000); loop.exec()
        self.window.afterAnimating.disconnect(loop.quit); guard.stop(); self.app.processEvents()
        path = Path(name) if Path(name).is_absolute() else ROOT / 'docs/images' / name
        image = self.window.grabWindow()
        if image.isNull() or not image.save(str(path)): raise AssertionError('Cannot capture ' + str(path))

    def close(self):
        self.backend.close(); self.window.hide(); shiboken6.delete(self.engine)
        self.app.processEvents()
        for process in self.owned_subprocesses:
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate(); process.wait(timeout=5)
        self.patches.close(); self.temporary.cleanup()


class WidgetMarketUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.ui = MarketUi()
    @classmethod
    def tearDownClass(cls): cls.ui.close()
    def setUp(self): self.ui.reset('en')

    def test_full_application_native_pane_search_details_and_localized_state(self):
        ui = self.ui
        self.assertEqual((ui.window.width(), ui.window.height()), (1320, 860))
        self.assertEqual(ui.find('webPane').property('preferredWidth'), 500)
        self.assertEqual(ui.find('webPane').property('mode'), 'plugin')
        self.assertTrue(ui.find('closeWebPaneButton').isVisible())
        self.assertEqual(ui.widget.width(), 499)
        self.assertEqual({row['state'] for row in ui.rows()}, {'installed', 'update-available', 'not-installed'})
        for identifier, action in [('billion-context', 'Install'), ('focus-timer', 'Open'), ('clipboard-notes', 'Update')]:
            button = ui.find('widgetMarketAction_' + identifier)
            self.assertEqual(button.property('text'), action)
            self.assertLessEqual(button.mapToItem(ui.widget, button.boundingRect().bottomRight()).x(), ui.widget.width())
        ui.find('widgetMarketSearch').setProperty('text', 'Billion')
        self.assertEqual(ui.find('widgetMarketList').property('count'), 1)
        ui.select('billion-context')
        self.assertTrue(ui.find('widgetMarketDetails').isVisible())
        self.assertIn('process.execute', ui.js('JSON.stringify(selected)'))
        self.assertNotIn('2026-11-02T', ui.js('localDate("2026-11-02T08:30:00Z")'))
        ui.language('zh'); self.assertEqual(ui.find('widgetMarketAction_billion-context').property('text'), '安装')
        self.assertEqual(ui.warnings, [])

    def test_install_digest_confirmation_explicit_enable_and_existing_open_flow(self):
        ui = self.ui
        enabled = []; started = []; opened = []
        original_enable = ui.manager.setSessionEnabled
        def enable(identifier, value):
            enabled.append((identifier, value)); return original_enable(identifier, value)
        with patch.object(ui.manager, 'setSessionEnabled', enable):
            ui.start_install()
            self.assertIn('Permissions: process.execute', ui.host.pendingApproval['detail'])
            self.assertIn('checksum', ui.host.pendingApproval['detail'].lower())
            self.assertEqual(ui.js('localDigests["billion-context"]'), False)
            ui.click('widgetHost_allowToolButton'); ui.idle(); self.assertEqual(enabled, [])
            self.assertTrue('billion-context' in ui.manager.entries,
                repr(variant(ui.widget.property('localStates'))) + ' ' + ui.manager.status)
            wait_for(lambda: ui.row('billion-context')['state'] == 'installed'
                and not variant(ui.widget.property('pending')), ui.app, 'Installed state did not refresh after native import')
            self.assertFalse(ui.manager.enabled('billion-context'))
            self.assertFalse(ui.manager.session_enabled('billion-context'))
            self.assertFalse(ui.manager.workers.get('billion-context'))
            with patch.object(ui.manager, 'start', lambda identifier: started.append(identifier)):
                ui.js('activate(' + json.dumps(ui.row('billion-context')) + ')'); ui.idle()
                self.assertEqual(enabled, [('billion-context', True)])
                self.assertTrue(ui.manager.enabled('billion-context')); self.assertIn('billion-context', started)
                wait_for(lambda: ui.row('billion-context')['enabled']
                    and not variant(ui.widget.property('pending')), ui.app, 'Explicit Enable state did not refresh')
        original_open = ui.manager.openPage
        def opener(identifier):
            opened.append(identifier); return original_open(identifier)
        with patch.object(ui.manager, 'openPage', opener):
            ui.js('activate(' + json.dumps(ui.row('focus-timer')) + ')')
            wait_for(lambda: ui.manager.page.get('id') == 'focus-timer', ui.app, 'Enabled Widget did not open')
            self.assertEqual(opened, ['focus-timer'])
        self.assertEqual(ui.warnings, [])

    def test_repository_readme_and_cached_offline_local_import_entry(self):
        ui = self.ui
        ui.click('widgetMarketSource'); ui.idle()
        self.assertIn('github.com/umeiko/umeko-desktop-widgets', ui.browser.call_args.args[0].toString())
        ui.select('billion-context'); ui.click('widgetMarketReadme'); ui.idle()
        self.assertIn('billion-context', ui.browser.call_args.args[0].toString())
        ui.catalog.fixture.routes[RELEASES] = OSError('Offline')
        ui.js('load(true)'); ui.idle()
        self.assertEqual(len(ui.rows()), 3); self.assertTrue(ui.find('widgetMarketNotice').isVisible())
        dialog = ui.find('desktopPluginImportDialog')
        ui.js('options = FileDialog.DontUseNativeDialog', dialog)
        ui.click('widgetMarketImportLocal')
        wait_for(lambda: ui.window.property('page') == 'settings' and ui.find('desktopPluginsPage').isVisible()
            and dialog.property('visible'), ui.app, 'Local import did not open Agent Widgets and its ZIP picker')
        self.assertEqual(ui.window.property('settingsTab'), 3)
        ui.js('close()', dialog)
        self.assertEqual(ui.warnings, [])


def capture_documentation():
    ui = MarketUi()
    try:
        for language in ('zh', 'en'):
            ui.reset(language); ui.capture('widget-market-' + language + '.png')
            ui.select('billion-context'); ui.capture('widget-market-details-' + language + '.png')
            ui.start_install(); ui.capture('widget-market-confirmation-' + language + '.png')
            ui.click('widgetHost_denyToolButton'); ui.idle()
        ui.reset('zh'); ui.catalog.fixture.routes[RELEASES] = OSError('Offline')
        ui.js('load(true)'); ui.idle(); ui.capture('widget-market-offline-zh.png')
        ui.reset('zh'); ui.js('load(true)'); ui.idle()
        ui.backend.setTheme('dark'); ui.select('billion-context')
        ui.capture('widget-market-dark-zh.png')
        if ui.warnings: raise AssertionError('\n'.join(ui.warnings))
    finally: ui.close()
    print('WIDGET_MARKET_FULLAPP_CAPTURES_OK: 8 screenshots')


if __name__ != '__main__':
    class IsolatedWidgetMarketUiTests(unittest.TestCase):
        def test_widget_market_ui_in_windowless_process(self):
            result = subprocess.run([sys.executable, '-X', 'faulthandler', str(Path(__file__).resolve())], cwd=ROOT,
                env=dict(os.environ, PYTHONUTF8='1', QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software'),
                capture_output=True, text=True, encoding='utf-8', timeout=150,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print((result.stdout + result.stderr).strip())


def load_tests(loader, tests, pattern):
    if __name__ == '__main__': return tests
    return unittest.TestSuite([IsolatedWidgetMarketUiTests('test_widget_market_ui_in_windowless_process')])


if __name__ == '__main__':
    if sys.argv[1:] == ['--capture']: capture_documentation()
    elif sys.argv[1:] == ['--preview']:
        ui = MarketUi()
        try: ui.capture(TEMP_ROOT / 'widget-market-fullapp-preview.png')
        finally: ui.close()
    else: unittest.main()
