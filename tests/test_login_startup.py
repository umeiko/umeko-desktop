"""Login registration tests use a fake registry or temporary user directories.

The sole real-registry test is restricted to Windows GitHub Actions and uses
an ephemeral, unique value name. It never touches the user's Umeko value.
"""

import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

from app.login_startup import LoginStartup, RUN_KEY


class FakeRegistry:
    HKEY_CURRENT_USER = "HKCU"
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self):
        self.values = {}
        self.writes = []

    def OpenKey(self, root, path, reserved=0, access=0):
        assert root == self.HKEY_CURRENT_USER and path == RUN_KEY
        return self

    CreateKeyEx = OpenKey

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name]

    def SetValueEx(self, key, name, reserved, kind, value):
        self.values[name] = value, kind
        self.writes.append((name, value))

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]
        self.writes.append((name, None))


class WindowsLoginStartupTests(unittest.TestCase):
    def setUp(self):
        self.registry = FakeRegistry()
        self.login = LoginStartup(platform="win32", executable=r"C:\Program Files\Umeko\Umeko.exe",
                                  frozen=True, registry=self.registry, environ={})

    def assert_flags(self, state, umeko, proxy):
        self.assertEqual(state, {"available": True, "reason": "", "umeko": umeko, "proxy": proxy})

    def test_single_registration_keeps_each_flag_independent(self):
        self.assert_flags(self.login.state(), False, False)
        self.assert_flags(self.login.set_enabled(True, True), True, True)
        self.assertEqual(set(self.registry.values), {"Umeko"})
        self.assertEqual(self.registry.values["Umeko"][0],
                         '"C:\\Program Files\\Umeko\\Umeko.exe" --login-startup --login-umeko --login-proxy')
        self.assert_flags(self.login.set_enabled(False, True), False, True)
        self.assert_flags(self.login.set_enabled(True, False), True, False)
        self.assert_flags(self.login.set_enabled(False, False), False, False)
        self.assertEqual(self.registry.values, {})
        self.login.set_enabled(False, False)  # Removing an absent value is harmless.

    def test_state_reads_external_changes_instead_of_cached_preferences(self):
        self.login.set_enabled(True, True)
        self.registry.values["Umeko"] = ('"C:\\Old App\\umeko.exe" --login-startup --login-proxy', 1)
        self.assert_flags(self.login.state(), False, True)
        del self.registry.values["Umeko"]
        self.assert_flags(self.login.state(), False, False)

    def test_moved_executable_refresh_preserves_registered_flags(self):
        self.registry.values["Umeko"] = ('"C:\\Old App\\umeko.exe" --login-startup --login-proxy', 1)
        self.assert_flags(self.login.refresh(), False, True)
        self.assertEqual(self.registry.values["Umeko"][0],
                         subprocess.list2cmdline([self.login.executable, "--login-startup", "--login-proxy"]))

    def test_escaping_quotes_spaces_percent_and_backslashes(self):
        self.login.executable = 'C:\\Apps %name%\\quoted "test"\\umeko.exe'
        self.assert_flags(self.login.set_enabled(True, True), True, True)
        self.assertEqual(self.registry.values["Umeko"][1], self.registry.REG_SZ)
        self.assertIn("%name%", self.registry.values["Umeko"][0])

    def test_missing_or_malformed_registration_is_off_and_not_refreshed(self):
        commands = ['"unterminated --login-startup --login-umeko',
                    '"C:\\App\\Umeko.exe" --login-umeko',
                    '"C:\\App\\Umeko.exe" --login-startup',
                    '"C:\\App\\Umeko.exe" --login-startup --login-umeko --unknown',
                    '"C:\\App\\Umeko.exe" --login-startup --login-proxy --login-proxy',
                    'relative.exe --login-startup --login-proxy']
        for command in commands:
            with self.subTest(command=command):
                self.registry.values["Umeko"] = command, 1
                self.assert_flags(self.login.refresh(), False, False)
        self.assertEqual(self.registry.writes, [])

    def test_source_run_never_changes_existing_registration(self):
        self.registry.values["Umeko"] = ('"C:\\Old\\Umeko.exe" --login-startup --login-umeko', 1)
        self.login.frozen = False
        self.assertFalse(self.login.set_enabled(False, False)["available"])
        self.assertFalse(self.login.refresh()["available"])
        self.assertEqual(self.registry.writes, [])
        self.assertIn("Umeko", self.registry.values)

    def test_permission_errors_are_not_reported_as_disabled(self):
        with patch.object(self.registry, "OpenKey", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                self.login.state()
        with patch.object(self.registry, "SetValueEx", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                self.login.set_enabled(True, False)


class FileLoginStartupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)

    def manager(self, platform, executable=None, **kwargs):
        return LoginStartup(platform=platform, executable=executable or "/opt/Umeko App/umeko",
                            frozen=True, home=self.home, environ=kwargs.pop("environ", {}), **kwargs)

    def test_linux_one_desktop_entry_all_flag_combinations_and_xdg_location(self):
        config = self.home / "custom-config"
        login = self.manager("linux", environ={"XDG_CONFIG_HOME": str(config)})
        entry = config / "autostart/umeko.desktop"
        self.assertFalse(login.state()["umeko"])
        for umeko, proxy in ((True, True), (False, True), (True, False), (False, False)):
            with self.subTest(umeko=umeko, proxy=proxy):
                state = login.set_enabled(umeko, proxy)
                self.assertEqual((state["umeko"], state["proxy"]), (umeko, proxy))
                self.assertEqual(entry.exists(), umeko or proxy)
                self.assertEqual(list(entry.parent.glob("*.desktop")), [entry] if umeko or proxy else [])

    def test_linux_exec_escaping_and_refresh_of_appimage_path(self):
        old = self.manager("linux", executable='/opt/Old "App" 100%/Umeko\\ $`build.AppImage')
        old.set_enabled(False, True)
        path = self.home / ".config/autostart/umeko.desktop"
        text = path.read_text(encoding="utf-8")
        self.assertIn("100%%", text)
        self.assertIn('\\\\"App\\\\"', text)
        self.assertEqual((old.state()["umeko"], old.state()["proxy"]), (False, True))
        new = LoginStartup(platform="linux", frozen=True, executable=None, home=self.home,
                           environ={"APPIMAGE": "/new path/Umeko.AppImage"})
        new.refresh()
        self.assertIn('"/new path/Umeko.AppImage"', path.read_text(encoding="utf-8"))
        self.assertTrue(new.state()["proxy"])
        self.assertFalse(new.state()["umeko"])

    def test_linux_hidden_malformed_or_external_removal_is_off(self):
        login = self.manager("linux")
        login.set_enabled(True, True)
        path = self.home / ".config/autostart/umeko.desktop"
        original = path.read_text(encoding="utf-8")
        for text in (original.replace("Hidden=false", "Hidden=true"),
                     original.replace("Hidden=false", "X-GNOME-Autostart-enabled=false"),
                     original.replace("--login-proxy", "--unexpected"),
                     original.replace("/opt/Umeko App/umeko", "/opt/%U/umeko"),
                     "not a desktop entry"):
            path.write_text(text, encoding="utf-8")
            state = login.refresh()
            self.assertFalse(state["umeko"] or state["proxy"])
            self.assertEqual(path.read_text(encoding="utf-8"), text)
        path.unlink()
        self.assertFalse(login.state()["proxy"])

    def test_linux_relative_xdg_directory_uses_user_default(self):
        login = self.manager("linux", environ={"XDG_CONFIG_HOME": "relative-config"})
        login.set_enabled(True, False)
        self.assertTrue((self.home / ".config/autostart/umeko.desktop").exists())

    def test_macos_plist_flags_exact_argument_array_and_refresh(self):
        login = self.manager("darwin", executable='/Applications/Umeko "100%".app/Contents/MacOS/Umeko')
        path = self.home / "Library/LaunchAgents/Umeko.plist"
        login.set_enabled(True, True)
        data = plistlib.loads(path.read_bytes())
        self.assertEqual(data["ProgramArguments"],
                         [login.executable, "--login-startup", "--login-umeko", "--login-proxy"])
        self.assertTrue(data["RunAtLoad"])
        login.set_enabled(False, True)
        login.executable = "/Applications/New Umeko.app/Contents/MacOS/Umeko"
        login.refresh()
        self.assertEqual(plistlib.loads(path.read_bytes())["ProgramArguments"],
                         [login.executable, "--login-startup", "--login-proxy"])
        login.set_enabled(True, False)
        self.assertTrue(login.state()["umeko"])
        self.assertFalse(login.state()["proxy"])
        login.set_enabled(False, False)
        self.assertFalse(path.exists())

    def test_macos_disabled_or_malformed_item_does_not_enable_flags(self):
        login = self.manager("darwin")
        login.set_enabled(True, True)
        path = self.home / "Library/LaunchAgents/Umeko.plist"
        original = plistlib.loads(path.read_bytes())
        for change in ({"Disabled": True}, {"RunAtLoad": False}, {"ProgramArguments": "invalid"}):
            path.write_bytes(plistlib.dumps(dict(original, **change)))
            self.assertFalse(login.refresh()["umeko"])
            self.assertFalse(login.state()["proxy"])
        path.write_bytes(b"not a plist")
        self.assertFalse(login.state()["umeko"])

    def test_source_mode_never_creates_or_changes_files(self):
        for platform in ("linux", "darwin"):
            login = self.manager(platform)
            login.frozen = False
            self.assertFalse(login.set_enabled(True, True)["available"])
            self.assertFalse(login.refresh()["available"])
        self.assertEqual(list(self.home.iterdir()), [])

    def test_inherited_appimage_does_not_enable_a_source_run(self):
        with patch.object(sys, "frozen", False, create=True):
            login = LoginStartup(platform="linux", home=self.home,
                                 environ={"APPIMAGE": "/opt/Parent.AppImage"})
            self.assertFalse(login.set_enabled(True, True)["available"])
            self.assertFalse(login.refresh()["available"])
        self.assertEqual(list(self.home.iterdir()), [])

    def test_unsupported_platform_is_unavailable(self):
        login = self.manager("freebsd")
        self.assertFalse(login.set_enabled(True, True)["available"])
        self.assertEqual(login.state()["reason"], "当前系统不支持开机启动。")
        self.assertEqual(list(self.home.iterdir()), [])


@unittest.skipUnless(os.name == "nt" and os.environ.get("GITHUB_ACTIONS") == "true",
                     "Real registry roundtrip runs only on Windows GitHub Actions")
class WindowsCIRegistryTests(unittest.TestCase):
    def test_unique_disposable_run_value_roundtrip(self):
        name = "Umeko-CI-login-test-" + uuid.uuid4().hex
        login = LoginStartup(platform="win32", executable=sys.executable, frozen=True,
                             value_name=name, environ={})
        try:
            self.assertEqual(login.set_enabled(True, True)["proxy"], True)
            self.assertEqual(login.set_enabled(False, True)["umeko"], False)
            self.assertEqual(login.state()["proxy"], True)
        finally:
            login.set_enabled(False, False)
        self.assertFalse(login.state()["umeko"] or login.state()["proxy"])


if __name__ == "__main__":
    unittest.main()
