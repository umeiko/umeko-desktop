from concurrent.futures import Future
import unittest
from unittest.mock import patch

from PySide6.QtCore import QObject, QCoreApplication

from app.syntax_highlight import (tokenize, eligible, language_name, HighlightService, Tokens,
                                  MAX_CHARS, MAX_LINES, MAX_LINE, MAX_PENDING, CACHE_BYTES, CACHE_ENTRIES)


class SyntaxTests(unittest.TestCase):
    def test_unicode_spans_use_qt_utf16_offsets_and_multiline_state(self):
        text = 'label = "中文𠮷"; count = 42\n"""multiple\nlines"""\n'
        result = tokenize(text, "python")
        start = len(text[:text.index("42")].encode("utf-16-le")) // 2
        self.assertIn((start, 2, "number"), result.lines[0])
        self.assertTrue(any(group == "string" for _, _, group in result.lines[2]))
        self.assertEqual(text, 'label = "中文𠮷"; count = 42\n"""multiple\nlines"""\n')

    def test_large_long_unknown_inputs_do_not_invoke_lexer(self):
        for text, language in (("a" * (MAX_CHARS + 1), "python"), ("a\n" * MAX_LINES, "python"),
                               ("a" * (MAX_LINE + 1), "python"), ("def x(): pass", "unknown")):
            with patch("app.syntax_highlight.lexer_for") as lexer:
                self.assertFalse(eligible(text, language))
                self.assertEqual(tokenize(text, language).count, 0)
                lexer.assert_not_called()
        self.assertEqual(language_name("PyThOn3"), "python")
        self.assertEqual(language_name("c++"), "cpp")
        with patch("app.syntax_highlight.MAX_SPANS", 1):
            self.assertEqual(tokenize('def hello(): return "value"', "python").count, 0)

    def test_pending_work_is_bounded_deduplicated_and_cache_is_bounded(self):
        app = QCoreApplication.instance() or QCoreApplication([])
        class Target(QObject):
            def __init__(self): super().__init__(); self.received = []
            def accept(self, generation, tokens): self.received.append((generation, tokens))
        target, worker = Target(), HighlightService()
        futures = []
        def submit(*_):
            future = Future(); futures.append(future); return future
        try:
            with patch.object(worker.pool, "submit", side_effect=submit):
                for index in range(MAX_PENDING):
                    self.assertTrue(worker.request(target, index, str(index), "python"))
                self.assertFalse(worker.request(target, 99, "overflow", "python"))
                self.assertTrue(worker.request(target, 100, "0", "python"))
                self.assertEqual(len(futures), MAX_PENDING)
                result = Tokens({0: [(0, 1, "number")]}, 1, 128)
                futures[0].set_result(result)
                self.assertEqual([generation for generation, _ in target.received], [0, 100])
                self.assertTrue(worker.request(target, 101, "0", "python"))
                self.assertEqual(target.received[-1][0], 101)
                self.assertEqual(len(futures), MAX_PENDING)
            for index in range(CACHE_ENTRIES + 5):
                worker._deliver(("fixture", index), Tokens({}, 1, CACHE_BYTES // 3))
            self.assertLessEqual(worker.weight, CACHE_BYTES)
            self.assertLessEqual(len(worker.cache), CACHE_ENTRIES)
        finally:
            worker.close()
