import ctypes
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from app import cli_path


class CliPathTests(unittest.TestCase):
    def test_bash_login_and_interactive_config_preserve_user_content(self):
        with TemporaryDirectory() as directory:
            home = Path(directory)
            rc, login = home / ".bashrc", home / ".bash_login"
            rc.write_bytes(b"# keep bash settings")
            login.write_bytes(b"# keep login settings\n")
            old = home / "First app" / "umeko"
            new = home / "Umeko's new home" / "umeko"
            with patch.object(cli_path.sys, "platform", "linux"), patch.object(Path, "home", return_value=home), \
                    patch.dict(os.environ, SHELL="/bin/bash"):
                cli_path.configure_path(old)
                first = rc.read_bytes()
                cli_path.configure_path(old)
                self.assertEqual(rc.read_bytes(), first)
                cli_path.configure_path(new)
            self.assertFalse((home / ".bash_profile").exists())
            self.assertFalse((home / ".profile").exists())
            for path, prefix in ((rc, b"# keep bash settings\n"), (login, b"# keep login settings\n")):
                data = path.read_bytes()
                self.assertTrue(data.startswith(prefix))
                self.assertEqual(data.count(b"# >>> Umeko CLI PATH >>>"), 1)
                self.assertIn(b"Umeko", data)
                self.assertIn(b"new home", data)
                self.assertNotIn(b"First app", data)

    def test_zsh_and_fish_honor_config_locations(self):
        with TemporaryDirectory() as directory:
            home = Path(directory)
            launcher = home / "Umeko's app" / "umeko"
            zsh, fish = home / "zsh", home / "fish-config"
            environment = {"ZDOTDIR": str(zsh), "XDG_CONFIG_HOME": str(fish)}
            with patch.object(cli_path.sys, "platform", "darwin"), patch.object(Path, "home", return_value=home):
                for shell in ("/bin/zsh", "/opt/bin/fish"):
                    with patch.dict(os.environ, environment | {"SHELL": shell}):
                        cli_path.configure_path(launcher)
            self.assertIn("export PATH=", (zsh / ".zshrc").read_text(encoding="utf-8"))
            self.assertIn("set -gx PATH", (fish / "fish/conf.d/umeko-cli-path.fish").read_text(encoding="utf-8"))
            self.assertFalse((home / ".zshrc").exists())

    def test_windows_user_path_preserves_value_type_and_other_entries(self):
        registry = MagicMock()
        registry.REG_EXPAND_SZ, registry.REG_SZ = 2, 1
        prior = r'%SystemRoot%\Tools;C:\Other;C:\APPS\UMEKO\;c:\apps\umeko'
        updated = r'C:\APPS\UMEKO\;%SystemRoot%\Tools;C:\Other'
        registry.QueryValueEx.side_effect = [(prior, registry.REG_EXPAND_SZ), (updated, registry.REG_EXPAND_SZ)]
        registry.ExpandEnvironmentStrings.side_effect = lambda value: value.replace("%SystemRoot%", r"C:\Windows")
        with patch.dict(sys.modules, winreg=registry), patch.object(ctypes, "WinDLL", create=True) as dll:
            cli_path._configure_windows(r"C:\Apps\Umeko")
            cli_path._configure_windows(r"C:\Apps\Umeko")
        registry.CreateKeyEx.assert_called_with(registry.HKEY_CURRENT_USER, "Environment", 0,
                                                registry.KEY_QUERY_VALUE | registry.KEY_SET_VALUE)
        registry.SetValueEx.assert_called_once_with(registry.CreateKeyEx.return_value.__enter__.return_value,
                                                   "Path", 0, registry.REG_EXPAND_SZ, updated)
        dll.return_value.SendMessageTimeoutW.assert_called_once()


if __name__ == "__main__":
    unittest.main()
