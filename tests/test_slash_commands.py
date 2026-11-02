import unittest
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtCore import QObject, Signal, QCoreApplication
from app.slash_commands import SlashCommands

APP = QCoreApplication.instance() or QCoreApplication([])


class Plugins(QObject):
    changed = Signal()
    sessionPlugins = []
    enabled = True

    def skills_enabled(self, record):
        return self.enabled


class Backend(QObject):
    viewChanged = Signal()
    jobDone = Signal(str, object)
    appearanceChanged = Signal()
    toast = Signal(str)

    def __init__(self):
        super().__init__()
        self._closing = False
        self.language = 'zh'
        self._release = Path('.')
        self._view = SimpleNamespace(key='first', workspace='', skill_modes={}, known_skills={})
        self.store = SimpleNamespace(data={'agent': {}})
        self.desktopPlugins = Plugins(self)
        self.piManagement = SimpleNamespace(_context=lambda: (self._release, '.', '.', {}))
        self.jobs = []

    def _job(self, name, work):
        self.jobs.append((name, work))


class SlashCommandTests(unittest.TestCase):
    def setUp(self):
        self.b = Backend()
        self.commands = SlashCommands(self.b)
        self.notifications = []
        self.commands.changed.connect(lambda: self.notifications.append(True))
        self.payload = {'ok': True, 'value': {'skills': [{'id':'fixture', 'name':'fixture',
            'path':'/skills/fixture/SKILL.md', 'attached':True, 'description':'A skill', 'scope':'global'}]}}

    def test_cached_opens_and_identical_background_refresh_do_not_reset_entries(self):
        c = self.commands
        c.refresh(); c.finished('slash-skills', self.payload)
        self.notifications.clear()
        rows = c.entries
        for _ in range(5):
            c.refresh(); self.b.desktopPlugins.changed.emit()
        self.assertEqual(len(self.b.jobs), 1)
        self.assertIs(c.entries, rows)
        self.assertFalse(self.notifications)
        c._loaded_at -= c.CACHE_SECONDS + 1
        c.refresh(); self.assertEqual(len(self.b.jobs), 2)
        c.finished('slash-skills', self.payload)
        self.assertIs(c.entries, rows)
        self.assertFalse(self.notifications)

    def test_disabled_widget_and_new_chat_do_not_reuse_another_catalog(self):
        c = self.commands
        c.refresh(); c.finished('slash-skills', self.payload)
        self.b.desktopPlugins.enabled = False; self.b.desktopPlugins.changed.emit()
        self.assertFalse(any(row['group'] == '技能' for row in c.entries))
        c.refresh(); self.assertEqual(len(self.b.jobs), 1)
        self.b.desktopPlugins.enabled = True; self.b.desktopPlugins.changed.emit()
        c.refresh(); self.assertEqual(len(self.b.jobs), 2)
        self.b._view.key = 'second'; self.b.viewChanged.emit()
        c.finished('slash-skills', self.payload)
        self.assertEqual(len(self.b.jobs), 3)
        self.assertFalse(any(row['group'] == '技能' for row in c.entries))

    def test_failure_is_retryable_and_explicit_reload_invalidates_the_cache(self):
        c = self.commands
        c.refresh(); c.finished('slash-skills', {'ok':False, 'value':'fixture failure'})
        c.refresh(); self.assertEqual(len(self.b.jobs), 2)
        c.finished('slash-skills', self.payload)
        c.invalidate(); c.refresh()
        self.assertEqual(len(self.b.jobs), 3)


if __name__ == '__main__':
    unittest.main()
