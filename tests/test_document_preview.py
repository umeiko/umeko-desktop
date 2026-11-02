import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QTest
from app.document_preview import DocumentPreview, read_preview, document_kind
from app.document_blocks import source_blocks, parse_markdown


class DocumentPreviewTests(unittest.TestCase):
    def test_large_markdown_retains_entire_table_code_and_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'large.md'
            text = '# 大文档\n\n| Header | Value |\n| --- | --- |\n'
            text += ''.join(f'| row-{i} | **value** |\n' for i in range(5000))
            code = 'println!("测试𠮷");\n' * 5000
            text += '\n```rust\n' + code + '```\n\nEND-OF-DOCUMENT\n'
            path.write_text(text, encoding='utf-8')
            result = read_preview(str(path))
            self.assertTrue(result['chunked']);self.assertFalse(result['truncated'])
            self.assertEqual(result['text'], text)
            self.assertEqual(''.join(b['text'] for b in result['_source']), text)
            self.assertEqual(''.join(b['text'] for b in result['_blocks'] if b['kind']=='code'), code.rstrip())
            html=''.join(b['html'] for b in result['_blocks'])
            self.assertIn('row-4999', html);self.assertIn('END-OF-DOCUMENT', html)
            self.assertGreater(html.count('<th>Header</th>'), 100)

    def test_chunk_boundaries_and_parser_cancellation(self):
        text = ('🙂\n' * 301) + ('x' * 50000)
        blocks = list(source_blocks(text))
        self.assertEqual(''.join(b['text'] for b in blocks), text)
        self.assertTrue(all(len(b['text'])<=8192 and b['text'].count('\n')<=80 for b in blocks))
        with self.assertRaises(InterruptedError):parse_markdown('x' * 100000, cancelled=lambda:True)

    def test_packaged_parser_and_failure_keep_source_accessible(self):
        with patch('app.document_blocks.Path.is_dir', return_value=False):
            self.assertIn('<strong>bold</strong>', parse_markdown('**bold**')[0]['html'])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'fallback.md';source='**paragraph**\n\n'*2000
            path.write_text(source,encoding='utf-8')
            with patch('app.document_preview.parse_markdown', side_effect=TimeoutError):
                result=read_preview(str(path))
            self.assertEqual(result['text'],source)
            self.assertEqual(''.join(b['text'] for b in result['_source']),source)
            self.assertFalse(result['truncated']);self.assertTrue(result['renderNote'])
            with patch('app.document_preview.MARKDOWN_LIMIT',4096):
                self.assertTrue(read_preview(str(path))['truncated'])

    def test_cache_reopens_without_parsing_and_invalidates_changed_files(self):
        app = QCoreApplication.instance() or QCoreApplication([])
        reader = DocumentPreview()
        def loaded():
            for _ in range(300):
                QTest.qWait(10);time.sleep(.001)
                if not reader.state.get('busy'):break
            self.assertNotIn('error', reader.state)
            self.assertFalse(reader.state.get('busy'))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'cached.md';path.write_text('# Title\n\nParagraph\n\n'*500,encoding='utf-8')
            with patch('app.document_preview.parse_markdown', wraps=parse_markdown) as parser:
                reader.load(str(path),'markdown');loaded()
                self.assertEqual(reader.state['text'], '')
                self.assertGreater(reader.blocks.rowCount(), 0)
                reader.setMode('markdown','source')
                self.assertEqual(''.join(b['text'] for b in reader.blocks.rows),path.read_text(encoding='utf-8'))
                reader.cancel();reader.load(str(path),'markdown');loaded()
                self.assertEqual(parser.call_count, 1)
                path.write_text(path.read_text(encoding='utf-8')+'\nChanged!\n',encoding='utf-8')
                reader.load(str(path),'markdown');loaded()
                self.assertEqual(parser.call_count, 2)
            reader.close()
            self.assertEqual(reader._cache_bytes,0)

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
            self.assertTrue(result['chunked']);self.assertFalse(result['truncated'])
            self.assertEqual(''.join(row['text'] for row in result['_source']), '|' * 15000)
            self.assertEqual(document_kind('CMakeLists.txt'), 'code')
            self.assertEqual(document_kind('/tmp/a.pdf', 'file'), '')
            self.assertEqual(document_kind('/tmp/a', 'text'), 'text')

    def test_one_reader_latest_request_and_cancellation_keep_ui_responsive(self):
        app = QCoreApplication.instance() or QCoreApplication([])
        entered, release = threading.Event(), threading.Event()
        calls = []
        def read(path, kind, **kwargs):
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
