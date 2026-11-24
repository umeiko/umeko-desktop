import unittest
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
