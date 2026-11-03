"""Real DesktopPlugins import/update/uninstall through the market host API.

Every catalog response and ZIP is local. No model or network calls are made.
"""
import io
import json
from pathlib import Path
import sys
import unittest
import zipfile
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent))
from PySide6.QtCore import QCoreApplication, QUrl
from widget_market_fixture import Backend, local_catalog, package, request, wait_for, temporary_directory
from app.desktop_plugins import DesktopPlugins


class WidgetMarketHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temporary = temporary_directory('umeko-market-host-')
        self.addCleanup(self.temporary.cleanup)
        self.backend = Backend(self.temporary.name)
        self.addCleanup(self.backend.close)
        self.manager = self.backend.desktopPlugins
        self.host = self.manager.hostServices
        self.fetch = local_catalog(self.backend)
        self.assertTrue(self.manager.openPage('widget-market'))
        wait_for(lambda: self.manager.workers.get('widget-market', {}).get('ready'), self.app, lambda: 'Market worker did not initialize: ' + str(self.manager.page))

    def result(self, operation, args=None, confirm=None):
        key = request(self.backend, self.app, operation, args, confirm)
        return self.backend.replies[key]

    def prepare(self):
        self.assertTrue(self.result('market.list')['ok'])
        value = self.result('market.prepare', {'id': 'sample-widget'})
        self.assertTrue(value['ok'], value)
        return value['result']['token']

    def test_list_merges_real_installed_versions_and_permissions_block_fetch(self):
        self.manager.entries['sample-widget'] = {**package()[0], 'builtin': False}
        result = self.result('market.list')['result']['rows'][0]
        self.assertEqual((result['state'], result['installedVersion']), ('installed', '1.0.0'))
        self.manager.entries['widget-market']['permissions'] = []
        before = len(self.fetch.calls)
        denied = self.result('market.list', {'force': True})
        self.assertFalse(denied['ok'])
        self.assertEqual(len(self.fetch.calls), before)

    def test_prepare_confirmation_decline_cleans_download_and_never_imports(self):
        token = self.prepare()
        path = Path(self.host._market.prepared[token]['package']['path'])
        with patch.object(self.manager, 'importZip', wraps=self.manager.importZip) as importer:
            key = request(self.backend, self.app, 'market.install', {'token': token})
            approval = self.host.pendingApproval
            self.assertEqual(approval['id'], key)
            self.assertIn('Permissions: workspace.read', approval['detail'])
            self.assertIn('digest', approval['detail'])
            self.assertIn('not added to this chat or run', approval['detail'])
            importer.assert_not_called()
            self.host.respondApproval(False)
            wait_for(lambda: key in self.backend.replies, self.app, 'Decline did not reply')
        self.assertFalse(path.exists())
        self.assertNotIn('sample-widget', self.manager.entries)

    def test_real_async_import_update_retains_config_and_uninstall_uses_manager(self):
        token = self.prepare()
        with patch.object(self.manager, 'importZip', wraps=self.manager.importZip) as importer:
            installed = self.result('market.install', {'token': token}, True)
        self.assertTrue(installed['ok'], installed)
        self.assertEqual(importer.call_count, 1)
        row = next(row for row in self.manager.rows if row['id'] == 'sample-widget')
        self.assertTrue(row['enabled'])
        self.assertFalse(row['sessionEnabled'])
        self.assertNotIn('sample-widget', {item['id'] for item in self.manager.sessionPlugins})
        self.assertFalse(row['running'])
        self.manager.settings['config']['sample-widget'] = {'choice': 'retained'}
        self.manager.save()
        local_catalog(self.backend, [('sample-widget', '2.0.0', 'Sample Widget')])
        self.assertEqual(self.result('market.list', {'force': True})['result']['rows'][0]['state'], 'update-available')
        token = self.prepare()
        self.assertTrue(self.result('market.install', {'token': token}, True)['ok'])
        self.assertEqual(self.manager.entries['sample-widget']['version'], '2.0.0')
        self.assertEqual(self.manager.settings['config']['sample-widget'], {'choice': 'retained'})
        with patch.object(self.manager, 'uninstall', wraps=self.manager.uninstall) as uninstall:
            key = request(self.backend, self.app, 'market.uninstall', {'id': 'sample-widget'})
            uninstall.assert_not_called()
            self.host.respondApproval(True)
            wait_for(lambda: key in self.backend.replies, self.app, 'Uninstall did not finish')
        uninstall.assert_called_once_with('sample-widget')
        self.assertNotIn('sample-widget', self.manager.entries)
        self.assertFalse((self.manager.root / 'packages/sample-widget').exists())

    def manual_import(self, identifier='manual-widget', version='1.0.0'):
        manifest, payload = package(identifier, version)
        manifest['page'] = 'qml/Main.qml'
        archive = Path(self.temporary.name) / (identifier + '-' + version + '.zip')
        with zipfile.ZipFile(io.BytesIO(payload)) as source, zipfile.ZipFile(archive, 'w') as target:
            for name in source.namelist():
                target.writestr(name, json.dumps(manifest) if name == 'manifest.json' else source.read(name))
            target.writestr('qml/Main.qml', 'import QtQuick\nItem {}\n')
        results = {}
        self.manager.managed.connect(lambda key, value: results.__setitem__(key, value))
        key = self.manager.importZip(QUrl.fromLocalFile(str(archive)).toString())
        self.assertTrue(key)
        wait_for(lambda: key in results, self.app, 'Manual ZIP import did not complete')
        self.assertTrue(results[key]['ok'], results[key])
        return identifier

    def test_manual_session_widget_import_retains_main_activation_behavior(self):
        identifier = self.manual_import()
        self.assertTrue(self.manager.enabled(identifier))
        self.assertFalse(self.manager.session_enabled(identifier))
        self.assertNotIn(identifier, {row['id'] for row in self.manager.sessionPlugins})
        self.assertNotIn(identifier, self.manager.workers)
        self.assertNotIn(identifier, self.manager.settings.get('enabled', {}))
        self.manager.setSessionEnabled(identifier, True)
        self.assertIn(identifier, {row['id'] for row in self.manager.sessionPlugins})
        self.assertNotIn(identifier, self.manager.workers, 'Page workers remain lazy until opened')
        self.assertNotIn(identifier, self.manager.settings.get('enabled', {}))
        self.manager.setEnabled(identifier, False)
        self.manager.setSessionEnabled(identifier, False)
        self.manager.setSessionEnabled(identifier, True)
        self.assertFalse(self.manager.enabled(identifier), 'Session enabling must not override global disabling')
        self.assertNotIn(identifier, {row['id'] for row in self.manager.sessionPlugins})

    def test_manual_import_digit_id_and_semver_build_survive_registry_reload(self):
        identifier = self.manual_import('1-manual-widget', '1.2.3+build.1')
        restored = DesktopPlugins(self.backend)
        try:
            self.assertEqual(restored.entries[identifier]['version'], '1.2.3+build.1')
            self.assertTrue(restored.enabled(identifier))
            self.assertFalse(restored.session_enabled(identifier))
            self.assertNotIn(identifier, {row['id'] for row in restored.sessionPlugins})
            self.assertNotIn(identifier, restored.workers)
        finally:
            restored.close()

    def test_import_completion_after_close_cleans_market_temp_without_ui_changes(self):
        token = self.prepare()
        downloaded = Path(self.host._market.prepared[token]['package']['path'])
        request(self.backend, self.app, 'market.install', {'token': token})
        self.host.respondApproval(True)
        self.manager.close()
        toasts, changes = [], []
        self.backend.toast.connect(toasts.append)
        self.manager.changed.connect(lambda: changes.append(True))
        wait_for(lambda: not self.host._market.imports, self.app, 'Closed import did not clean up')
        self.assertFalse(downloaded.exists())
        self.assertEqual(toasts, [])
        self.assertEqual(changes, [])

    def test_only_visible_builtin_market_can_dispatch_and_stale_confirmation_fails(self):
        self.manager.entries['widget-market']['builtin'] = False
        self.assertFalse(self.result('market.list')['ok'])
        self.assertEqual(self.fetch.calls, [])
        self.manager.entries['widget-market']['builtin'] = True
        token = self.prepare()
        key = request(self.backend, self.app, 'market.install', {'token': token})
        self.manager._session = {**self.manager._session, 'token': 'changed-session'}
        self.host.respondApproval(True)
        wait_for(lambda: key in self.backend.replies, self.app, 'Stale approval did not reply')
        self.assertFalse(self.backend.replies[key]['ok'])
        self.assertNotIn('sample-widget', self.manager.entries)


if __name__ == '__main__': unittest.main()
