"""Production dependency QML + shared service/API. Isolated profile, no models."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software', QT_QUICK_CONTROLS_STYLE='Basic')

from PySide6.QtCore import QObject, Property, QUrl, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import shiboken6

from app.runtime_capabilities import RuntimeCapabilities
from app.umeko_control import UmekoControl
from tests.test_runtime_capabilities import DependencyTests


class Backend(QObject):
    changed = Signal()
    viewChanged = Signal()
    jobDone = Signal(str, object)

    def __init__(self, directory):
        super().__init__()
        self._language = 'zh'
        self._closing = False
        self._view = SimpleNamespace(workspace=directory)
        self.store = SimpleNamespace(directory=Path(directory))
        self.jobs = []
        self.service = RuntimeCapabilities(self)

    def _job(self, name, function): self.jobs.append((name, function))

    @Property(QObject, constant=True)
    def runtimeCapabilities(self): return self.service

    @Property(str, notify=changed)
    def language(self): return self._language

    @Property(float, constant=True)
    def fontScale(self): return 1.0

    @Property(str, constant=True)
    def lineSpacing(self): return 'standard'

    @Property('QVariantMap', constant=True)
    def config(self): return {'fontFamily': '', 'theme': 'light'}

    @Property('QVariantMap', constant=True)
    def themeStyle(self): return {'base': 'light', 'colors': {}}


app = QApplication([])
if os.environ.get('UMEKO_TEST_FONT'):
    QFontDatabase.addApplicationFont(os.environ['UMEKO_TEST_FONT'])
with tempfile.TemporaryDirectory(prefix='Umeko 依赖 ') as directory:
    backend = Backend(directory)
    api = UmekoControl.__new__(UmekoControl)
    QObject.__init__(api)
    api.b = backend
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
    engine.rootContext().setContextProperty('backend', backend)
    source = '''import QtQuick
import QtQuick.Controls
import "%s" as UI
ApplicationWindow {
    width: 880; height: 920; visible: true; color: UI.Theme.bg
    ScrollView { anchors.fill: parent; anchors.margins: 24; contentWidth: availableWidth; clip: true
        UI.RuntimeCapabilities { width: parent.width }
    }
}''' % QUrl.fromLocalFile(str(ROOT / 'app/qml')).toString()
    engine.loadData(source.encode(), QUrl.fromLocalFile(str(ROOT / 'tests/RuntimeCapabilitiesHarness.qml')))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]

    def find(name):
        stack = [window.contentItem()]
        while stack:
            item = stack.pop()
            if item.objectName() == name: return item
            stack.extend(item.childItems())
        raise AssertionError('Missing QML item: ' + name)

    def settle():
        app.processEvents()
        QTest.qWait(80)

    try:
        settle()
        assert len(backend.jobs) == 1, backend.jobs
        assert '正在检测' in find('runtimeCapabilitiesState').property('text')
        assert not find('refreshRuntimeCapabilities').property('enabled')
        runner, _ = DependencyTests().fixture(missing=('playwright.sync_api',))
        report = DependencyTests().inspect(runner, absent=('soffice', 'libreoffice'))
        report['workspace'] = directory
        backend.jobDone.emit(backend.jobs[0][0], {'ok': True, 'value': report})
        settle()
        shared = api.execute({'operation': 'capabilities.get'})['snapshot']
        assert shared['capabilities'] == backend.service.snapshot['capabilities']
        assert shared['checkedAt'] == backend.service.snapshot['checkedAt']
        assert '部分可用' in find('runtimeCapability_office').property('title')
        assert '缺失' in find('runtimeCapability_browser').property('title')
        assert '可用' in find('runtimeCapability_git').property('title')
        assert find('refreshRuntimeCapabilities').property('enabled')

        output = ROOT / 'build/runtime-capabilities-ui'
        output.mkdir(parents=True, exist_ok=True)
        for language in ('zh', 'en'):
            backend._language = language
            backend.changed.emit()
            settle()
            if language == 'en':
                assert 'Partially available' in find('runtimeCapability_office').property('title')
                assert find('refreshRuntimeCapabilities').property('text') == 'Check again'
            assert window.grabWindow().save(str(output / (language + '.png')))

        find('runtimeCapability_office').setProperty('expanded', True)
        settle()
        assert window.grabWindow().save(str(output / 'details.png'))
        find('refreshRuntimeCapabilities').clicked.emit()
        settle()
        assert len(backend.jobs) == 2
        assert not find('refreshRuntimeCapabilities').property('enabled')
        backend.jobDone.emit(backend.jobs[1][0], {'ok': False, 'value': 'fixture-secret'})
        settle()
        assert 'Check failed' in find('runtimeCapabilitiesState').property('text')
        assert not backend.service.snapshot.get('capabilities')

        backend._view = SimpleNamespace(workspace=directory + '/other')
        backend.viewChanged.emit()
        settle()
        assert backend.service.snapshot['state'] == 'unchecked'
        assert not backend.service.snapshot.get('capabilities')
        assert not warnings, '\n'.join(warnings)
        print('RUNTIME_CAPABILITIES_UI_OK: shared API, zh/en, states, details, refresh, failure and workspace isolation')
    finally:
        backend._closing = True
        window.close()
        shiboken6.delete(engine)
