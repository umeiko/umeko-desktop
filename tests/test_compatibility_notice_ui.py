"""Offscreen coverage for cached compatibility notices in the existing QML."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


def run_ui(directory):
    # Imported only by the child after its Qt environment has been selected.
    from PySide6.QtCore import QObject, Property, QMetaObject, QUrl, Signal, Slot
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickWindow

    root = Path(__file__).resolve().parents[1]
    recorded_at = 1_800_000_000
    metadata = [
        {'parameter': 'thinking', 'recordedAt': recorded_at, 'ageDays': 3, 'action': 'omitted'},
        {'parameter': 'tool_choice', 'recordedAt': recorded_at + 2 * 86400, 'ageDays': 1, 'action': 'auto'},
    ]
    report = {'http': [
        {'request': {'method': 'POST', 'body': {}}, 'response': {'status': 400}},
        {'request': {'method': 'POST', 'body': {}}, 'response': {'status': 200}, 'compatibility': metadata},
    ]}

    class Backend(QObject):
        changed = Signal()
        detailsRequested = Signal(str)

        def __init__(self):
            super().__init__()
            self.opened = []
            self.language_value = 'zh'

        @Property(str, notify=changed)
        def language(self): return self.language_value

        @Property(float, constant=True)
        def fontScale(self): return 1.0

        @Property(str, constant=True)
        def lineSpacing(self): return 'standard'

        @Property('QVariantMap', constant=True)
        def themeStyle(self): return {'base': 'light', 'colors': {}}

        @Property('QVariantList', constant=True)
        def commonProviders(self): return []

        @Property('QVariantMap', constant=True)
        def config(self):
            return {'fontFamily': '', 'theme': 'light', 'providers': [{
                'id': 'sample', 'name': '兼容接口', 'api': 'openai', 'baseUrl': '',
                'models': [], 'compatibilityNotice': '已按此前的拒绝记录省略 thinking（3 天前记录）',
                'compatibilityReportId': 'sample-report',
            }]}

        @Slot(str, result=str)
        def requestReport(self, identifier):
            return json.dumps(report) if identifier == 'sample-report' else ''

        @Slot(str)
        def showRequestDetails(self, identifier):
            self.opened.append(identifier)
            self.detailsRequested.emit(identifier)

    app = QGuiApplication.instance() or QGuiApplication([])
    backend = Backend()
    engine = QQmlApplicationEngine()
    engine.setIncubationController(None)
    engine.rootContext().setContextProperty('backend', backend)
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
    source = Path(directory) / 'compatibility.qml'
    qml_url = QUrl.fromLocalFile(str(root / 'app/qml')).toString()
    source.write_text('''import QtQuick
import QtQuick.Controls
import ''' + json.dumps(qml_url) + '''
ApplicationWindow {
    width: 1280; height: 900; visible: true
    ProviderAccountList { anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 24; accounts: backend.config.providers }
    RequestDetails { id: details }
    Connections { target: backend; function onDetailsRequested(identifier) { details.show(identifier) } }
}
''', encoding='utf8')
    engine.load(QUrl.fromLocalFile(str(source)))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]

    def find(name):
        pending = [window.contentItem()]
        while pending:
            item = pending.pop()
            if item.objectName() == name:
                return item
            pending.extend(item.childItems())
        raise AssertionError(name)

    try:
        app.processEvents()
        link = find('providerCompatibility_sample')
        assert link.isVisible() and link.isEnabled()
        assert 'thinking' in link.property('text')
        assert '3 天前记录' in link.property('text')
        assert QMetaObject.invokeMethod(link, 'clicked')
        app.processEvents()
        assert backend.opened == ['sample-report']
        dialog = window.findChild(QObject, 'requestDetailsDialog')
        assert dialog.property('opened')
        notice = find('requestCompatibilityNotice')
        text = notice.property('text')
        assert notice.isVisible()
        assert '省略 thinking（3 天前记录）' in text, text
        assert '将 tool_choice 改为 auto（1 天前记录）' in text, text
        assert dialog.property('callIndex') == 1
        # Ages come from the selected call's recorded metadata, independent of
        # today's clock. Selecting an unmodified attempt removes the notice.
        dialog.setProperty('callIndex', 0)
        app.processEvents()
        assert not notice.isVisible() and notice.property('text') == ''
        dialog.setProperty('callIndex', 1)
        backend.language_value = 'en'
        backend.changed.emit()
        app.processEvents()
        english = notice.property('text')
        assert 'Omitted thinking' in english and '3 days ago' in english, english
        assert 'Changed tool_choice to auto' in english and '1 day ago' in english, english
        assert not warnings, warnings
        print('COMPATIBILITY_NOTICE_UI_OK', flush=True)
    finally:
        window.close()
        app.processEvents()
        import shiboken6
        shiboken6.delete(engine)


class CompatibilityNoticeUiTests(unittest.TestCase):
    def test_provider_link_and_selected_call_metadata(self):
        base = Path('C:/UmekoTests') if os.name == 'nt' else Path(tempfile.gettempdir())
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='compatibility-notice-ui-', dir=base) as directory:
            environment = {**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'QT_QUICK_BACKEND': 'software',
                           'QSG_RHI_BACKEND': 'software', 'QT_QUICK_CONTROLS_STYLE': 'Basic'}
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker', directory],
                cwd=Path(__file__).resolve().parents[1], env=environment,
                capture_output=True, text=True, encoding='utf8', timeout=45,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('COMPATIBILITY_NOTICE_UI_OK', result.stdout)


if __name__ == '__main__':
    if len(sys.argv) > 2 and sys.argv[1] == '--worker':
        run_ui(sys.argv[2])
    else:
        unittest.main()
