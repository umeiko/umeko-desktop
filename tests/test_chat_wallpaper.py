from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtGui import QImage, QImageReader
from PySide6.QtTest import QTest

from app.chat_wallpaper import ChatWallpaper
from app.storage import Store


class ChatWallpaperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        self.profile = self.directory / 'profile'
        self.store = Store(self.profile)
        self.wallpaper = ChatWallpaper(self.store, None)
        self.addCleanup(self.wallpaper.close)
        self.picture = self.directory / '风景 #1.png'
        image = QImage(4000, 800, QImage.Format_ARGB32)
        image.fill(0xC05C91AB)
        self.assertTrue(image.save(str(self.picture)))

    def finish_import(self):
        for _ in range(500):
            if not self.wallpaper.draft['busy']:
                return
            QTest.qWait(10)
        self.fail('wallpaper import did not finish')

    def choose(self, path):
        self.wallpaper.chooseImage(QUrl.fromLocalFile(str(path)))
        self.finish_import()

    def apply_options(self, mode, opacity, zoom):
        return self.wallpaper.apply(False, {'mode': mode, 'opacity': opacity, 'zoom': zoom})

    def test_applied_copy_survives_restart_and_can_be_removed(self):
        self.assertFalse(self.wallpaper.settings['source'])
        self.choose(self.picture)
        self.assertFalse(self.wallpaper.settings['source'])
        self.assertTrue(self.wallpaper.apply(False, {
            'mode': 'fit', 'opacity': 27, 'zoom': 140, 'offsetX': -0.2536, 'offsetY': 0.1358, 'angle': 372.5,
        }))
        applied = QUrl(self.wallpaper.settings['source']).toLocalFile()
        self.assertEqual(Path(applied).parent, self.profile / 'chat-wallpaper')
        self.assertEqual(QImageReader(applied).size().width(), 3072)
        self.picture.unlink()

        reopened = ChatWallpaper(Store(self.profile), None)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.settings, self.wallpaper.settings)
        self.assertEqual((reopened.settings['mode'], reopened.settings['opacity'], reopened.settings['zoom']), ('fit', 27, 140))
        self.assertEqual((reopened.settings['offsetX'], reopened.settings['offsetY'], reopened.settings['angle']), (-0.2536, 0.1358, 12.5))
        self.assertTrue(reopened.apply(True, reopened.defaults))
        self.assertFalse(reopened.settings['source'])
        self.assertFalse(Path(applied).exists())

    def test_failed_replacement_preserves_saved_wallpaper_and_preview(self):
        self.choose(self.picture)
        self.assertTrue(self.apply_options('fill', 24, 100))
        saved = self.wallpaper.settings
        self.choose(self.picture)
        candidate = self.wallpaper.draft['source']

        broken = self.directory / 'broken.jpg'
        broken.write_bytes(b'not an image')
        self.choose(broken)
        self.assertTrue(self.wallpaper.draft['error'])
        self.assertEqual(self.wallpaper.draft['source'], candidate)
        self.assertEqual(self.wallpaper.settings, saved)

        with patch.object(self.store, 'save', side_effect=OSError('test disk error')):
            self.assertFalse(self.apply_options('fill', 20, 160))
        self.assertEqual(self.wallpaper.settings, saved)
        self.assertTrue(Path(QUrl(candidate).toLocalFile()).is_file())
        self.assertTrue(self.apply_options('fill', 20, 160))
        self.assertFalse(Path(QUrl(saved['source']).toLocalFile()).exists())

    def test_cancel_during_import_does_not_save_or_keep_a_draft(self):
        self.wallpaper.chooseImage(QUrl.fromLocalFile(str(self.picture)))
        self.wallpaper.discard()
        self.finish_import()
        self.assertFalse(self.wallpaper.settings['source'])
        self.assertFalse(self.wallpaper.draft['source'])
        self.assertFalse(list((self.profile / 'chat-wallpaper').glob('*')))

    def test_default_image_adjustments_are_saved_without_an_import(self):
        self.assertIsNone(self.wallpaper.settings['opacity'])
        self.assertTrue(self.apply_options('fit', 9.5, 115))
        reopened = ChatWallpaper(Store(self.profile), None)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.settings, {**reopened.defaults, 'mode': 'fit', 'opacity': 9.5, 'zoom': 115, 'source': '', 'name': ''})
        self.assertTrue(reopened.apply(True, reopened.defaults))
        self.assertIsNone(reopened.settings['opacity'])
