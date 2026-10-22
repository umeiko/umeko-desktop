"""Local, opt-in Provider packages. The host knows no provider login protocol."""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import shutil
import sys
import threading
import types
import uuid
from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot, QStandardPaths

from umeko_provider_sdk import Provider, ProviderContext, ProviderError
from umeko_provider_sdk.packages import PackageValidationError, unpack_package, validate_folder, validate_config
from umeko_provider_sdk.network import network_scope
from .model_capabilities import normalize_model
from .storage import protect


class ProtectedSecrets:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.account = "provider:" + hashlib.sha256(str(self.path.resolve()).encode()).hexdigest()

    def _read(self):
        return json.loads(protect(self.path.read_text(encoding="utf-8"), True)) if self.path.exists() else {}

    def get(self, name, default=None):
        with self.lock: return copy.deepcopy(self._read().get(name, default))

    def set(self, name, value):
        with self.lock:
            data = self._read()
            data[name] = value
            self._write(data)

    def delete(self, name):
        with self.lock:
            data = self._read()
            data.pop(name, None)
            self._write(data)

    def clear(self, keep_credentials=False):
        with self.lock:
            credentials = self._read().get("credentials") if keep_credentials else None
            self._write({"credentials": credentials} if credentials else {})

    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(protect(json.dumps(data, ensure_ascii=False), account=self.account), encoding="utf-8")
        temp.replace(self.path)


class ProviderPlugins(QObject):
    changed = Signal()
    finished = Signal(str, object)

    def __init__(self, controller):
        super().__init__(controller)
        self.c = controller
        self.root = controller.store.directory / "provider-plugins"
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.clients, self.leases, self.busy, self.status = {}, {}, set(), {}
        self._import_error = {}
        self.closed = False
        self.finished.connect(self._finished)

    def _record(self, provider_id):
        record = next((p for p in self.c.store.data["providers"] if p["id"] == provider_id and p["api"] == "plugin"), None)
        if not record: raise ProviderError("自定义供应商不存在")
        return record

    def _package_path(self, record):
        # Saved settings are also validated before using their path components.
        import re
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", record.get("pluginId", "")) or not re.fullmatch(r"\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?", record.get("pluginVersion", "")):
            raise ProviderError("供应商包信息无效，请重新导入")
        return self.root / "packages" / record["pluginId"] / record["pluginVersion"]

    def _package(self, record):
        path = self._package_path(record)
        return path, validate_folder(path)

    def _accounts(self, plugin_id, version):
        return [p for p in self.c.store.data["providers"] if p.get("api") == "plugin"
                and p.get("pluginId") == plugin_id and p.get("pluginVersion") == version]

    @Property("QVariantMap", notify=changed)
    def importError(self):
        return self._import_error

    @Property("QVariantList", notify=changed)
    def packages(self):
        rows = []
        for path in sorted((self.root / "packages").glob("*/*")):
            if not path.is_dir() or path.is_symlink() or path.parent.is_symlink(): continue
            record = {"pluginId": path.parent.name, "pluginVersion": path.name}
            try: self._package_path(record)
            except ProviderError: continue
            accounts = self._accounts(path.parent.name, path.name)
            row = {"id": path.parent.name, "version": path.name, "name": path.parent.name,
                   "accountCount": len(accounts), "valid": False,
                   "busy": any(p["id"] in self.busy or self.leases.get(p["id"], 0)
                               or self.c._models_busy(p["id"]) for p in accounts)}
            try:
                manifest, _, _ = validate_folder(path)
                row.update(name=manifest["name"], valid=True)
            except (OSError, ValueError, RuntimeError): pass
            rows.append(row)
        return rows

    @staticmethod
    def _new_account(manifest):
        return {"id": uuid.uuid4().hex, "api": "plugin", "name": manifest["name"],
                "pluginId": manifest["id"], "pluginVersion": manifest["version"],
                "key": "", "baseUrl": "", "models": []}

    @Slot(str, str, result=bool)
    def addAccount(self, plugin_id, version):
        try:
            with self.lock:
                _, (manifest, _, _) = self._package({"pluginId": plugin_id, "pluginVersion": version})
                previous = self.c.store.data["providers"]
                self.c.store.data["providers"] = previous + [self._new_account(manifest)]
                try: self.c.store.save()
                except Exception:
                    self.c.store.data["providers"] = previous
                    raise
                self._notify(save=False)
            return True
        except (ProviderError, OSError, ValueError) as exc:
            self.c.toast.emit(str(exc))
            return False

    def _forget_package(self, path):
        namespace = "_umeko_provider_" + hashlib.sha256(str(path).encode()).hexdigest()[:24]
        for name in list(sys.modules):
            if name == namespace or name.startswith(namespace + "."):
                sys.modules.pop(name, None)
        vendor = str(path / "vendor")
        sys.path[:] = [entry for entry in sys.path if entry != vendor]
        importlib.invalidate_caches()

    def _retire_package(self, path):
        if not path.exists(): return None
        packages = (self.root / "packages").resolve()
        if path.is_symlink() or not path.resolve().is_relative_to(packages) or path.resolve() == packages:
            raise ProviderError("插件包路径超出安装目录，无法清理")
        retired = self.root / "retired" / uuid.uuid4().hex
        retired.parent.mkdir(parents=True, exist_ok=True)
        path.rename(retired)
        return retired

    def _clean_retired(self, path):
        if path and not path.is_symlink() and path.resolve().parent == (self.root / "retired").resolve():
            # Locked native dependencies can be retained here without blocking reinstall.
            shutil.rmtree(path, ignore_errors=True)

    def _secrets(self, provider_id):
        # IDs are generated by the host; never use an arbitrary caller path.
        self._record(provider_id)
        return ProtectedSecrets(self.root / "secrets" / (hashlib.sha256(provider_id.encode()).hexdigest() + ".dat"))

    def _config_path(self, provider_id):
        return self.root / "config" / (hashlib.sha256(provider_id.encode()).hexdigest() + ".json")

    def _client(self, provider_id):
        with self.lock:
            if self.closed: raise ProviderError("应用正在关闭")
            if provider_id in self.clients: return self.clients[provider_id]
            record = self._record(provider_id)
            path, (manifest, defaults, schema) = self._package(record)
            config_path = self._config_path(provider_id)
            config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else defaults
            validate_config(config, schema)
            state_dir = self.root / "state" / hashlib.sha256(provider_id.encode()).hexdigest()
            state_dir.mkdir(parents=True, exist_ok=True)
            namespace = "_umeko_provider_" + hashlib.sha256(str(path).encode()).hexdigest()[:24]
            if namespace not in sys.modules:
                module = types.ModuleType(namespace)
                module.__path__ = [str(path)]
                sys.modules[namespace] = module
            vendor = path / "vendor"
            if vendor.is_dir() and str(vendor) not in sys.path: sys.path.append(str(vendor))
            entry, factory = manifest["entrypoint"].split(":")
            try:
                implementation = importlib.import_module(namespace + "." + entry[:-3].replace("/", "."))
                client = getattr(implementation, factory)(ProviderContext(config, state_dir, self._secrets(provider_id)))
            except ImportError:
                raise ProviderError("供应商依赖缺失，请让插件作者将依赖放入包内 vendor 目录") from None
            if not isinstance(client, Provider): raise ProviderError("供应商实现必须继承 umeko_provider_sdk.Provider")
            self.clients[provider_id] = client
            return client

    @contextmanager
    def _lease(self, provider_id, management=False):
        with self.lock:
            if self.closed: raise ProviderError("应用正在关闭")
            if provider_id in self.busy and not management: raise ProviderError("供应商正在登录或刷新，请稍后重试")
            self.leases[provider_id] = self.leases.get(provider_id, 0) + 1
        try:
            with network_scope(self._record(provider_id).get('proxy')):
                yield self._client(provider_id)
        finally:
            with self.lock: self.leases[provider_id] -= 1

    def events(self, provider_id, model, messages, tools, max_tokens, parameters):
        with self._lease(provider_id) as client:
            yield from client.events(model, messages, tools, max_tokens, parameters)

    def _idle(self, provider_id):
        if self.closed: raise ProviderError("应用正在关闭")
        if self.c._models_busy(provider_id) or provider_id in self.busy or self.leases.get(provider_id, 0):
            raise ProviderError("该供应商仍有任务运行，结束后可修改")

    def _invalidate(self, provider_id):
        client = self.clients.pop(provider_id, None)
        if client: client.close()

    def _notify(self, save=True):
        if save: self.c.store.save()
        self.c._restart_pi()
        self.changed.emit()
        self.c.changed.emit()

    @Property("QVariantList", notify=changed)
    def rows(self):
        rows = []
        for record in self.c.store.data["providers"]:
            if record["api"] != "plugin": continue
            row = {"id": record["id"], "name": record["name"], "version": record["pluginVersion"],
                   "models": copy.deepcopy(record["models"]), "fields": [], "busy": record["id"] in self.busy,
                   "status": self.status.get(record["id"], record.get("accountLabel", "尚未登录"))}
            try:
                _, (manifest, _, _) = self._package(record)
                values = self._secrets(record["id"]).get("credentials", {})
                for field in manifest.get("auth", {}).get("fields", []):
                    row["fields"].append({**field, "secret": bool(field.get("secret")),
                        "value": "" if field.get("secret") else values.get(field["key"], ""),
                        "hasValue": bool(values.get(field["key"]))})
            except (OSError, ValueError, RuntimeError): row["status"] = "包或凭据不可用，请检查系统密钥环或重新登录"
            rows.append(row)
        return rows

    def _submit(self, provider_id, action, function, sensitive=None):
        with self.lock:
            self._idle(provider_id)
            self.busy.add(provider_id)
        self.status[provider_id] = "正在登录…" if action == "login" else "正在刷新模型…"
        self.changed.emit()
        def work():
            try:
                with self._lease(provider_id, management=True) as client: result = function(client)
                payload = {"action": action, "result": result}
            except ProviderError as exc:
                # A plugin must report safe errors; redact saved credential/session values as a backstop.
                message = str(exc)[:400]
                def redact(value):
                    nonlocal message
                    if isinstance(value, dict):
                        for item in value.values(): redact(item)
                    elif isinstance(value, str) and len(value) >= 3: message = message.replace(value, "***")
                redact(sensitive)
                for name in ("credentials", "session"):
                    try: redact(self._secrets(provider_id).get(name))
                    except Exception: pass
                payload = {"error": message}
            except Exception:
                payload = {"error": "供应商操作失败，请检查插件配置、依赖与网络"}
            if not self.closed: self.finished.emit(provider_id, payload)
        threading.Thread(target=work, daemon=True).start()

    @Slot(str, result=bool)
    def importZip(self, url):
        staging = self.root / "staging" / uuid.uuid4().hex
        self._import_error = {}
        try:
            path = QUrl(url).toLocalFile()
            if not path: raise ProviderError("请选择本机 ZIP 文件")
            manifest, defaults, _ = unpack_package(path, staging)
            destination = self.root / "packages" / manifest["id"] / manifest["version"]
            with self.lock:
                exists = destination.exists()
                if exists:
                    def digest(folder):
                        return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in folder.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
                    if digest(destination) != digest(staging): raise ProviderError("该插件版本已安装但内容不同；请先卸载插件，再安装修正版")
                installed = not exists
                previous = self.c.store.data["providers"]
                try:
                    if installed:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        staging.rename(destination)
                    record = self._new_account(manifest)
                    self.c.store.data["providers"] = previous + [record]
                    self.c.store.save()
                except Exception:
                    self.c.store.data["providers"] = previous
                    if installed and destination.exists() and not staging.exists():
                        destination.rename(staging)
                    raise
                self._notify(save=False)
            self.c.toast.emit("供应商已导入，请在当前页面登录并刷新模型")
            return True
        except Exception as exc:
            self._import_error = {"message": str(exc) if isinstance(exc, ProviderError) else "无法导入供应商包，请检查 ZIP 和 manifest.json"}
            if isinstance(exc, PackageValidationError):
                self._import_error.update(entry=exc.entry, rule=exc.rule, detail=exc.detail, conflict=exc.conflict)
            self.changed.emit()
            self.c.toast.emit("供应商导入失败，请查看错误详情")
            return False
        finally:
            if not staging.is_symlink() and staging.resolve().parent == (self.root / "staging").resolve():
                shutil.rmtree(staging, ignore_errors=True)

    @Slot(str, str)
    def login(self, provider_id, raw):
        try:
            _, (manifest, _, _) = self._package(self._record(provider_id))
            submitted = json.loads(raw)
            saved = self._secrets(provider_id).get("credentials", {})
            fields = manifest.get("auth", {}).get("fields", [])
            changed_identity = any(not f.get("secret") and str(submitted.get(f["key"], "")) != saved.get(f["key"], "") for f in fields)
            credentials = {}
            for field in fields:
                key = field["key"]
                value = str(submitted.get(key, ""))
                if not value and field.get("secret") and not changed_identity: value = saved.get(key, "")
                if field.get("required", True) and not value: raise ProviderError("请填写" + field["label"])
                credentials[key] = value
            def authenticate(client):
                details = client.authenticate(credentials) or {}
                models = client.list_models(refresh=True)
                self._secrets(provider_id).set("credentials", credentials)
                return {"models": models, "label": str(details.get("label", "已登录"))[:100]}
            self._submit(provider_id, "login", authenticate, {f["key"]: credentials[f["key"]] for f in fields if f.get("secret")})
        except (ValueError, RuntimeError, OSError) as exc: self.c.toast.emit(str(exc))

    @Slot(str)
    def refreshModels(self, provider_id):
        try: self._submit(provider_id, "refresh", lambda client: {"models": client.list_models(refresh=True)})
        except (ProviderError, OSError) as exc: self.c.toast.emit(str(exc))

    def _models(self, record, rows):
        if not isinstance(rows, list) or len(rows) > 2000: raise ProviderError("供应商返回的模型列表无效")
        previous = {m["upstream"]: m for m in record["models"]}
        taken = {m["alias"] for p in self.c.store.data["providers"] if p["id"] != record["id"] for m in p["models"]}
        models, ids = [], set()
        for row in rows:
            if not isinstance(row, dict): raise ProviderError("供应商模型条目必须为对象")
            upstream = row.get("id") or row.get("upstream")
            if not isinstance(upstream, str) or not upstream.strip() or upstream in ids: raise ProviderError("模型 ID 缺失或重复")
            ids.add(upstream)
            old = previous.get(upstream, {})
            alias = old.get("alias", upstream)
            if alias in taken: alias = record["id"][:8] + "/" + upstream
            if alias in taken or any(c.isspace() for c in alias): raise ProviderError("供应商模型别名无效")
            taken.add(alias)
            metadata = {"upstream": upstream}
            sources = {}
            for key, automatic in (("contextWindow", "contextWindowAuto"), ("vision", "visionAuto")):
                sources[key + "Source"] = "auto"
                if key in row:
                    metadata.update({key: row[key], automatic: False})
                    sources[key + "Source"] = "provider"
                if old.get(automatic) is False and old.get(key + "Source") != "provider":
                    metadata.update({key: old[key], automatic: False})
                    sources[key + "Source"] = "custom"
            models.append({"upstream": upstream, "alias": alias, **normalize_model(metadata), **sources})
        return models

    @staticmethod
    def modelSettings(row, previous=None):
        previous = previous or {}
        result = normalize_model(row, previous)
        for key, automatic in (("contextWindow", "contextWindowAuto"), ("vision", "visionAuto")):
            unchanged = result[key] == previous.get(key) and result[automatic] == previous.get(automatic)
            result[key + "Source"] = previous.get(key + "Source", "custom") if unchanged else ("auto" if result[automatic] else "custom")
        return result

    @Slot(str, object)
    def _finished(self, provider_id, payload):
        if self.closed: return
        with self.lock: self.busy.discard(provider_id)
        if "error" in payload:
            self.status[provider_id] = payload["error"]
            self.changed.emit()
            self.c.toast.emit(payload["error"])
            return
        try:
            record = self._record(provider_id)
            result = payload["result"]
            record["models"] = self._models(record, result["models"])
            if "label" in result: record["accountLabel"] = result["label"]
            self.status[provider_id] = record.get("accountLabel", "已连接") + f" · {len(record['models'])} 个模型"
            self.repair_selection(provider_id)
            self._notify()
            self.c.toast.emit("可用模型已更新")
        except (ProviderError, ValueError, OSError) as exc:
            self.status[provider_id] = str(exc)
            self.changed.emit()
            self.c.toast.emit(str(exc))

    def repair_selection(self, preferred=""):
        data = self.c.store.data
        usable = [p for p in data["providers"] if p["models"] and p["api"] != "internal"]
        current = next((p for p in usable if p["id"] == data["selectedProvider"]), None)
        if current and any(m["alias"] == data["selectedModel"] for m in current["models"]): return
        selected = next((p for p in usable if p["id"] == preferred), None) or next(iter(usable), None)
        data.update(selectedProvider=selected["id"] if selected else "", selectedModel=selected["models"][0]["alias"] if selected else "")

    @Slot(str, result=str)
    def configJson(self, provider_id):
        try:
            _, (_, defaults, _) = self._package(self._record(provider_id))
            path = self._config_path(provider_id)
            return json.dumps(json.loads(path.read_text(encoding="utf-8")) if path.exists() else defaults, ensure_ascii=False, indent=2)
        except (OSError, ValueError, ProviderError): return "{}"

    @Slot(str, str, result=bool)
    def saveConfig(self, provider_id, raw):
        try:
            with self.lock:
                self._idle(provider_id)
                _, (_, _, schema) = self._package(self._record(provider_id))
                config = json.loads(raw)
                validate_config(config, schema)
                path = self._config_path(provider_id)
                path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_suffix(".tmp")
                temp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
                temp.replace(path)
                self._invalidate(provider_id)
                self._secrets(provider_id).clear(keep_credentials=True)
                self.status[provider_id] = "配置已更新，请重新登录"
                self.changed.emit()
            self.c.toast.emit("插件配置已保存，请重新登录以应用")
            return True
        except (RuntimeError, ValueError, OSError) as exc:
            self.c.toast.emit(str(exc))
            return False

    @Slot(str, str, result=bool)
    def saveModels(self, provider_id, raw):
        try:
            with self.lock:
                self._idle(provider_id)
                record = self._record(provider_id)
                rows = json.loads(raw)
                ids = {m["upstream"] for m in record["models"]}
                if len(rows) != len(ids) or {r["upstream"] for r in rows} != ids: raise ProviderError("请通过刷新获取模型 ID")
                taken = {m["alias"] for p in self.c.store.data["providers"] if p["id"] != provider_id for m in p["models"]}
                previous = {m["upstream"]: m for m in record["models"]}
                models = []
                for row in rows:
                    alias = row["alias"].strip() or row["upstream"]
                    if not alias or alias in taken or any(c.isspace() for c in alias): raise ProviderError("别名不能重复或包含空白")
                    taken.add(alias)
                    models.append({"upstream": row["upstream"], "alias": alias, **self.modelSettings(row, previous.get(row["upstream"]))})
                record["models"] = models
                self.repair_selection(provider_id)
                self._notify()
            self.c.toast.emit("模型设置已保存")
            return True
        except (ProviderError, ValueError, KeyError, TypeError, OSError) as exc:
            self.c.toast.emit(str(exc))
            return False

    @Slot(str)
    def remove(self, provider_id):
        try:
            with self.lock:
                self._idle(provider_id)
                self._invalidate(provider_id)
                secrets = self._secrets(provider_id)
                previous = self.c.store.data["providers"]
                selection = {key: self.c.store.data[key] for key in ("selectedProvider", "selectedModel")}
                self.c.store.data["providers"] = [p for p in self.c.store.data["providers"] if p["id"] != provider_id]
                try:
                    self.repair_selection()
                    self.c.store.save()
                except Exception:
                    self.c.store.data["providers"] = previous
                    self.c.store.data.update(selection)
                    raise
                secrets.clear()
                self.status.pop(provider_id, None)
                self.leases.pop(provider_id, None)
                self._notify(save=False)
        except (RuntimeError, OSError) as exc: self.c.toast.emit(str(exc))

    @Slot(str, str, result=bool)
    def uninstall(self, plugin_id, version):
        try:
            with self.lock:
                path = self._package_path({"pluginId": plugin_id, "pluginVersion": version})
                accounts = self._accounts(plugin_id, version)
                for account in accounts: self._idle(account["id"])
                secrets = [self._secrets(p["id"]) for p in accounts]
                for account in accounts: self._invalidate(account["id"])
                retired = self._retire_package(path)
                previous = self.c.store.data["providers"]
                selection = {key: self.c.store.data[key] for key in ("selectedProvider", "selectedModel")}
                self.c.store.data["providers"] = [p for p in previous if p not in accounts]
                try:
                    self.repair_selection()
                    self.c.store.save()
                except Exception:
                    self.c.store.data["providers"] = previous
                    self.c.store.data.update(selection)
                    if retired: retired.rename(path)
                    raise
                self._forget_package(path)
                for vault in secrets: vault.clear()
                for account in accounts:
                    self.status.pop(account["id"], None)
                    self.leases.pop(account["id"], None)
                self._clean_retired(retired)
                self._notify(save=False)
            self.c.toast.emit("插件已卸载，可以重新安装")
            return True
        except (ProviderError, OSError) as exc:
            self.c.toast.emit(str(exc))
            return False

    @Slot(str, str, result=bool)
    def exportResource(self, kind, url):
        names = {"sdk": "umeko-provider-sdk-0.2.1.zip", "skill": "develop-umeko-provider.zip"}
        try:
            if kind not in names: raise ProviderError("未知开发资源")
            source = self.c.root / "provider-resources" / names[kind]
            if not source.exists(): source = self.c.root / "build/provider-resources" / names[kind]
            target = QUrl(url).toLocalFile()
            if not target: raise ProviderError("请选择本机保存位置")
            shutil.copyfile(source, target)
            self.c.toast.emit("开发资源已导出")
            return True
        except (ProviderError, OSError) as exc:
            self.c.toast.emit(str(exc) if isinstance(exc, ProviderError) else "开发资源导出失败，请检查保存位置或重新构建资源")
            return False

    @Slot(str, result=str)
    def resourceFile(self, kind):
        name = "umeko-provider-sdk-0.2.1.zip" if kind == "sdk" else "develop-umeko-provider.zip"
        folder = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation) or str(Path.home())
        return QUrl.fromLocalFile(str(Path(folder) / name)).toString()

    def close(self):
        with self.lock:
            self.closed = True
            for client in self.clients.values(): client.close()
            self.clients.clear()
