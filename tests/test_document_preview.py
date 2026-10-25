import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QTest
from app.document_preview import DocumentPreview, read_preview, document_kind


class DocumentPreviewTests(unittest.TestCase):
    def test_large_sparse_files_long_lines_and_line_counts_are_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'huge.py'
            with path.open('wb') as stream:
                stream.write(b'x' * 270000)
                stream.truncate(512 * 1024 * 1024)
            result = read_preview(str(path))
            self.assertTrue(result['truncated'])
            self.assertLessEqual(len(result['text']), 48002)
            self.assertLessEqual(len(result['text'].splitlines()[0]), 2002)
            self.assertFalse(result['highlight'])
            path.write_text('line\n' * 2000)
            result = read_preview(str(path), 'text')
            self.assertTrue(result['truncated'])
            self.assertLess(len(result['text'].splitlines()), 1001)

    def test_utf16_empty_binary_missing_and_complex_markdown(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'notes.txt'
            path.write_text('中文\nhello', encoding='utf-16')
            self.assertEqual(read_preview(str(path))['text'], '中文\nhello')
            path.write_bytes(b'')
            self.assertEqual(read_preview(str(path))['text'], '')
            path.write_bytes(b'a\0b')
            self.assertIn('error', read_preview(str(path)))
            path.unlink()
            self.assertIn('error', read_preview(str(path)))
            path = path.with_suffix('.md');path.write_text('|' * 15000)
            result = read_preview(str(path))
            self.assertTrue(result['simple']);self.assertEqual(result['html'], '')
            self.assertEqual(document_kind('CMakeLists.txt'), 'code')
            self.assertEqual(document_kind('/tmp/a.pdf', 'file'), '')
            self.assertEqual(document_kind('/tmp/a', 'text'), 'text')

    def test_one_reader_latest_request_and_cancellation_keep_ui_responsive(self):
        app = QCoreApplication.instance() or QCoreApplication([])
        entered, release = threading.Event(), threading.Event()
        calls = []
        def read(path, kind):
            calls.append(path)
            if path == 'slow': entered.set();release.wait(5)
            return {'path': path, 'text': path, 'busy': False}
        reader = DocumentPreview()
        with patch('app.document_preview.read_preview', side_effect=read):
            reader.load('slow', 'text');self.assertTrue(entered.wait(1))
            for index in range(50):reader.load(str(index), 'text')
            self.assertEqual(calls, ['slow'])
            ticks = []
            from PySide6.QtCore import QTimer
            timer = QTimer();timer.timeout.connect(lambda:ticks.append(1));timer.start(5)
            QTest.qWait(40);timer.stop();self.assertTrue(ticks)
            release.set()
            for _ in range(100):
                QTest.qWait(10)
                if reader.state.get('path') == '49' and not reader.state.get('busy'):break
            self.assertEqual(calls, ['slow', '49'])
            reader.cancel();QTest.qWait(30);self.assertEqual(reader.state, {})
