import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from app.remote_environments import RemoteEnvironments


class RemoteEnvironmentSettingsTest(unittest.TestCase):
    def setUp(self):
        self.save = Mock()
        self.changed = Mock()
        self.store = SimpleNamespace(data={}, save=self.save)
        self.registry = RemoteEnvironments(self.store, self.changed)

    def test_registration_and_live_reconnect_state(self):
        environment = self.registry.add('build', 'ssh-build', 'linux')
        self.assertEqual(environment['state'], 'disconnected')
        self.assertEqual(self.registry.add('build', 'ssh-build', 'linux'), environment)
        self.save.assert_called_once()

        self.registry.observe('chat', {**environment, 'state': 'reconnecting'})
        self.assertEqual(self.registry.rows()[0]['state'], 'reconnecting')
        self.registry.observe('chat', {**environment, 'state': 'connected'})
        self.assertEqual(self.registry.rows()[0]['state'], 'connected')
        self.registry.disconnect('chat')
        self.assertEqual(self.registry.rows()[0]['state'], 'disconnected')

        self.registry.remove('build')
        self.registry.observe('chat', {**environment, 'state': 'connected'})
        self.assertEqual(self.registry.rows(), [])
        self.assertEqual(self.store.data['remoteEnvironments'], [])

    def test_rejects_options_and_conflicting_names(self):
        with self.assertRaises(ValueError):
            self.registry.add('build', '-oProxyCommand=example', 'linux')
        self.registry.add('build', 'build-a', 'linux')
        with self.assertRaises(ValueError):
            self.registry.add('build', 'build-b', 'windows')

    def test_ssh_diagnostics_follow_the_selected_connection_and_clear_on_recovery(self):
        environment = self.registry.add('build', 'ssh-build', 'linux')
        client = str(Path('ssh-client-for-test').absolute())
        diagnostic = 'posix_spawnp: No such file or directory'
        retry = {**environment, 'state': 'reconnecting', 'sshClient': client,
                 'message': 'OpenSSH failed: ' + diagnostic, 'sshError': diagnostic,
                 'attempt': 1, 'retryAfterMs': 60000}
        self.registry.observe('chat', retry)
        self.assertEqual(self.registry.rows()[0], {key: value for key, value in retry.items()})
        before = self.changed.call_count
        self.registry.observe('chat', {**retry, 'attempt': 2})
        self.assertEqual(self.registry.rows()[0]['attempt'], 2)
        self.assertEqual(self.changed.call_count, before + 1)

        connected = {**environment, 'state': 'connected', 'sshClient': client}
        self.registry.observe('second-chat', connected)
        self.assertEqual(self.registry.rows()[0], connected)
        self.registry.disconnect('second-chat')
        self.assertEqual(self.registry.rows()[0]['message'], retry['message'])
        self.registry.observe('chat', connected)
        self.assertEqual(self.registry.rows()[0], connected)

    def test_settings_render_client_retry_and_plain_text_error(self):
        qml = (Path(__file__).parents[1] / 'app/qml/DesktopSettings.qml').read_text(encoding='utf-8')
        self.assertIn('"remoteEnvironmentSshClient_" + modelData.name', qml)
        self.assertIn('modelData.sshClient || ""', qml)
        self.assertIn('modelData.retryAfterMs || 0', qml)
        error_label = qml.split('objectName: "remoteEnvironmentError_"', 1)[1].split('font.pixelSize:', 1)[0]
        self.assertIn('modelData.message || modelData.sshError || ""', error_label)
        self.assertIn('textFormat: Text.PlainText', error_label)
