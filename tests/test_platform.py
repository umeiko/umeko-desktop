import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from app.platform_support import configure_input_method, data_directory, legacy_data_directory
from app.storage import keyring_protect


class PlatformTests(unittest.TestCase):
    def test_platform_data_locations(self):
        home = Path("/users/example")
        for system in ('win32', 'darwin', 'linux'):
            self.assertEqual(data_directory(system, {}, home), home / '.umeko/desktop')
        self.assertEqual(legacy_data_directory("darwin", {}, home), home / "Library/Application Support/Umeko")
        self.assertEqual(legacy_data_directory("linux", {}, home), home / ".local/share/umeko")
        self.assertEqual(legacy_data_directory("linux", {"XDG_DATA_HOME": "/custom"}, home), Path("/custom/umeko"))
        self.assertEqual(legacy_data_directory("win32", {"LOCALAPPDATA": "/local"}, home), Path("/local/Umeko"))

    def test_fcitx_uses_only_compatible_bundled_plugins_and_preserves_overrides(self):
        with tempfile.TemporaryDirectory() as temp:
            plugins = Path(temp)
            (plugins / "libibusplatforminputcontextplugin.so").touch()
            env = {"QT_IM_MODULE": "fcitx", "XMODIFIERS": "@im=fcitx"}
            configure_input_method("linux", env, plugins)
            self.assertEqual(env["QT_IM_MODULE"], "ibus")
            (plugins / "libfcitx5platforminputcontextplugin.so").touch()
            env = {"XMODIFIERS": "@im=fcitx"}
            configure_input_method("linux", env, plugins)
            self.assertEqual(env["QT_IM_MODULE"], "fcitx")
            for module in ("ibus", "", "wayland"):
                env = {"QT_IM_MODULE": "fcitx", "UMEKO_QT_IM_MODULE": module}
                configure_input_method("linux", env, plugins)
                self.assertEqual(env["QT_IM_MODULE"], module)
            env = {"WAYLAND_DISPLAY": "wayland-0"}
            configure_input_method("linux", env, plugins)
            self.assertNotIn("QT_IM_MODULE", env)
            env = {"QT_IM_MODULE": "other"}
            configure_input_method("linux", env, plugins)
            self.assertEqual(env["QT_IM_MODULE"], "other")

    def test_keyring_reuses_field_account_and_never_serializes_secret(self):
        class Backend:
            priority = 1
            def __init__(self): self.values = {}
            def set_password(self, service, account, secret): self.values[(service, account)] = secret
            def get_password(self, service, account): return self.values.get((service, account))
        Backend.__module__ = "keyring.backends.SecretService"
        backend = Backend()
        with patch.dict("sys.modules", {"keyring": types.SimpleNamespace(get_keyring=lambda: backend)}):
            first = keyring_protect("first-secret", account="fixture:provider")
            second = keyring_protect("second-secret", account="fixture:provider")
            self.assertEqual(first, second)
            self.assertNotIn("secret", second)
            self.assertEqual(keyring_protect(second, True), "second-secret")
            self.assertEqual(len(backend.values), 1)
            with self.assertRaises(RuntimeError): keyring_protect("copied-windows-blob", True)
            with self.assertRaises(RuntimeError): keyring_protect("keyring:missing", True)
            Backend.__module__ = "keyrings.alt.file"
            with self.assertRaises(RuntimeError): keyring_protect("secret", account="fixture")
