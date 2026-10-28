import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.document_preview import DocumentPreview, read_preview
from app.static_preview import HTML_LIMIT, StaticPreview


class StaticPreviewTests(unittest.TestCase):
    def test_relative_assets_traversal_hidden_files_size_and_revocation(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            root = directory / "site"
            root.mkdir()
            (root / "index.html").write_text('<link rel="stylesheet" href="style.css"><h1>Preview</h1>')
            (root / "style.css").write_text('h1{color:green}')
            (root / ".env").write_text('not-public')
            (directory / "outside.txt").write_text('outside')
            with (root / "large.html").open('wb') as stream:
                stream.truncate(HTML_LIMIT + 1)
            preview = StaticPreview()
            try:
                url = preview.open(root / "index.html")
                with urllib.request.urlopen(url) as response:
                    self.assertIn(b'<h1>Preview</h1>', response.read())
                    self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')
                prefix = url.rsplit('/', 1)[0]
                with urllib.request.urlopen(prefix + '/style.css') as response:
                    self.assertIn(b'green', response.read())
                for path, status in [('/.env', 404), ('/%2e%2e/outside.txt', 404), ('/large.html', 413), ('/missing.js', 404)]:
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(prefix + path)
                    self.assertEqual(error.exception.code, status)
                preview.revoke()
                with self.assertRaises(urllib.error.HTTPError):
                    urllib.request.urlopen(url)
            finally:
                preview.close()

    def test_preferences_are_global_per_type_and_survive_new_reader(self):
        saved = SimpleNamespace(data={'ui': {}}, save=Mock())
        reader = DocumentPreview(store=saved)
        with tempfile.TemporaryDirectory() as temporary:
            markdown = Path(temporary) / 'one.md'
            markdown.write_text('# Heading\n\n**Bold**')
            html = Path(temporary) / 'index.html'
            html.write_text('<h1>Hello</h1>')
            reader._state = read_preview(str(markdown))
            reader._presentation()
            self.assertEqual(reader.state['mode'], 'rendered')
            reader.setMode('markdown', 'source')
            self.assertEqual(reader.state['mode'], 'source')
            reader.setMode('html', 'source')
            self.assertEqual(saved.data['ui']['documentPreviewModes'], {'markdown': 'source', 'html': 'source'})
            other = DocumentPreview(store=saved)
            other._state = read_preview(str(html))
            with patch('app.webview.configuration', return_value={'available': True}):
                other._presentation()
                self.assertEqual(other.state['fileType'], 'html')
                self.assertEqual(other.state['mode'], 'source')
                other.setMode('html', 'rendered')
                self.assertTrue(other.state['previewUrl'].startswith('http://127.0.0.1:'))
                self.assertEqual(saved.data['ui']['documentPreviewModes']['markdown'], 'source')
                other.close()
            reader.close()

    def test_large_html_falls_back_without_overwriting_preference(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'large.html'
            with path.open('wb') as stream:
                stream.write(b'<div>Large</div>' * 20000)
                stream.truncate(HTML_LIMIT + 1)
            reader = DocumentPreview()
            reader._state = read_preview(str(path))
            with patch('app.webview.configuration', return_value={'available': True}):
                reader.setMode('html', 'rendered')
                self.assertEqual(reader.state['mode'], 'source')
                self.assertEqual(reader._modes['html'], 'rendered')
                self.assertFalse(reader.state['renderable'])
                self.assertIsNone(reader._static)
            reader.close()
