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

    def test_windows_wheel_keeps_qml_metadata_and_plugin_directories(self):
        files = {
            'PySide6/Qt6WebView.dll': b'frontend',
            'PySide6/Qt6WebViewQuick.dll': b'quick',
            'PySide6/qml/QtWebView/qmldir': b'module QtWebView\nplugin qtwebviewquickplugin',
            'PySide6/qml/QtWebView/qtwebviewquickplugin.dll': b'qml plugin',
            'PySide6/qml/QtWebView/plugins.qmltypes': b'types',
            'PySide6/plugins/webview/qtwebview_webview2.dll': b'native backend',
            'PySide6/QtWebView.pyd': b'Python wrapper is not needed',
            'PySide6/Qt6WebEngineCore.dll': b'Excluded engine',
        }
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            for name, data in files.items(): archive.writestr(name, data)
        raw = stream.getvalue()
        metadata = {'urls': [{'filename':'PySide6_Addons-win_amd64.whl','url':'https://fixture.invalid/wheel','digests':{'sha256':hashlib.sha256(raw).hexdigest()}}]}
        def response(url, **kwargs): return io.BytesIO(raw if url.endswith('/wheel') else json.dumps(metadata).encode())
        with tempfile.TemporaryDirectory() as temporary, patch.object(package.sys, 'platform', 'win32'), patch.object(package.urllib.request, 'urlopen', side_effect=response):
            output = Path(temporary) / 'frontend'; output.mkdir()
            # An old manifest with valid hashes must be rebuilt as well.
            (output/'bin').mkdir(); (output/'bin/Qt6WebView.dll').write_bytes(b'old')
            (output/'frontend-manifest.json').write_text(json.dumps({'qt':package.QT,'platform':'win32','files':{'bin/Qt6WebView.dll':package.digest(output/'bin/Qt6WebView.dll')}}))
            package.stage_frontend(output)
            self.assertEqual((output/'qml/QtWebView/qmldir').read_bytes(), files['PySide6/qml/QtWebView/qmldir'])
            self.assertTrue((output/'qml/QtWebView/qtwebviewquickplugin.dll').is_file())
            self.assertTrue((output/'plugins/webview/qtwebview_webview2.dll').is_file())
            self.assertTrue((output/'bin/Qt6WebViewQuick.dll').is_file())
            self.assertFalse((output/'bin/qml').exists())
            self.assertFalse((output/'bin/plugins').exists())
            self.assertFalse((output/'bin/Qt6WebEngineCore.dll').exists())
            self.assertEqual(json.loads((output/'frontend-manifest.json').read_text())['layout'], package.FRONTEND_LAYOUT)


if __name__ == '__main__':
    unittest.main()
