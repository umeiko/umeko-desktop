"""settings.json edits made by other programs while Umeko is running."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from app.storage import Store


def profile(model):
    return {'session-task-service': {'tasks': {'workspace': '/work', 'model': model, 'provider': 'test-provider',
        'tools': ['read'], 'permissionMode': 'ask', 'allowApprovals': False}}}


class ExternalSettingsEditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='umeko-settings-external-')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        (self.directory / 'settings.json').write_text(json.dumps({
            'server': {'keys': []}, 'agent': {'outputLimitDefaultVersion': 1},
            'ui': {'language': 'en', 'lineSpacing': 'standard'},
            'pluginSessionProfiles': profile('test-model-a')}), encoding='utf-8')
        self.store = Store(self.directory)
        self.notices = []
        self.store.external_change = lambda keys, invalid: self.notices.append((keys, invalid))

    def disk(self):
        return json.loads((self.directory / 'settings.json').read_text(encoding='utf-8'))

    def edit(self, change):
        data = self.disk()
        change(data)
        (self.directory / 'settings.json').write_text(json.dumps(data, indent=2), encoding='utf-8')

    def test_save_keeps_an_external_edit_and_the_in_memory_change(self):
        self.edit(lambda data: data['pluginSessionProfiles']['session-task-service']['tasks'].update(model='test-model-b'))
        self.store.data['ui']['sidebarWidth'] = 300
        self.store.save()
        saved = self.disk()
        self.assertEqual(saved['pluginSessionProfiles'], profile('test-model-b'))
        self.assertEqual(saved['ui']['sidebarWidth'], 300)
        self.assertEqual(self.store.data['pluginSessionProfiles'], profile('test-model-b'))
        self.assertEqual(self.notices, [(['pluginSessionProfiles'], False)])
        self.store.data['ui']['sidebarWidth'] = 320
        self.store.save()
        self.assertEqual(self.disk()['pluginSessionProfiles'], profile('test-model-b'))
        self.assertEqual(len(self.notices), 1)

    def test_conflicting_field_takes_the_disk_value_and_keeps_live_references(self):
        keys = self.store.data['server']['keys']
        self.edit(lambda data: (data['ui'].update(sidebarWidth=410), data['server']['keys'].append({'id': 'external'})))
        self.store.data['ui']['sidebarWidth'] = 222
        self.store.data['ui']['sidebarCollapsed'] = True
        self.store.save()
        self.assertEqual(self.store.data['ui']['sidebarWidth'], 410)
        self.assertIs(self.store.data['ui']['sidebarCollapsed'], True)
        self.assertEqual(self.disk()['ui']['sidebarWidth'], 410)
        self.assertIs(self.store.data['server']['keys'], keys)
        self.assertEqual(keys, [{'id': 'external'}])

    def test_external_removal_and_unchanged_file(self):
        self.store.save()
        self.assertEqual(self.notices, [])
        self.edit(lambda data: data.pop('pluginSessionProfiles'))
        self.store.save()
        self.assertNotIn('pluginSessionProfiles', self.store.data)
        self.assertNotIn('pluginSessionProfiles', self.disk())
        self.assertEqual(self.notices, [(['pluginSessionProfiles'], False)])

    def test_unreadable_external_file_is_kept_as_a_copy(self):
        (self.directory / 'settings.json').write_text('{"broken"', encoding='utf-8')
        self.store.save()
        self.assertEqual((self.directory / 'settings.external-invalid.json').read_text(encoding='utf-8'), '{"broken"')
        self.assertEqual(self.disk()['pluginSessionProfiles'], profile('test-model-a'))
        self.assertEqual(self.notices, [([], True)])

    def test_three_way_merge_rules(self):
        from app.storage import merge_external
        base = {'a': 1, 'b': {'x': 1, 'y': 1}, 'gone': 1}
        ours = {'a': 2, 'b': {'x': 2, 'y': 1}, 'gone': 1, 'mine': 1}
        theirs = {'a': 1, 'b': {'x': 3, 'y': 4}, 'new': 1}
        self.assertEqual(merge_external(base, ours, theirs), {'a': 2, 'b': {'x': 3, 'y': 4}, 'mine': 1, 'new': 1})


if __name__ == '__main__':
    unittest.main()
