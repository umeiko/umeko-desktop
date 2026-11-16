import tempfile
import unittest
from pathlib import Path
from app.selection_attachment import write_selection


class SelectionAttachmentTests(unittest.TestCase):
    def test_unicode_contents_collisions_and_safe_names(self):
        with tempfile.TemporaryDirectory() as directory:
            text = '中文𠮷 quoted text\n\n```python\nprint("hello")\n```\n'
            first = write_selection(directory, text)
            second = write_selection(directory, text + 'second')
            self.assertNotEqual(first['path'], second['path'])
            self.assertEqual(Path(first['path']).parent, Path(directory).resolve() / '.umeko')
            self.assertEqual(Path(first['path']).read_text(encoding='utf-8'), text)
            self.assertEqual(Path(second['path']).read_text(encoding='utf-8'), text + 'second')
            self.assertTrue(first['name'].startswith('中文𠮷 quoted text'))
            self.assertTrue(second['name'].endswith(' (2).md'))
            for text in ('../../danger:<name>?*|"', 'CON', 'nul.txt', '...'):
                item = write_selection(directory, text)
                self.assertEqual(Path(item['path']).parent, Path(first['path']).parent)
                self.assertNotRegex(item['name'], r'[<>:"/\\|?*]')
                self.assertEqual(Path(item['path']).read_text(encoding='utf-8'), text)

    def test_empty_selection_and_unusable_project(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(write_selection(directory, ' \n\t'))
            self.assertFalse((Path(directory) / '.umeko').exists())
            with self.assertRaises(OSError):
                write_selection(Path(directory) / 'missing', 'text')
            (Path(directory) / '.umeko').write_text('existing project file')
            with self.assertRaises(OSError):
                write_selection(directory, 'text')
            self.assertEqual((Path(directory) / '.umeko').read_text(), 'existing project file')
