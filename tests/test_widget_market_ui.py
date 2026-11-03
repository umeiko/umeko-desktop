"""Actual market Widget, DesktopPlugins host, and native approval, offscreen.

Discovery uses a hidden child process so existing QCoreApplication suites do not
change the GUI application's type. No input injection or real HTTP is used.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software', QT_QUICK_CONTROLS_STYLE='Basic')
from PySide6.QtCore import QObject, QEventLoop, QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtQuick import QQuickWindow, QQuickItem
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlContext
import shiboken6
from widget_market_fixture import Backend, local_catalog, package, variant, wait_for, temporary_directory


def application():
    from app.syntax_highlight import register_text_types
    register_text_types()
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
        # The Windows offscreen plugin may start with no registered fonts.
        # Match the existing preview harness without starting the application.
        if not QFontDatabase.families() and os.name == 'nt':
            for font in ('msyh.ttc', 'segoeui.ttf', 'consola.ttf'):
                QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / font))
        if os.name == 'nt':
            families = QFontDatabase.families()
            family = next((name for name in ('Microsoft YaHei UI', 'Microsoft YaHei', 'Segoe UI') if name in families), None)
            if family:
                app.setFont(QFont(family, 10))
    return app


class MarketUi:
    def __init__(self, directory, language='en', real=False):
        self.app = application()
        self.backend = Backend(directory, language)
        self.manager = self.backend.desktopPlugins
        self.host = self.manager.hostServices
        self.fetch = None if real else local_catalog(self.backend, [
            ('installed-widget', '1.0.0', 'Installed Widget'),
            ('updated-widget', '2.0.0', 'Updated Widget'),
            ('sample-widget', '1.0.0', 'Sample Widget')])
        if not real:
            for identifier, version in [('installed-widget', '1.0.0'), ('updated-widget', '1.0.0')]:
                self.manager.entries[identifier] = {**package(identifier, version)[0], 'builtin': False}
        self.engine = QQmlApplicationEngine()
        self.warnings = []
        self.engine.warnings.connect(lambda errors: self.warnings.extend(error.toString() for error in errors))
        self.engine.rootContext().setContextProperty('backend', self.backend)
        qml = '''
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "%s" as UI
ApplicationWindow {
    width: 940; height: 780; visible: true
    title: "Umeko Widget Market"
    color: UI.Theme.bg
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 24; spacing: 14
        Text { text: "Umeko"; color: UI.Theme.muted; font.family: UI.Theme.fontFamily; font.pixelSize: 13 }
        UI.DesktopPluginSurface { Layout.fillWidth: true; Layout.fillHeight: true }
    }
    UI.ApprovalDialog { approvalBackend: backend.desktopPlugins.hostServices; actionPrefix: "widget" }
}
''' % QUrl.fromLocalFile(str(ROOT / 'app/qml')).toString()
        self.engine.loadData(qml.encode(), QUrl.fromLocalFile(str(ROOT / 'tests/WidgetMarketHarness.qml')))
        if not self.engine.rootObjects():
            raise AssertionError('\n'.join(self.warnings))
        self.window = self.engine.rootObjects()[0]
        self.find('toolApproval').setProperty('enter', None)
        self.find('toolApproval').setProperty('exit', None)
        if not self.manager.openPage('widget-market'):
            raise AssertionError('Menu-style openPage rejected Widget Market')
        try:
            wait_for(lambda: self.maybe('widgetMarket') is not None, self.app,
                lambda: 'Actual market QML did not load: page=' + repr(self.manager.page) + ' loader=' + repr({name: str(self.find('desktopPluginPageLoader').property(name)) for name in ('source', 'width', 'height', 'visible')}) + '\n' + '\n'.join(self.warnings))
            self.widget = self.find('widgetMarket')
            self.idle()
        except BaseException:
            self.close()
            raise

    def maybe(self, name):
        stack = [self.window.contentItem()]
        while stack:
            item = stack.pop()
            if item.objectName() == name:
                return item
            stack.extend(item.childItems())
        return self.window.findChild(QObject, name)

    def find(self, name):
        value = self.maybe(name)
        if value is None:
            raise AssertionError('QML object missing: ' + name + '\n' + '\n'.join(self.warnings))
        return value

    def js(self, source):
        expression = QQmlExpression(qmlContext(self.widget), self.widget, source)
        value = expression.evaluate()
        if expression.hasError():
            raise AssertionError(expression.error().toString())
        return value

    def idle(self):
        wait_for(lambda: self.widget.property('initialized') and not variant(self.widget.property('pending')),
            self.app, lambda: 'Market requests did not settle: ' + repr(variant(self.widget.property('pending'))) + ' page=' + str(self.manager.page) + '\n' + '\n'.join(self.warnings))

    def click(self, name):
        button = self.find(name)
        if not button.property('visible') or not button.property('enabled'):
            raise AssertionError('Action unavailable: ' + name)
        button.clicked.emit()
        self.app.processEvents()

    def rows(self): return variant(self.widget.property('rows'))

    def start_install(self, identifier):
        row = next(row for row in self.rows() if row['id'] == identifier)
        self.js('install(' + json.dumps(row) + ')')
        wait_for(lambda: bool(self.host.pendingApproval), self.app, 'Native import confirmation did not appear')

    def capture(self, path):
        loop = QEventLoop()
        guard = QTimer()
        guard.setSingleShot(True)
        guard.timeout.connect(loop.quit)
        self.window.afterAnimating.connect(loop.quit)
        self.window.requestUpdate()
        guard.start(5000)
        loop.exec()
        self.window.afterAnimating.disconnect(loop.quit)
        guard.stop()
        self.app.processEvents()
        image = self.window.grabWindow()
        path.parent.mkdir(parents=True, exist_ok=True)
        if image.isNull() or not image.save(str(path)):
            raise AssertionError('Offscreen capture failed: ' + str(path))

    def close(self):
        self.backend.close()
        self.window.close()
        shiboken6.delete(self.engine)
        self.app.processEvents()


class WidgetMarketUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = application()

    def setUp(self):
        self.temporary = temporary_directory('umeko-market-ui-')
        self.addCleanup(self.temporary.cleanup)
        self.ui = MarketUi(self.temporary.name)
        self.addCleanup(self.ui.close)

    def test_actual_widget_bilingual_rows_and_refresh_dispatch(self):
        ui = self.ui
        self.assertEqual(ui.manager.page['id'], 'widget-market')
        self.assertEqual({row['state'] for row in ui.rows()}, {'installed', 'update-available', 'not-installed'})
        for language, states in [('en', ['Installed', 'Update available', 'Not installed']),
                                 ('zh', ['已安装', '有可用更新', '未安装'])]:
            ui.backend._language = language
            ui.backend.changed.emit()
            wait_for(lambda: ui.find('widgetMarketState_installed-widget').property('text') == states[0], self.app, 'Language did not update')
            for identifier, text in zip(('installed-widget', 'updated-widget', 'sample-widget'), states):
                self.assertEqual(ui.find('widgetMarketState_' + identifier).property('text'), text)
        calls = len(ui.fetch.calls)
        ui.click('widgetMarketRefresh')
        ui.idle()
        self.assertGreater(len(ui.fetch.calls), calls)
        self.assertEqual(ui.warnings, [])

    def test_install_native_dialog_then_real_import_disabled_management_row_and_uninstall(self):
        ui = self.ui
        with patch.object(ui.manager, 'importZip', wraps=ui.manager.importZip) as importer:
            ui.start_install('sample-widget')
            approval = ui.host.pendingApproval
            self.assertIn('Permissions: workspace.read', approval['detail'])
            self.assertIn('digest', approval['detail'])
            self.assertTrue(ui.find('toolApproval').property('visible'))
            self.assertFalse(ui.host.panelApproval)
            importer.assert_not_called()
            ui.click('widgetallowToolButton')
            ui.idle()
        self.assertEqual(importer.call_count, 1)
        row = next(row for row in ui.manager.rows if row['id'] == 'sample-widget')
        self.assertFalse(row['enabled'])
        self.assertFalse(row['running'])
        self.assertEqual(next(row for row in ui.rows() if row['id'] == 'sample-widget')['state'], 'installed')
        with patch.object(ui.manager, 'uninstall', wraps=ui.manager.uninstall) as uninstall:
            ui.js('uninstall(' + json.dumps(next(row for row in ui.rows() if row['id'] == 'sample-widget')) + ')')
            wait_for(lambda: bool(ui.host.pendingApproval), self.app, 'Native uninstall confirmation missing')
            uninstall.assert_not_called()
            ui.click('widgetallowToolButton')
            ui.idle()
        uninstall.assert_called_once_with('sample-widget')
        self.assertNotIn('sample-widget', ui.manager.entries)
        self.assertEqual(ui.warnings, [])

    def test_declining_confirmation_keeps_package_uninstalled_and_cleans_download(self):
        ui = self.ui
        ui.start_install('sample-widget')
        downloaded = [Path(item['package']['path']) for item in ui.host._market.prepared.values()]
        ui.click('widgetdenyToolButton')
        ui.idle()
        self.assertNotIn('sample-widget', ui.manager.entries)
        self.assertTrue(all(not path.exists() for path in downloaded))
        self.assertIn('Canceled', ui.find('widgetMarketState_sample-widget').property('text'))
        self.assertEqual(ui.warnings, [])


def capture_documentation():
    application()
    for language in ('zh', 'en'):
        with temporary_directory('umeko-market-capture-') as directory:
            ui = MarketUi(directory, language)
            try:
                ui.capture(ROOT / ('docs/images/widget-market-' + language + '.png'))
                if language == 'en':
                    ui.start_install('sample-widget')
                    ui.capture(ROOT / 'docs/images/widget-market-confirmation-en.png')
            finally:
                ui.close()
    print('WIDGET_MARKET_CAPTURES_OK')


if __name__ != '__main__':
    class IsolatedWidgetMarketUiTests(unittest.TestCase):
        def test_widget_market_ui_in_windowless_process(self):
            environment = dict(os.environ, PYTHONUTF8='1', QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software')
            result = subprocess.run([sys.executable, str(Path(__file__).resolve())], cwd=ROOT,
                env=environment, capture_output=True, text=True, encoding='utf-8', timeout=150,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print((result.stdout + result.stderr).strip())


def load_tests(loader, tests, pattern):
    if __name__ == '__main__': return tests
    return unittest.TestSuite([IsolatedWidgetMarketUiTests('test_widget_market_ui_in_windowless_process')])


if __name__ == '__main__':
    if sys.argv[1:] == ['--capture']: capture_documentation()
    else: unittest.main()
