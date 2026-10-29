"""Bundled packages use disposable profiles and synthetic, inert SDK ZIPs only."""
import copy
import json
import shutil
import tempfile
import threading
import unittest
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.bundled_providers import BundledProviders, STATE_KEY, _version
from umeko_provider_sdk import ProviderError


class FakeStore:
    def __init__(self, directory):
        self.directory = directory
        self.path = directory / "settings.json"
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {"providers": [], "unrelated": {"keep": True}}

    def save(self):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data), encoding="utf-8")
        temporary.replace(self.path)


class FakeManager:
    def __init__(self, root, directory):
        directory.mkdir(parents=True, exist_ok=True)
        self.c = SimpleNamespace(root=root, store=FakeStore(directory))
        self.root = directory / "provider-plugins"
        self.root.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.invalidated = []

    def _accounts(self, plugin_id, version):
        return [p for p in self.c.store.data["providers"] if p.get("api") == "plugin"
                and p.get("pluginId") == plugin_id and p.get("pluginVersion") == version]

    @staticmethod
    def _new_account(manifest):
        return {"id": uuid.uuid4().hex, "api": "plugin", "pluginId": manifest["id"],
                "pluginVersion": manifest["version"], "name": manifest["name"], "models": []}

    def _package_path(self, record):
        return self.root / "packages" / record["pluginId"] / record["pluginVersion"]

    def _config_path(self, account_id):
        return self.root / "config" / (account_id + ".json")

    def _idle(self, account_id):
        pass

    def _invalidate(self, account_id):
        self.invalidated.append(account_id)

    def _retire_package(self, path):
        if not path.exists():
            return None
        retired = self.root / "retired" / uuid.uuid4().hex
        retired.parent.mkdir(parents=True, exist_ok=True)
        path.rename(retired)
        return retired

    def _forget_package(self, path):
        pass

    @staticmethod
    def _clean_retired(path):
        if path:
            shutil.rmtree(path)


class BundledProviderTests(unittest.TestCase):
    def setUp(self):
        test_root = Path("C:/UmekoTests") if __import__("os").name == "nt" else Path(tempfile.gettempdir()) / "UmekoTests"
        test_root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="bundled-provider-", dir=test_root)
        self.path = Path(self.temporary.name)
        self.root = self.path / "application"
        self.resources = self.root / "provider-resources"
        self.resources.mkdir(parents=True)
        self.profile = self.path / "profile"
        self.manager = FakeManager(self.root, self.profile)

    def tearDown(self):
        self.temporary.cleanup()

    def bundle(self, version="1.0.0", plugin_id="fixture-provider", *, schema=None, indexed_version=None):
        archive = f"{plugin_id}-{version}.zip"
        manifest = {"apiVersion": 1, "id": plugin_id, "name": "Fixture Provider", "version": version,
                    "entrypoint": "scripts/provider.py:create_provider"}
        with zipfile.ZipFile(self.resources / archive, "w") as stream:
            for name, value in {"manifest.json": json.dumps(manifest), "config.json": '{"prefix":"default"}',
                                "config.schema.json": json.dumps(schema or {"type": "object", "properties": {"prefix": {"type": "string"}}}),
                                "scripts/provider.py": "raise AssertionError('Installing a bundle executed plugin code')"}.items():
                stream.writestr(name, value)
        row = {"id": plugin_id, "name": "Fixture Provider", "version": indexed_version or version, "archive": archive}
        (self.resources / "bundled-providers.json").write_text(json.dumps({"schemaVersion": 1, "providers": [row]}), encoding="utf-8")
        return BundledProviders(self.manager)

    def restart(self):
        self.manager = FakeManager(self.root, self.profile)
        return BundledProviders(self.manager)

    def package(self, version="1.0.0"):
        return self.manager.root / "packages/fixture-provider" / version

    def uninstall(self, helper, version="1.0.0"):
        with helper.uninstalling("fixture-provider", version):
            old = self.package(version)
            retired = self.manager._retire_package(old)
            self.manager.c.store.data["providers"] = []
            self.manager.c.store.save()
            self.manager._clean_retired(retired)

    def test_default_install_is_inert_and_restart_adds_no_second_account(self):
        helper = self.bundle()
        self.assertEqual(helper.sync(), [])
        account = copy.deepcopy(self.manager.c.store.data["providers"][0])
        self.assertTrue(self.package().is_dir())
        self.assertEqual(helper.available(), [])
        self.assertEqual(self.manager.c.store.data[STATE_KEY]["installed"], {"fixture-provider": "1.0.0"})
        self.assertEqual(self.restart().sync(), [])
        self.assertEqual(self.manager.c.store.data["providers"], [account])

    def test_upgrade_preserves_account_models_configuration_and_opaque_credentials(self):
        self.bundle().sync()
        account = self.manager.c.store.data["providers"][0]
        account.update(name="My account", models=[{"upstream": "fixture-model", "alias": "custom-model"}], proxy="http://fixture.invalid")
        second = dict(account, id=uuid.uuid4().hex)
        self.manager.c.store.data["providers"].append(second)
        config = self.manager._config_path(account["id"])
        config.parent.mkdir(parents=True)
        config.write_text('{"prefix":"custom"}', encoding="utf-8")
        secret = self.manager.root / "secrets" / (account["id"] + ".dat")
        secret.parent.mkdir()
        secret.write_bytes(b"opaque synthetic credentials and session")
        self.manager.c.store.save()
        previous = copy.deepcopy(self.manager.c.store.data)
        helper = self.bundle("1.2.0")
        self.assertEqual(helper.sync(), [])
        expected = previous["providers"]
        for row in expected:
            row["pluginVersion"] = "1.2.0"
        self.assertEqual(self.manager.c.store.data["providers"], expected)
        self.assertEqual(config.read_text(), '{"prefix":"custom"}')
        self.assertEqual(secret.read_bytes(), b"opaque synthetic credentials and session")
        self.assertEqual(self.manager.c.store.data["unrelated"], {"keep": True})
        self.assertFalse(self.package().exists())
        self.assertTrue(self.package("1.2.0").is_dir())

    def test_uninstall_stays_suppressed_after_restart_and_app_upgrade_then_reinstalls(self):
        helper = self.bundle()
        helper.sync()
        self.uninstall(helper)
        self.assertEqual(self.restart().sync(), [])
        newer = self.bundle("2.0.0")
        self.assertEqual(newer.sync(), [])
        self.assertEqual(self.manager.c.store.data["providers"], [])
        self.assertEqual(newer.available(), [{"id": "fixture-provider", "version": "2.0.0", "name": "Fixture Provider"}])
        self.assertTrue(newer.install("fixture-provider"))
        self.assertEqual(self.manager.c.store.data[STATE_KEY]["uninstalled"], [])
        self.assertEqual(self.manager.c.store.data["providers"][0]["pluginVersion"], "2.0.0")

    def test_existing_user_import_is_not_adopted_or_overwritten(self):
        helper = self.bundle()
        folder = self.package()
        folder.mkdir(parents=True)
        marker = folder / "user-content.txt"
        marker.write_text("user import")
        self.assertEqual(helper.sync(), [])
        self.assertNotIn(STATE_KEY, self.manager.c.store.data)
        self.assertEqual(marker.read_text(), "user import")
        with self.assertRaises(ProviderError):
            helper.install("fixture-provider")

    def test_imported_upgrade_target_is_not_overwritten(self):
        self.bundle().sync()
        folder = self.package("2.0.0")
        folder.mkdir(parents=True)
        (folder / "user-content.txt").write_text("user import")
        helper = self.bundle("2.0.0")
        self.assertEqual("此供应商插件版本已通过导入安装", helper.sync()[0])
        self.assertEqual(self.manager.c.store.data["providers"][0]["pluginVersion"], "1.0.0")

    def test_failed_upgrade_save_restores_old_package_accounts_and_bundle_state(self):
        self.bundle().sync()
        previous = copy.deepcopy(self.manager.c.store.data)
        helper = self.bundle("2.0.0")
        with patch.object(self.manager.c.store, "save", side_effect=OSError("synthetic disk failure")):
            self.assertEqual("供应商插件包、配置或文件访问无效，无法安装", helper.sync()[0])
        self.assertEqual(self.manager.c.store.data, previous)
        self.assertTrue(self.package().is_dir())
        self.assertFalse(self.package("2.0.0").exists())

    def test_uninstall_transaction_failure_restores_suppression_state(self):
        helper = self.bundle()
        helper.sync()
        previous = copy.deepcopy(self.manager.c.store.data[STATE_KEY])
        with self.assertRaises(OSError):
            with helper.uninstalling("fixture-provider", "1.0.0"):
                raise OSError("synthetic uninstall failure")
        self.assertEqual(self.manager.c.store.data[STATE_KEY], previous)

    def test_older_application_bundle_does_not_downgrade_tracked_package(self):
        self.bundle("2.0.0").sync()
        self.assertEqual(self.bundle("1.0.0").sync(), [])
        self.assertTrue(self.package("2.0.0").is_dir())
        self.assertEqual(self.manager.c.store.data["providers"][0]["pluginVersion"], "2.0.0")

    def test_incompatible_configuration_leaves_old_installation_in_place(self):
        self.bundle().sync()
        account = self.manager.c.store.data["providers"][0]
        config = self.manager._config_path(account["id"])
        config.parent.mkdir(parents=True)
        config.write_text('{"prefix":12}')
        helper = self.bundle("2.0.0")
        self.assertEqual("供应商插件包、配置或文件访问无效，无法安装", helper.sync()[0])
        self.assertTrue(self.package().exists())
        self.assertEqual(account["pluginVersion"], "1.0.0")

    def test_mismatched_index_rejects_package_and_leaves_no_account(self):
        helper = self.bundle(indexed_version="2.0.0")
        self.assertEqual("随应用提供的供应商插件包与索引不匹配", helper.sync()[0])
        self.assertEqual(self.manager.c.store.data["providers"], [])

    def test_source_build_fallback_and_semver_prerelease_order(self):
        self.bundle("1.0.0-rc.2")
        fallback = self.root / "build/provider-resources"
        fallback.parent.mkdir()
        self.resources.rename(fallback)
        self.assertEqual(BundledProviders(self.manager).sync(), [])
        self.assertTrue(self.package("1.0.0-rc.2").is_dir())
        self.assertLess(_version("1.0.0-rc.2"), _version("1.0.0-rc.10"))
        self.assertLess(_version("1.0.0-rc.10"), _version("1.0.0"))

    def test_default_account_identity_is_stable_across_fresh_profiles_and_reinstall(self):
        helper = self.bundle()
        helper.sync()
        first = self.manager.c.store.data["providers"][0]["id"]
        self.assertEqual(first, "bundled-fixture-provider")
        another = FakeManager(self.root, self.path / "another-profile")
        BundledProviders(another).sync()
        self.assertEqual(another.c.store.data["providers"][0]["id"], first)
        self.uninstall(helper)
        self.assertTrue(helper.install("fixture-provider"))
        self.assertEqual(self.manager.c.store.data["providers"][0]["id"], first)


if __name__ == "__main__":
    unittest.main()
