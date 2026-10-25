"""Exercise frontend staging from a fresh, verified wheel without network access."""
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('webview_package', Path(__file__).resolve().parents[1] / 'scripts/webview_package.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class WebViewPackagingTests(unittest.TestCase):
    def fixture(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as stream:
            stream.writestr('PySide6/Qt/qml/QtWebView/qmldir', 'module QtWebView')
            stream.writestr('PySide6/Qt/resources/qtwebengine_resources.pak', 'Excluded engine')
        raw = output.getvalue()
        platform = 'win_amd64' if sys.platform == 'win32' else 'macosx_' if sys.platform == 'darwin' else 'manylinux_2_34_x86_64'
        metadata = {'urls': [{'filename': 'PySide6_Addons-' + platform + '.whl', 'url': 'https://fixture.invalid/wheel', 'digests': {'sha256': hashlib.sha256(raw).hexdigest()}}]}
        return metadata, raw

    def test_clean_wheel_staging_cache_reuse_and_corruption_repair(self):
        metadata, raw = self.fixture()
        def response(url, **kwargs):
            return io.BytesIO(raw if url.endswith('/wheel') else json.dumps(metadata).encode())
        with tempfile.TemporaryDirectory() as temporary, patch.object(package.urllib.request, 'urlopen', side_effect=response) as fetch:
            output = Path(temporary) / 'frontend'
            package.stage_frontend(output)
            frontend = output / 'qml/QtWebView/qmldir'
            marker = output / 'frontend-manifest.json'
            self.assertEqual(frontend.read_text(), 'module QtWebView')
            self.assertEqual(json.loads(marker.read_text())['files'], {'qml/QtWebView/qmldir': package.digest(frontend)})
            self.assertFalse((output / 'resources/qtwebengine_resources.pak').exists())
            self.assertEqual(fetch.call_count, 2)
            package.stage_frontend(output)
            self.assertEqual(fetch.call_count, 2)
            frontend.write_text('corrupted')
            package.stage_frontend(output)
            self.assertEqual(frontend.read_text(), 'module QtWebView')
            self.assertEqual(fetch.call_count, 4)

    def test_rejects_wheel_checksum_mismatch_before_extracting(self):
        metadata, raw = self.fixture()
        metadata['urls'][0]['digests']['sha256'] = '0' * 64
        def response(url, **kwargs):
            return io.BytesIO(raw if url.endswith('/wheel') else json.dumps(metadata).encode())
        with tempfile.TemporaryDirectory() as temporary, patch.object(package.urllib.request, 'urlopen', side_effect=response):
            output = Path(temporary) / 'frontend'
            with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                package.stage_frontend(output)
            self.assertFalse((output / 'frontend-manifest.json').exists())
            self.assertFalse((output / 'qml/QtWebView/qmldir').exists())


if __name__ == '__main__':
    unittest.main()
