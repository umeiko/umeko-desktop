"""Real QML settings bindings across cached sessions; no provider or desktop I/O."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
os.environ.setdefault('QSG_RHI_BACKEND', 'software')

from tests.test_preview_channel import qt_application, isolated_test_module
from PySide6.QtCore import QMetaObject, Qt, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow  # Register visual-parent wrappers.
from PySide6.QtTest import QSignalSpy
import shiboken6

from app.controller import Controller
from app.pi_sessions import SessionState
from app.storage import Store


class SessionSettingsDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = qt_application()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='umeko-session-settings-')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, {
            'UMEKO_DATA_DIR': str(self.directory / 'profile'),
            'PI_CODING_AGENT_DIR': str(self.directory / 'agent'),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        seed = Store()
        seed.data['agent'].update(agentDir=str(self.directory / 'agent'), toolPermissionMode='auto')
        seed.data['ui']['language'] = 'en'
        seed.data['providers'] = [
            {'id': 'fixture-one', 'name': 'Fixture One', 'api': 'openai', 'baseUrl': 'https://example.invalid',
             'key': '', 'models': [{'alias': 'fixture-alpha', 'upstream': 'fixture-alpha'}]},
            {'id': 'fixture-two', 'name': 'Fixture Two', 'api': 'openai', 'baseUrl': 'https://example.invalid',
             'key': '', 'models': [{'alias': 'fixture-beta', 'upstream': 'fixture-beta'}]},
        ]
        seed.data.update(selectedProvider='fixture-one', selectedModel='fixture-alpha')
        seed.save()
        self.controller = Controller(ROOT)
        self.addCleanup(self.controller.close)
        self.command = patch.object(self.controller, '_command_pi', side_effect=AssertionError('No kernel command in display test'))
        self.job = patch.object(self.controller, '_job', side_effect=AssertionError('No background job in display test'))
        self.command_mock = self.command.start()
        self.job_mock = self.job.start()
        self.addCleanup(self.command.stop)
        self.addCleanup(self.job.stop)
        self.engine = QQmlApplicationEngine()
        self.addCleanup(self.close_engine)
        self.warnings = []
        self.engine.warnings.connect(lambda errors: self.warnings.extend(error.toString() for error in errors))
        self.engine.rootContext().setContextProperty('backend', self.controller)
        source = '''import QtQuick
import QtQuick.Controls
import "QML_DIRECTORY" as Umeko
ApplicationWindow {
    width: 1200; height: 950; visible: true
    Umeko.Composer { id: composer; width: parent.width; anchors.bottom: parent.bottom }
    Umeko.AgentSettings { width: parent.width }
    Umeko.ModelPopup { parent: composer.modelAnchor }
}'''.replace('QML_DIRECTORY', QUrl.fromLocalFile(str(ROOT / 'app/qml')).toString())
        self.engine.loadData(source.encode('utf-8'))
        self.assertTrue(self.engine.rootObjects(), '\n'.join(self.warnings))
        self.window = self.engine.rootObjects()[0]
        QMetaObject.invokeMethod(self.find('modelPopup'), 'open', Qt.DirectConnection)
        self.application.processEvents()

    def close_engine(self):
        shiboken6.delete(self.engine)

    def tearDown(self):
        self.assertEqual(self.warnings, [])
        self.command_mock.assert_not_called()
        self.job_mock.assert_not_called()

    def descendants(self, root):
        pending, seen = [root], set()
        while pending:
            item = pending.pop()
            identity = shiboken6.getCppPointer(item)[0]
            if identity in seen:
                continue
            seen.add(identity)
            yield item
            pending.extend(item.children())
            if hasattr(item, 'childItems'):
                pending.extend(item.childItems())
            content_property = getattr(item, 'contentItem', None)
            content = content_property() if callable(content_property) else item.property('contentItem')
            if content is not None:
                pending.append(content)

    def find(self, name):
        for item in self.descendants(self.window):
            if item.objectName() == name:
                return item
        self.fail('Missing production QML object: ' + name)

    def session(self, identifier, workspace, *, provider='fixture-one', model='fixture-alpha',
                effort='low', tokens=1200, percent=12.0):
        path = self.directory / workspace
        path.mkdir(exist_ok=True)
        record = SessionState(id=identifier, title=identifier, workspace=str(path),
                              provider=provider, model=model, reasoning_effort=effort,
                              context_usage={'model': model, 'tokens': tokens,
                                             'contextWindow': 10000, 'percent': percent})
        self.controller._sessions.append({'id': identifier, 'title': identifier, 'file': '', 'workspace': str(path)})
        self.controller.store.data['sessionMeta'][identifier] = {'unread': False}
        self.controller._pool.touch(record)
        return record

    def assert_display(self, record, permission):
        self.application.processEvents()
        selector = self.find('modelSelector')
        texts = [item.property('text') for item in self.descendants(selector) if item.metaObject().indexOfProperty('text') >= 0]
        provider = 'Fixture One' if record.provider == 'fixture-one' else 'Fixture Two'
        self.assertIn(provider, texts)
        self.assertIn(record.model, texts)
        prompt = self.find('promptInput')
        self.assertIn(Path(record.workspace).name, prompt.property('placeholderText'))
        self.assertEqual(self.controller.workspaceName, Path(record.workspace).name)
        badge = self.find('reasoningEffortBadge')
        self.assertEqual(badge.property('text'), '· ' + {'low': 'Low', 'high': 'High', 'max': 'Max', 'off': ''}[record.reasoning_effort])
        self.assertEqual(badge.property('visible'), record.reasoning_effort != 'off')
        for value in ('off', 'low', 'high', 'max'):
            self.assertEqual(self.find('reasoningEffort_' + value).property('primary'), value == record.reasoning_effort)
        for value in ('ask', 'auto'):
            self.assertEqual(self.find('toolPermission_' + value).property('primary'), value == permission)
        usage = self.find('contextUsageIndicator')
        self.assertTrue(usage.property('known'))
        self.assertAlmostEqual(usage.property('fraction'), record.context_usage['percent'] / 100)
        self.assertIn(f"{record.context_usage['percent']:.1f}%", usage.property('description'))
        actual_usage = usage.property('usage')
        if hasattr(actual_usage, 'toVariant'):
            actual_usage = actual_usage.toVariant()
        self.assertEqual(actual_usage['model'], record.model)
        self.assertEqual(actual_usage['tokens'], record.context_usage['tokens'])

    def test_model_workspace_and_global_permission_remain_visible_across_switches(self):
        c = self.controller
        first = self.session('first', 'project-alpha', effort='low', tokens=1200, percent=12.0)
        second = self.session('second', 'project-beta', provider='fixture-two', model='fixture-beta',
                              effort='high', tokens=7300, percent=73.0)
        c.openSession(first.id)
        self.assert_display(first, 'auto')
        # Permission mode is global. Exercise its public setter between the
        # session transitions, then verify that switching preserves the choice.
        permission_changed = QSignalSpy(c.changed)
        QMetaObject.invokeMethod(self.find('toolPermission_ask'), 'clicked', Qt.DirectConnection)
        self.assertEqual(permission_changed.count(), 1)
        self.assertEqual(c.config['agent']['toolPermissionMode'], 'ask')
        self.assert_display(first, 'ask')
        changed, view = QSignalSpy(c.changed), QSignalSpy(c.viewChanged)
        reasoning, context = QSignalSpy(c.reasoningChanged), QSignalSpy(c.contextUsageChanged)
        c.openSession(second.id)
        self.assertEqual(changed.count(), 1)
        self.assertEqual(view.count(), 1)
        self.assertEqual(reasoning.count(), 1)
        self.assertEqual(context.count(), 1)
        self.assert_display(second, 'ask')
        c.setToolPermissionMode('auto')
        self.assert_display(second, 'auto')
        c.openSession(first.id)
        self.assert_display(first, 'auto')

    def test_same_configuration_skips_changed_but_session_only_qml_values_update(self):
        c = self.controller
        first = self.session('same-first', 'shared-project', effort='low', tokens=1200, percent=12.0)
        second = self.session('same-second', 'shared-project', effort='max', tokens=9200, percent=92.0)
        # Populate both sessions' normal read/project metadata before observing
        # the no-global-change transition.
        c.openSession(first.id)
        c.openSession(second.id)
        c.openSession(first.id)
        self.assert_display(first, 'auto')
        changed, view = QSignalSpy(c.changed), QSignalSpy(c.viewChanged)
        reasoning, context = QSignalSpy(c.reasoningChanged), QSignalSpy(c.contextUsageChanged)
        before = c.config
        c.openSession(second.id)
        self.assertEqual(c.config, before)
        self.assertEqual(changed.count(), 0)
        self.assertEqual(view.count(), 1)
        self.assertEqual(reasoning.count(), 1)
        self.assertEqual(context.count(), 1)
        self.assert_display(second, 'auto')


def load_tests(loader, tests, pattern):
    if __name__ == '__main__':
        return tests
    class Isolated(unittest.TestCase):
        def runTest(self):
            isolated_test_module(self, Path(__file__))
    return unittest.TestSuite([Isolated()])


if __name__ == '__main__':
    unittest.main(verbosity=2)
