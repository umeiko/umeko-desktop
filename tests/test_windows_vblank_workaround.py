import unittest

from app.platform_support import configure_windows_vblank_workaround


class WindowsVblankWorkaroundTests(unittest.TestCase):
    def test_windows_sets_qt_variable(self):
        environment = {}

        configure_windows_vblank_workaround("win32", environment)

        self.assertEqual(environment, {"QT_D3D_NO_VBLANK_THREAD": "1"})

    def test_other_platforms_leave_environment_unchanged(self):
        for platform in ("linux", "darwin"):
            with self.subTest(platform=platform):
                environment = {}

                configure_windows_vblank_workaround(platform, environment)

                self.assertEqual(environment, {})

    def test_existing_value_wins(self):
        for value in ("0", "1", ""):
            with self.subTest(value=value):
                environment = {"QT_D3D_NO_VBLANK_THREAD": value}

                configure_windows_vblank_workaround("win32", environment)

                self.assertEqual(environment, {"QT_D3D_NO_VBLANK_THREAD": value})
