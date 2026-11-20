"""Exercise discovery through the actual pet with isolated existing sessions."""
import ast
import json
from pathlib import Path
import re
import unittest
from tests import test_pet_timer as fixtures


class PetCommandsTests(unittest.TestCase):
    setUpClass = classmethod(lambda cls: fixtures.PetTimerTests.setUpClass())
    owner = fixtures.PetTimerTests.owner
    open = fixtures.PetTimerTests.open
    def setUp(self):
        fixtures.PetTimerTests.setUp(self)
        self.menu = self.pet.commandMenu
        self.binding = self.pet.assistantStatus['id']

    def query(self):
        result = self.menu.query(self.binding)
        self.assertTrue(result['ok'], result)
        return result

    def test_query_and_choose_do_not_dispatch_or_change_main_draft(self):
        result = self.query()
        self.assertEqual(result['target'], {'kind': 'assistant', 'id': self.binding})
        self.assertEqual([r['semantics'] for r in result['entries']],
                         ['select-target', 'prepare-operation'])
        self.assertTrue(result['entries'][1]['titlePinyin'])
        self.assertEqual(self.menu.choose(result['ticket'], 'timer')['command'], '/定时任务')
        self.assertFalse(self.menu.choose(result['ticket'], 'timer')['ok'])
        self.h._command_pi.assert_not_called()
        self.m.call_for.assert_not_called()
        self.assertIs(self.h._view, self.a)
        self.assertEqual(self.a.draft, '主窗口草稿')
        self.assertEqual(self.a.attachments, ['untouched'])

    def test_target_change_invalidates_candidate_without_fallback(self):
        old = self.query()
        project = self.pet.projectEntry
        project.openCommand('/项目', self.binding)
        project.select('b')
        project.setBody('保留项目草稿')
        self.assertFalse(self.menu.choose(old['ticket'], 'timer')['ok'])
        result = self.query()
        self.assertEqual(result['target'], {'kind': 'project', 'id': 'b'})
        self.b.workspace = 'changed'
        self.assertFalse(self.menu.choose(result['ticket'], 'project')['ok'])
        self.assertEqual(project.body, '保留项目草稿')
        self.m.call_for.assert_not_called()

    def test_disabled_after_query_is_rechecked(self):
        old = self.query()
        self.m.settings.setdefault('enabled', {})['scheduled-tasks'] = False
        self.assertFalse(self.menu.choose(old['ticket'], 'timer')['ok'])
        result = self.query()
        row = next(r for r in result['entries'] if r['id'] == 'timer')
        self.assertFalse(row['enabled'])
        self.assertTrue(row['reason'])
        self.m.call_for.assert_not_called()

    def test_unknown_stale_and_mismatched_binding_are_rejected(self):
        old = self.query()
        self.query()
        self.assertFalse(self.menu.choose(old['ticket'], 'project')['ok'])
        current = self.query()
        self.assertFalse(self.menu.choose(current['ticket'], 'arbitrary.widget.method')['ok'])
        current = self.query()
        self.assertFalse(self.menu.query('stale-binding')['ok'])
        self.assertFalse(self.menu.choose(current['ticket'], 'project')['ok'])
        self.m.call_for.assert_not_called()

    def test_deleted_session_and_replaced_widget_never_fallback(self):
        from pathlib import Path
        project = self.pet.projectEntry
        project.openCommand('/项目', self.binding)
        project.select('b')
        project.setBody('删除后保留')
        result = self.query()
        Path(self.b.file).unlink()
        self.assertFalse(self.menu.choose(result['ticket'], 'timer')['ok'])
        self.assertFalse(self.menu.query(self.binding)['ok'])
        self.assertEqual(project.body, '删除后保留')
        project.leaveProject()
        result = self.query()
        self.m.entries['scheduled-tasks']['builtin'] = False
        self.assertFalse(self.menu.choose(result['ticket'], 'timer')['ok'])
        self.h._command_pi.assert_not_called()
        self.m.call_for.assert_not_called()


class PetCommandTranslationTests(unittest.TestCase):
    def test_every_dynamic_menu_label_and_error_has_an_english_entry(self):
        root = Path(__file__).resolve().parents[1]
        backend = ast.parse((root / 'app/pet_commands.py').read_text(encoding='utf-8'))
        labels = {node.value for node in ast.walk(backend)
                  if isinstance(node, ast.Constant) and isinstance(node.value, str)
                  and re.search(r'[\u4e00-\u9fff]', node.value)}
        self.assertEqual(len(labels), 9)
        source = (root / 'app/qml/english.js').read_text(encoding='utf-8')
        translations = json.loads(source[source.index('{'):])
        self.assertEqual(sorted(labels - translations.keys()), [])
        self.assertTrue(all(re.search(r'[A-Za-z]', translations[label]) and
                            not re.search(r'[\u4e00-\u9fff]', translations[label])
                            for label in labels))
