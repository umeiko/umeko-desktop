import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.controller import Controller
from app.selection_quote import QUOTE_MAX_CHARS, QuoteTooLong, append_quote, quote_block


class SelectionQuoteTests(unittest.TestCase):
    def test_quote_preserves_text_and_existing_draft(self):
        self.assertEqual(append_quote('', 'hello'), '> hello\n\n')
        self.assertEqual(append_quote('question', 'a\nb'), 'question\n\n> a\n> b\n\n')
        self.assertEqual(append_quote('question\n\n', 'line'), 'question\n\n> line\n\n')
        self.assertEqual(append_quote('  ', 'line'), '> line\n\n')

    def test_blank_lines_and_line_endings(self):
        self.assertEqual(quote_block('first\r\n\r\nsecond\rold'), '> first\n>\n> second\n> old')
        self.assertEqual(quote_block('a\n\n\na'), '> a\n>\n>\n> a')
        self.assertEqual(quote_block('  \n'), '')
        self.assertEqual(append_quote('draft', ' \n\t'), 'draft')

    def test_markdown_shape_is_quoted_not_interpreted(self):
        self.assertEqual(quote_block('```python\nprint("x")\n```'), '> ```python\n> print("x")\n> ```')
        self.assertEqual(quote_block('already > nested'), '> already > nested')

    def test_limit_keeps_the_draft_untouched(self):
        with self.assertRaises(QuoteTooLong):
            append_quote('keep', 'x' * (QUOTE_MAX_CHARS + 1))

    def test_controller_inserts_or_reports_a_long_selection(self):
        fake = Mock()
        fake._view = SimpleNamespace(draft='question')
        self.assertTrue(Controller._insert_chat_quote(fake, 'line'))
        self.assertEqual(fake._view.draft, 'question\n\n> line\n\n')
        fake.editorText.emit.assert_called_once_with('question\n\n> line\n\n')
        fake.toast.emit.assert_not_called()
        fake._view.draft = 'keep'
        self.assertFalse(Controller._insert_chat_quote(fake, 'x' * (QUOTE_MAX_CHARS + 1)))
        self.assertEqual(fake._view.draft, 'keep')
        fake.toast.emit.assert_called_once_with('所选内容过长，请改用“附加到聊天”')


if __name__ == '__main__':
    unittest.main()
