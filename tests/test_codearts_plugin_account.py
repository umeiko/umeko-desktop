"""Focused fake-credential tests; executable fixtures run outside repository data."""

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import importlib.util
import types
from types import SimpleNamespace

PACKAGE = "_codearts_plugin_account_tests"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(Path(__file__).resolve().parents[1] / "provider_dev/plugins/codearts/scripts")]
sys.modules[PACKAGE] = package
account_module = __import__(PACKAGE + ".account", fromlist=["CodeartsAccount"])
CodeartsAccount = account_module.CodeartsAccount
INSTALLER_URL, SERVICE, parse_credentials = account_module.INSTALLER_URL, account_module.SERVICE, account_module.parse_credentials



AK = "FAKE_AK_ACCOUNT_TEST"
SK = "FAKE_SK_ACCOUNT_TEST"
CSV = f"Secret Access Key,Access Key Id\n{SK},{AK}\n"


class FakeVault:
    def __init__(self):
        self.values = {}
        self.fail = False

    def get(self, name, default=None):
        return self.values.get(name, default)

    def set(self, name, value):
        if self.fail:
            raise RuntimeError(SK)
        self.values[name] = value.copy() if isinstance(value, dict) else value


class FakeLegacy:
    def __init__(self, raw=None):
        self.raw = raw
        self.reads, self.deletes = [], []
        self.fail_delete = False

    def get_password(self, service, username):
        self.reads.append((service, username))
        return self.raw

    def delete_password(self, service, username):
        if self.fail_delete:
            raise RuntimeError(SK)
        self.deletes.append((service, username))
        self.raw = None


class AccountTests(unittest.TestCase):
    def setUp(self):
        root = Path("C:/UmekoTests") if os.name == "nt" else Path(tempfile.gettempdir()) / "UmekoTests"
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="codearts-account-", dir=root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.downloads = self.root / "Downloads"
        self.downloads.mkdir()
        self.profile = self.root / "profile"
        self.fixture = self.root / "fake_cli.py"
        self.fixture.write_text(
            "import os,sys\n"
            "ak=os.environ.get('CODEARTS_CLI_AK'); sk=os.environ.get('CODEARTS_CLI_SK')\n"
            "assert ak == 'FAKE_AK_ACCOUNT_TEST' and sk == 'FAKE_SK_ACCOUNT_TEST'\n"
            "assert 'HW_SECRET_KEY' not in os.environ\n"
            "if '--fail' in sys.argv:\n"
            " print(ak + ':' + sk); sys.exit(0)\n"
            "print('huaweicloud/fixture-model')\n"
            "print('huaweicloud/' + sk)\n",
            encoding="utf-8",
        )
        self.vault = FakeVault()
        self.calls = []
        self.progress = []
        self.fail = False

        def runner(command, *, env, cwd, timeout):
            self.calls.append((command, dict(env), cwd, timeout))
            return subprocess.run([sys.executable, str(self.fixture), *( ["--fail"] if self.fail else [])],
                                  env=env, cwd=cwd, timeout=timeout, stdin=subprocess.DEVNULL,
                                  capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

        self.legacy = FakeLegacy()
        self.context = SimpleNamespace(state_dir=self.profile, secrets=self.vault, language="zh", profile_dir=None)
        self.account = CodeartsAccount(self.context, self.downloads, self.legacy, runner, self.progress.append)
        self.account._find_cli = lambda: self.root / "codearts.cmd"
        self.addCleanup(self.account.close)

    def assert_safe(self, result):
        rendered = json.dumps([result, self.progress], ensure_ascii=False)
        self.assertNotIn(AK, rendered)
        self.assertNotIn(SK, rendered)

    def test_csv_headers_bom_order_and_two_value_paste(self):
        self.assertEqual(parse_credentials("\ufeff" + CSV), (AK, SK))
        self.assertEqual(parse_credentials(f"Access Key Id,Secret Access Key\n{AK},{SK}"), (AK, SK))
        self.assertEqual(parse_credentials(f"{AK}\n{SK}"), (AK, SK))
        self.assertEqual(parse_credentials(f"CODEARTS_CLI_SK={SK}\nCODEARTS_CLI_AK={AK}"), (AK, SK))
        self.assertEqual(parse_credentials(f"{AK}, {SK}"), (AK, SK))
        with self.assertRaises(ValueError):
            parse_credentials(CSV + f"{SK},{AK}\n")

    def test_download_ignores_preexisting_and_accepts_arbitrary_new_csv_filename(self):
        old = self.downloads / "older-access-key.csv"
        old.write_text(CSV, encoding="utf-8")
        self.account.start_import()
        self.assertIsNone(self.account.poll_downloads())
        new = self.downloads / "renamed-access-key.CSV"
        new.write_text("\ufeff" + CSV, encoding="utf-8")
        result = self.account.poll_downloads()
        self.assertTrue(result["ready"])
        self.assertEqual(result["models"], ["huaweicloud/fixture-model"])
        self.assertTrue(old.exists())
        self.assertFalse(new.exists())
        self.assertEqual(self.vault.values["account"], {"ak": AK, "sk": SK})
        self.assertIsNone(self.account.poll_downloads())
        self.assert_safe(result)

    def test_unrelated_csv_never_uses_two_value_paste_fallback(self):
        self.account.start_import()
        unrelated = self.downloads / "two-values.csv"
        unrelated.write_text("ordinary,value\n", encoding="utf-8")
        table = self.downloads / "sales.csv"
        table.write_text("name,quantity\nbook,2\n", encoding="utf-8")
        malformed = self.downloads / "incomplete.csv"
        malformed.write_text("Access Key Id,Secret Access Key\nonly-ak,\n", encoding="utf-8")
        self.assertIsNone(self.account.poll_downloads())
        self.assertFalse(self.calls)
        self.assertFalse(self.vault.values)
        for path in (unrelated, table, malformed):
            self.assertTrue(path.exists())
        with self.assertRaises(ValueError):
            parse_credentials("ordinary,value", csv_only=True)

    def test_verification_exit_zero_without_models_preserves_download(self):
        self.account.start_import()
        new = self.downloads / "credentials.csv"
        new.write_text(CSV, encoding="utf-8")
        self.fail = True
        result = self.account.poll_downloads()
        self.assertFalse(result["ready"])
        self.assertTrue(new.exists())
        self.assertFalse(self.vault.values)
        self.assert_safe(result)

    def test_vault_failure_preserves_download_after_verify(self):
        self.account.start_import()
        new = self.downloads / "credentials.csv"
        new.write_text(CSV, encoding="utf-8")
        self.vault.fail = True
        result = self.account.poll_downloads()
        self.assertFalse(result["ready"])
        self.assertTrue(new.exists())
        self.assert_safe(result)

    def test_paste_child_only_and_begin_uses_vault(self):
        before = dict(os.environ)
        with patch.dict(os.environ, {"HW_SECRET_KEY": "FAKE_OTHER_SECRET"}):
            result = self.account.import_text(f"{AK}\n{SK}")
        self.assertTrue(result["ready"])
        self.assertEqual(dict(os.environ), before)
        self.assertEqual(self.calls[0][1]["CODEARTS_CLI_AK"], AK)
        self.assertNotIn("HW_SECRET_KEY", self.calls[0][1])
        self.assertTrue(self.account.begin()["ready"])
        self.assert_safe(result)

    def test_begin_environment_fallback_does_not_save_to_settings_or_vault(self):
        with patch.dict(os.environ, {"CODEARTS_CLI_AK": AK, "CODEARTS_CLI_SK": SK}):
            result = self.account.begin()
        self.assertTrue(result["ready"])
        self.assertFalse(self.vault.values)
        self.assert_safe(result)

    def test_missing_cli_installer_download_error_reports_safe_progress(self):
        self.account._find_cli = lambda: None

        def failed_download(command, *, env, cwd, timeout):
            self.assertEqual(command[0], "powershell.exe")
            self.assertIn("-NonInteractive", command)
            self.assertEqual(command[command.index("-WindowStyle") + 1], "Hidden")
            source = base64.b64decode(command[-1]).decode("utf-16le")
            self.assertIn(INSTALLER_URL, source)
            self.assertIn("Get-Content", source)
            self.assertTrue(Path(env["TEMP"]).is_relative_to(self.profile))
            self.assertEqual(env["TEMP"], env["TMP"])
            self.assertNotIn("CODEARTS_CLI_SK", env)
            raise OSError(SK)

        self.account._runner = failed_download
        result = self.account.begin()
        self.assertFalse(result["ready"])
        self.assertTrue(self.progress)
        self.assert_safe(result)

    def test_successful_auto_install_continues_to_awaiting_credentials(self):
        installed = False
        self.account._find_cli = lambda: self.root / "codearts.cmd" if installed else None

        def install_runner(command, *, env, cwd, timeout):
            nonlocal installed
            self.assertEqual(command[0], "powershell.exe")
            source = base64.b64decode(command[-1]).decode("utf-16le")
            self.assertIn(INSTALLER_URL, source)
            self.assertNotIn("CODEARTS_CLI_AK", env)
            self.assertNotIn("CODEARTS_CLI_SK", env)
            self.assertEqual(env["TEMP"], cwd)
            installed = True
            return subprocess.CompletedProcess(command, 0, b"", b"")

        self.account._runner = install_runner
        with patch.dict(os.environ):
            os.environ.pop("CODEARTS_CLI_AK", None)
            os.environ.pop("CODEARTS_CLI_SK", None)
            result = self.account.begin()
        self.assertTrue(installed)
        self.assertEqual(self.account._cli, self.root / "codearts.cmd")
        self.assertIn("CodeArts CLI 安装完成。", self.progress)
        self.assertFalse(result["ready"])
        self.assertIn("下载访问密钥", result["message"])
        self.assertFalse(self.vault.values)
        self.assert_safe(result)

    def test_cancel_stops_download_poll_and_prevents_save(self):
        self.account.start_import()
        new = self.downloads / "credentials.csv"
        new.write_text(CSV, encoding="utf-8")
        self.account.cancel()
        self.assertIsNone(self.account.poll_downloads())
        self.assertFalse(self.account.import_text(f"{AK}\n{SK}")["ready"])
        self.assertTrue(new.exists())
        self.assertFalse(self.vault.values)

    def test_begin_can_reopen_after_cancel(self):
        self.account.cancel()
        with patch.dict(os.environ, {"CODEARTS_CLI_AK": AK, "CODEARTS_CLI_SK": SK}):
            result = self.account.begin()
        self.assertTrue(result["ready"])
        self.assert_safe(result)

    def test_close_stops_only_owned_process(self):
        command = [sys.executable, "-c", "import time; time.sleep(30)"]
        other = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.addCleanup(other.kill)
        self.addCleanup(lambda: None if other.poll() is not None else other.terminate())
        owned = self.account._spawn(command, env=self.account._base_env(), cwd=str(self.root),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.account.close()
        self.assertIsNotNone(owned.poll())
        self.assertIsNone(other.poll())
        other.terminate()
        other.wait(timeout=5)

    def test_models_table_import_returns_only_safe_first_column(self):
        def table_runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 0,
                f"│ huaweicloud/fixture-model │ Fixture Model {SK}\n"
                "huaweicloud/qwen3   Qwen 3\n"
                f"huaweicloud/{AK}  Do not return\n".encode(), b"")

        self.account._runner = table_runner
        result = self.account.import_text(f"{AK}\n{SK}")
        self.assertTrue(result["ready"])
        self.assertEqual(result["models"], ["huaweicloud/fixture-model", "huaweicloud/qwen3"])
        self.assert_safe(result)

    @unittest.skipUnless(os.name == "nt", "Windows launcher tree lifecycle")
    def test_timeout_terminates_owned_launcher_tree(self):
        import ctypes
        from ctypes import wintypes

        pid_file = self.root / "child.pid"
        launcher = self.root / "fake_launcher.py"
        launcher.write_text(
            "import subprocess,sys,time,pathlib\n"
            "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'], "
            "creationflags=subprocess.CREATE_NO_WINDOW)\n"
            "pathlib.Path(sys.argv[1]).write_text(str(child.pid))\n"
            "time.sleep(30)\n", encoding="utf-8")
        self.account._runner = None
        with self.assertRaises(subprocess.TimeoutExpired):
            self.account._run([sys.executable, str(launcher), str(pid_file)],
                              env=self.account._base_env(), cwd=str(self.root), timeout=1)
        child_pid = int(pid_file.read_text())
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, child_pid)
        if handle:
            try:
                self.assertEqual(kernel.WaitForSingleObject(handle, 1000), 0)
            finally:
                kernel.CloseHandle(handle)
        else:
            self.assertEqual(ctypes.get_last_error(), 87)
        self.assertFalse(self.account._processes)

    def test_begin_captures_boundary_and_ignores_renamed_preexisting_credentials(self):
        old = self.downloads / "old.csv"
        old.write_text(CSV, encoding="utf-8")
        unrelated = self.downloads / "unrelated.txt"
        unrelated.write_text("name,count\nbook,1", encoding="utf-8")
        self.account.begin()
        old.rename(self.downloads / "renamed.csv")
        unrelated.rename(self.downloads / "unrelated.csv")
        self.assertIsNone(self.account.poll_downloads())
        self.assertFalse(self.calls)
        self.assertTrue((self.downloads / "renamed.csv").exists())

    def test_explicit_cli_path_and_exact_console_guide(self):
        cli = self.root / "explicit-cli.cmd"
        cli.write_text("@exit /b 0\n", encoding="utf-8")
        self.context.config = {"cliPath": str(cli)}
        self.account._find_cli = CodeartsAccount._find_cli.__get__(self.account)
        self.assertTrue(self.account._ensure_cli())
        self.assertEqual(self.account._cli, cli.resolve())
        self.assertFalse(self.calls)
        guide = self.account.start_import()["message"]
        expected = "右上角用户名 → 我的凭证 → 访问密钥 → 新增访问密钥 → 下载访问密钥"
        self.assertEqual(guide.splitlines()[0], expected)
        self.assertIn("仅能下载一次", guide)
        self.assertIn("安全保存后", guide)
        self.assertIn("私密粘贴", guide)

    def test_models_uses_direct_executable_and_private_trusted_directory(self):
        captured = {}

        def private_runner(command, *, env, cwd, timeout):
            captured.update(command=command, env=env, cwd=Path(cwd))
            return subprocess.CompletedProcess(command, 0, b"huaweicloud/private-model\n", b"")

        self.account._runner = private_runner
        result = self.account.import_text(CSV)
        self.assertTrue(result["ready"])
        command, env, cwd = captured["command"], captured["env"], captured["cwd"]
        executable = self.root / "bin" / "codearts.exe" if os.name == "nt" else self.account._cli
        self.assertEqual(command, [str(executable), "models"])
        self.assertTrue(cwd.is_relative_to(self.profile))
        self.assertEqual(cwd.name, "work")
        private = cwd.parent
        for variable, directory in (("KERNEL_CONFIG_DIR", "config"), ("KERNEL_DATA_DIR", "data"),
                                    ("KERNEL_STATE_DIR", "state"), ("XDG_CACHE_HOME", "cache")):
            self.assertEqual(Path(env[variable]), private / directory)
        settings = json.loads((private / "data" / "settings.json").read_text(encoding="utf-8"))
        self.assertTrue(settings["security"]["folderTrust"]["enabled"])
        self.assertEqual(settings["security"]["trustedFolders"], [str(cwd.resolve())])
        self.assertEqual(Path(env["OPENCODE_CONFIG"]), private / "config" / "codearts_cli.json")
        self.assertEqual((env["CODEARTS_CLI_AK"], env["CODEARTS_CLI_SK"]), (AK, SK))
        self.assert_safe(result)

    def test_english_status_progress_and_parser_errors(self):
        self.context.language = "en-US"
        result = self.account.begin()
        self.assertIn("Username → My Credentials → Access Keys", result["message"])
        self.assertIn("only be downloaded once", result["message"])
        self.assertIn("Unrecognized", self.account.import_text("invalid")["message"])
        result = self.account.import_text(CSV)
        self.assertTrue(result["ready"])
        self.assertIn("stored securely", result["message"])
        self.assertIn("Verifying credentials", self.progress[0])
        self.assert_safe(result)

    def test_migrate_exact_legacy_profile_once_then_delete(self):
        self.assertEqual(self.account.migration_status, "not_checked")
        self.context.profile_dir = self.root / "original-profile"
        self.legacy.raw = json.dumps({"ak": AK, "sk": SK})
        self.assertEqual(self.account._credentials(), (AK, SK))
        expected = [(SERVICE, str(self.context.profile_dir))]
        self.assertEqual(self.legacy.reads, expected)
        self.assertEqual(self.legacy.deletes, expected)
        self.assertEqual(self.vault.values["account"], {"ak": AK, "sk": SK})
        self.assertEqual(self.account.migration_status, "migrated")
        self.assertEqual(self.account._credentials(), (AK, SK))
        self.assertEqual(self.account.migration_status, "migrated")
        self.assertEqual(self.legacy.reads, expected)
        self.assertEqual(self.legacy.deletes, expected)

    def test_migration_store_failure_keeps_legacy_and_retries(self):
        self.context.profile_dir = self.root / "original-profile"
        self.legacy.raw = json.dumps({"ak": AK, "sk": SK})
        self.vault.fail = True
        result = self.account.begin()
        self.assertFalse(result["ready"])
        self.assertFalse(self.legacy.deletes)
        self.assertFalse(self.vault.values)
        self.vault.fail = False
        self.assertEqual(self.account._credentials(), (AK, SK))
        self.assertEqual(len(self.legacy.reads), 2)
        self.assertEqual(len(self.legacy.deletes), 1)
        self.assert_safe(result)

    def test_migration_delete_failure_retries_without_reread(self):
        self.context.profile_dir = self.root / "original-profile"
        self.legacy.raw = json.dumps({"ak": AK, "sk": SK})
        self.legacy.fail_delete = True
        self.assertEqual(self.account._credentials(), (AK, SK))
        self.assertIn("legacy_profile", self.vault.values["account"])
        self.legacy.fail_delete = False
        self.assertEqual(self.account._credentials(), (AK, SK))
        self.assertEqual(len(self.legacy.reads), 1)
        self.assertEqual(len(self.legacy.deletes), 1)
        self.assertNotIn("legacy_profile", self.vault.values["account"])

    def test_migration_missing_checked_once_and_existing_sdk_never_overwritten(self):
        self.context.profile_dir = self.root / "original-profile"
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(self.account._credentials())
            self.assertIsNone(self.account._credentials())
        self.assertEqual(len(self.legacy.reads), 1)
        self.assertFalse(self.legacy.deletes)
        self.vault.values["account"] = {"ak": "other-ak", "sk": "other-sk"}
        self.legacy.raw = json.dumps({"ak": AK, "sk": SK})
        self.assertEqual(self.account._credentials(), ("other-ak", "other-sk"))
        self.assertEqual(len(self.legacy.reads), 1)
        self.assertFalse(self.legacy.deletes)

    def test_legacy_layout_requires_exact_username_and_does_not_enumerate(self):
        legacy_module = __import__(PACKAGE + ".legacy_vault", fromlist=["WindowsLegacyVault"])
        vault = legacy_module.WindowsLegacyVault()
        username = str(self.root / "exact-profile")
        targets = []
        def read(target):
            targets.append(target)
            return ("another-profile", "ignored") if target == SERVICE else (username, "fake-raw")
        vault._read = read
        self.assertEqual(vault.get_password(SERVICE, username), "fake-raw")
        self.assertEqual(targets, [SERVICE, f"{username}@{SERVICE}"])
        targets.clear()
        self.assertIsNone(vault.get_password("other-service", username))
        self.assertFalse(targets)


if __name__ == "__main__":
    unittest.main()
