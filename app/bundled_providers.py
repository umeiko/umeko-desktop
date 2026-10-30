"""Install optional bundled SDK packages without activating their Python code.

Package provenance and uninstall choices live in the profile's existing settings
transaction. Account IDs, configuration files and protected secrets survive upgrades.
"""
from __future__ import annotations

import copy
import json
import re
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path

from umeko_provider_sdk import ProviderError
from umeko_provider_sdk.packages import unpack_package, validate_config


STATE_KEY = "bundledProviders"
_ID = re.compile(r"[a-z][a-z0-9-]{0,63}")
_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:-([a-zA-Z0-9.-]+))?")


def _public_error(error, fallback):
    message = str(error)
    # Keep fixed helper messages translatable; dependencies may include paths
    # or configuration keys in their exceptions, so show a fixed fallback.
    return message if message.startswith(("随应用提供的供应商插件", "此标识的供应商插件",
                                          "此供应商插件版本", "未找到随应用提供的供应商插件")) else fallback


def _version(value):
    """Comparable SemVer precedence, including numeric prerelease identifiers."""
    match = _VERSION.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise ProviderError("随应用提供的供应商插件版本无效")
    major, minor, patch, prerelease = match.groups()
    identifiers = tuple((0, int(part)) if part.isdigit() else (1, part)
                        for part in prerelease.split(".")) if prerelease else ()
    return int(major), int(minor), int(patch), not bool(prerelease), identifiers


class BundledProviders:
    def __init__(self, manager):
        self.manager = manager
        self.catalog = {}
        root = Path(manager.c.root)
        folders = (root / "provider-resources", root / "build/provider-resources")
        self.index = next((p / "bundled-providers.json" for p in folders
                           if (p / "bundled-providers.json").is_file()), None)
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        catalog = {}
        if self.index:
            document = json.loads(self.index.read_text(encoding="utf-8-sig"))
            if not isinstance(document, dict) or document.get("schemaVersion") != 1 or not isinstance(document.get("providers"), list):
                raise ProviderError("随应用提供的供应商插件索引格式不受支持")
            for row in document["providers"]:
                if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not _ID.fullmatch(row["id"]):
                    raise ProviderError("随应用提供的供应商插件标识无效")
                _version(row.get("version"))
                archive = row.get("archive")
                if not isinstance(archive, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.zip", archive):
                    raise ProviderError("随应用提供的供应商插件必须使用本地 ZIP 文件名")
                if row["id"] in catalog or not isinstance(row.get("name"), str) or not row["name"].strip():
                    raise ProviderError("随应用提供的供应商插件条目重复或无效")
                catalog[row["id"]] = {key: row[key] for key in ("id", "version", "name", "archive")}
        self.catalog = catalog
        self._loaded = True

    def _state(self):
        saved = self.manager.c.store.data.get(STATE_KEY, {})
        if not isinstance(saved, dict) or not isinstance(saved.get("installed", {}), dict) or not isinstance(saved.get("uninstalled", []), list):
            raise ProviderError("随应用提供的供应商插件安装记录无效")
        return {"installed": dict(saved.get("installed", {})), "uninstalled": list(saved.get("uninstalled", []))}

    def _existing(self, plugin_id):
        folder = self.manager.root / "packages" / plugin_id
        return folder.exists() and any(folder.iterdir())

    def available(self):
        self._load()
        return [{key: row[key] for key in ("id", "version", "name")}
                for row in self.catalog.values() if not self._existing(row["id"])]

    def sync(self):
        """At manager construction, install defaults and upgrade tracked packages.

        The controller is not yet initialized and cannot have active tasks here.
        Return safe per-package errors instead of aborting the application startup.
        """
        try:
            self._load()
            state = self._state()
        except (OSError, ValueError, ProviderError) as exc:
            return [_public_error(exc, "无法读取随应用提供的供应商插件信息")]
        errors = []
        for plugin_id in self.catalog:
            if plugin_id in state["uninstalled"]:
                continue
            try:
                self._install(plugin_id, explicit=False)
            except (OSError, ValueError, ProviderError) as exc:
                errors.append(_public_error(exc, "供应商插件包、配置或文件访问无效，无法安装"))
        return errors

    def install(self, plugin_id):
        """Explicit installation clears a saved uninstall choice after success."""
        self._load()
        return self._install(plugin_id, explicit=True)

    def _install(self, plugin_id, explicit):
        if plugin_id not in self.catalog:
            raise ProviderError("未找到随应用提供的供应商插件")
        manager = self.manager
        row = self.catalog[plugin_id]
        with manager.lock:
            state = self._state()
            previous_version = state["installed"].get(plugin_id)
            if previous_version and _version(row["version"]) <= _version(previous_version):
                return False
            # An imported package is never silently adopted as bundled provenance.
            if not previous_version and self._existing(plugin_id):
                if explicit:
                    raise ProviderError("此标识的供应商插件已经安装")
                return False
            destination = manager.root / "packages" / plugin_id / row["version"]
            if destination.exists():
                raise ProviderError("此供应商插件版本已通过导入安装")
            source = self.index.parent / row["archive"]
            if source.is_symlink() or source.resolve().parent != self.index.parent.resolve():
                raise ProviderError("随应用提供的供应商插件包必须位于应用资源目录内")
            staging = manager.root / "staging" / uuid.uuid4().hex
            previous_providers = manager.c.store.data["providers"]
            had_state = STATE_KEY in manager.c.store.data
            previous_state = copy.deepcopy(manager.c.store.data.get(STATE_KEY))
            retired = None
            installed = False
            try:
                manifest, _, schema = unpack_package(source, staging)
                if manifest["id"] != plugin_id or manifest["version"] != row["version"]:
                    raise ProviderError("随应用提供的供应商插件包与索引不匹配")
                accounts = manager._accounts(plugin_id, previous_version) if previous_version else []
                for account in accounts:
                    # Startup sync precedes the controller's task pool. Only an
                    # explicit runtime operation needs the runtime busy guard.
                    if explicit:
                        manager._idle(account["id"])
                    config = manager._config_path(account["id"])
                    if config.exists():
                        validate_config(json.loads(config.read_text(encoding="utf-8")), schema)
                providers = [dict(account, pluginVersion=row["version"]) if account in accounts else account
                             for account in previous_providers]
                if not previous_version:
                    account = manager._new_account(manifest)
                    default_id = "bundled-" + plugin_id
                    if not any(existing.get("id") == default_id for existing in previous_providers):
                        account["id"] = default_id
                    providers.append(account)
                for account in accounts:
                    manager._invalidate(account["id"])
                destination.parent.mkdir(parents=True, exist_ok=True)
                staging.rename(destination)
                installed = True
                if previous_version:
                    old_path = manager._package_path({"pluginId": plugin_id, "pluginVersion": previous_version})
                    retired = manager._retire_package(old_path)
                state["installed"][plugin_id] = row["version"]
                state["uninstalled"] = [item for item in state["uninstalled"] if item != plugin_id]
                manager.c.store.data["providers"] = providers
                manager.c.store.data[STATE_KEY] = state
                manager.c.store.save()
            except Exception:
                manager.c.store.data["providers"] = previous_providers
                if had_state:
                    manager.c.store.data[STATE_KEY] = previous_state
                else:
                    manager.c.store.data.pop(STATE_KEY, None)
                if retired:
                    retired.rename(old_path)
                if installed:
                    destination.rename(staging)
                raise
            finally:
                if not staging.is_symlink() and staging.resolve().parent == (manager.root / "staging").resolve():
                    shutil.rmtree(staging, ignore_errors=True)
            if retired:
                manager._forget_package(old_path)
                manager._clean_retired(retired)
            return True

    def mark_uninstalled(self, plugin_id, version):
        """Call before the package uninstall's settings save; rollback with that save."""
        state = self._state()
        if state["installed"].get(plugin_id) != version:
            return
        state["installed"].pop(plugin_id)
        if plugin_id not in state["uninstalled"]:
            state["uninstalled"].append(plugin_id)
        self.manager.c.store.data[STATE_KEY] = state

    @contextmanager
    def uninstalling(self, plugin_id, version):
        """Enclose the existing uninstall transaction, including its settings save."""
        data = self.manager.c.store.data
        had_state, previous = STATE_KEY in data, copy.deepcopy(data.get(STATE_KEY))
        self.mark_uninstalled(plugin_id, version)
        try:
            yield
        except Exception:
            if had_state:
                data[STATE_KEY] = previous
            else:
                data.pop(STATE_KEY, None)
            raise
