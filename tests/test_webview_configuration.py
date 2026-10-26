"""Validate Windows frontend dependencies before reporting browser availability."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import webview


class WebViewConfigurationTests(unittest.TestCase):
    def test_missing_qml_module_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(webview.sys, 'platform', 'win32'), patch.object(webview, '_configuration', {}), patch.object(webview.ctypes, 'CDLL') as library:
            webview.configure(Path(temporary))
            self.assertFalse(webview.configuration()['available'])
            self.assertIn('qmldir', webview.configuration()['error'])
            library.assert_not_called()

    def test_windows_preloads_both_frontend_dlls_in_source_and_frozen_layouts(self):
        for frozen in (False, True):
            with self.subTest(frozen=frozen), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                support = root / ('webview-support' if frozen else 'build/webview-support')
                (support / 'qml/QtWebView').mkdir(parents=True)
                (support / 'qml/QtWebView/qmldir').write_text('module QtWebView')
                (support / 'bin').mkdir()
                with patch.object(webview.sys, 'platform', 'win32'), patch.object(webview.sys, 'frozen', frozen, create=True), patch.object(webview, '_configuration', {}), patch.object(webview, '_libraries', []), patch.object(webview.os, 'add_dll_directory', create=True), patch.object(webview.ctypes, 'CDLL') as library:
                    webview.configure(root)
                    self.assertTrue(webview.configuration()['available'])
                    self.assertEqual([Path(c.args[0]).name for c in library.call_args_list], ['Qt6WebView.dll', 'Qt6WebViewQuick.dll'])


if __name__ == '__main__':
    unittest.main()
