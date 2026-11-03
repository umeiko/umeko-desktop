"""Local preferences and Windows DPAPI protected secrets. No network access."""
from __future__ import annotations

import base64
import copy
import ctypes
import json
import math
import os
import shutil
import hashlib
import uuid
from pathlib import Path
from ctypes import wintypes
from .platform_support import data_directory, legacy_data_directory, migrate_profile, normalize_projects
from .api_keys import make_key
from PySide6.QtCore import QLocale
from .desktop_preferences import DEFAULTS as DESKTOP_DEFAULTS, normalize as desktop_settings
from .multimodal_settings import DEFAULTS as MULTIMODAL_DEFAULTS, normalize as multimodal_settings
from .auxiliary_vision import DEFAULTS as VISION_DEFAULTS, normalize as vision_settings


class Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def protect(value: str, decrypt: bool = False, account: str = "") -> str:
    if not value:
        return ""
    if os.name != "nt":
        return keyring_protect(value, decrypt, account)
    raw = base64.b64decode(value) if decrypt else value.encode("utf-8")
    buf = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    dest = Blob()
    if decrypt:
        ok = ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(dest))
    else:
        ok = ctypes.windll.crypt32.CryptProtectData(ctypes.byref(source), "Umeko", None, None, None, 1, ctypes.byref(dest))
    if not ok:
        raise OSError("Windows 凭据保护失败")
    try:
        result = ctypes.string_at(dest.pbData, dest.cbData)
        return result.decode("utf-8") if decrypt else base64.b64encode(result).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(dest.pbData)


def keyring_protect(value, decrypt=False, account=""):
    import keyring
    backend = keyring.get_keyring()
    candidates = getattr(backend, "backends", [backend])
    secure = next((item for item in candidates if type(item).__module__ in (
        "keyring.backends.macOS", "keyring.backends.SecretService", "keyring.backends.kwallet") and item.priority > 0), None)
    if secure is None:
        raise RuntimeError("需要可用且已解锁的系统密钥环（macOS Keychain、Secret Service 或 KWallet）")
    if decrypt:
        if not value.startswith("keyring:"):
            raise RuntimeError("凭据不属于此平台，请在设置中重新输入")
        result = secure.get_password("umeko-desktop", value[8:])
        if result is None:
            raise RuntimeError("系统密钥环中缺少凭据，请检查密钥环或重新配置")
        return result
    account = account or uuid.uuid4().hex
    secure.set_password("umeko-desktop", account, value)
    return "keyring:" + account


DEFAULTS = {
    "projects": [], "activeProject": "", "removedProjects": [], "sessionMeta": {},
    "fontFamily": "",
    "employeeId": "", "password": "", "workspace": "", "dark": False, "theme": "light", "character": "yanami",
    "selectedProvider": "", "selectedModel": "",
    "providers": [],
    "multimodal": MULTIMODAL_DEFAULTS,
    "auxiliaryVision": VISION_DEFAULTS,
    "desktop": DESKTOP_DEFAULTS,
    "agent": {"maxTokens": 32768, "maxContextImages": 3, "outputLimitDefaultVersion": 1, "instructions": "", "autoCompaction": True,
              "agentDir": "", "skillPaths": [], "extensionPaths": [], "safeMode": False, "toolPermissionMode": "auto",
              "npmRegistry": "", "npmUserconfig": "", "npmCafile": ""},
    "server": {"port": 8787, "openai": True, "anthropic": True, "lan": False, "keys": []},
    "ui": {"sidebarWidth": 244, "sidebarCollapsed": False, "lineSpacing": "standard", "sessionCacheSize": 3},
}


class Store:
    def __init__(self, directory: Path | None = None):
        self.directory = directory
        custom = os.environ.get("UMEKO_DATA_DIR")
        if self.directory is None and custom:
            self.directory = Path(custom)
        if self.directory is None:
            self.directory = data_directory()
            previous = legacy_data_directory()
            migrate_profile(previous, self.directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "settings.json"
        self.data = copy.deepcopy(DEFAULTS)
        self._protected = {}
        self._serialized = None
        saved = {}
        if self.path.exists():
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            self.data.update(copy.deepcopy(saved))
            self.data["theme"] = saved.get("theme", "dark" if saved.get("dark") else "light")
            saved_server = saved.get("server", {})
            self.data["server"] = {**copy.deepcopy(DEFAULTS["server"]), **saved_server}
            self.data["agent"] = {**copy.deepcopy(DEFAULTS["agent"]), **saved.get("agent", {})}
            ui = saved.get("ui", {})
            self.data["ui"] = {**DEFAULTS["ui"], **(ui if isinstance(ui, dict) else {})}
            width = self.data["ui"]["sidebarWidth"]
            if type(width) not in (int, float) or not math.isfinite(width):
                width = DEFAULTS["ui"]["sidebarWidth"]
            self.data["ui"]["sidebarWidth"] = max(200, min(480, round(width)))
            self.data["ui"]["sidebarCollapsed"] = self.data["ui"]["sidebarCollapsed"] is True
            self.data["password"] = protect(self.data.get("password", ""), True)
            if "keys" in saved_server:
                # Proxy credentials are verifiers only; complete keys are never
                # recoverable from this profile after their creation dialog closes.
                for row in self.data["server"]["keys"]:
                    row.setdefault("lastUsedAt", "")
            else:
                legacy = protect(saved_server.get("token", ""), True)
                self.data["server"]["keys"] = [make_key(value=legacy)] if legacy else []
            self.data["server"].pop("token", None)
            for p in self.data["providers"]:
                p["key"] = protect(p.get("key", ""), True)
        # Retain the encrypted references read from disk. Ordinary UI saves
        # must not rewrite unchanged secrets through Secret Service/Keychain.
        self._namespace = hashlib.sha256(str(self.directory.resolve()).encode()).hexdigest()[:24]
        self._remember_secret('password', self.data.get('password', ''), saved.get('password', ''))
        saved_keys = {p['id']: p.get('key', '') for p in saved.get('providers', [])}
        for provider in self.data['providers']:
            self._remember_secret('provider:' + provider['id'], provider.get('key', ''), saved_keys.get(provider['id'], ''))
        image_limit = self.data['agent'].get('maxContextImages', 3)
        self.data['agent']['maxContextImages'] = max(1, image_limit) if type(image_limit) is int else 3
        self.data['desktop'] = desktop_settings(self.data.get('desktop'))
        self.data['multimodal'] = multimodal_settings(self.data.get('multimodal'))
        try:
            self.data['auxiliaryVision'] = vision_settings(self.data.get('auxiliaryVision', {}))
        except ValueError:
            self.data['auxiliaryVision'] = copy.deepcopy(VISION_DEFAULTS)
        output_default_migrated = saved.get('agent', {}).get('outputLimitDefaultVersion') != 1
        if output_default_migrated:
            if self.data['agent']['maxTokens'] == 8192:
                self.data['agent']['maxTokens'] = 32768
            self.data['agent']['outputLimitDefaultVersion'] = 1
        ui = self.data['ui']
        cache_size = ui.get('sessionCacheSize', 3)
        ui['sessionCacheSize'] = cache_size if type(cache_size) is int and 0 <= cache_size <= 2147483647 else 3
        if ui.get('language') not in ('zh', 'en'):
            preferred = QLocale.system().uiLanguages()
            system_language = preferred[0] if preferred else QLocale.system().name()
            ui['language'] = os.environ.get('UMEKO_LANGUAGE') or ('zh' if system_language.lower().startswith('zh') else 'en')
            if ui['language'] not in ('zh', 'en'): ui['language'] = 'en'
        old_ui = saved.get('ui') if isinstance(saved.get('ui'), dict) else {}
        scale = old_ui.get('fontScale', saved.get('fontScale', ui.get('fontScale', 1.)))
        ui['fontScale'] = max(.3, min(2., float(scale))) if type(scale) in (int, float) and math.isfinite(scale) else 1.
        line_spacing = old_ui.get('lineSpacing')
        line_spacing_migrated = line_spacing not in ('compact', 'standard', 'relaxed')
        ui['lineSpacing'] = 'standard' if line_spacing_migrated else line_spacing
        projects_migrated = normalize_projects(self.data)
        if not self.path.exists() or "keys" not in saved.get("server", {}) or output_default_migrated or projects_migrated or line_spacing_migrated:
            self.save()

    def _remember_secret(self, name, value, protected):
        if protected or not value:
            self._protected[name] = (hashlib.sha256(value.encode('utf-8')).digest(), protected)

    def _protect_secret(self, name, value):
        fingerprint = hashlib.sha256(value.encode('utf-8')).digest()
        cached = self._protected.get(name)
        if cached is not None and cached[0] == fingerprint:
            return cached[1]
        protected = protect(value, account=self._namespace + ':' + name)
        self._protected[name] = fingerprint, protected
        return protected

    def save(self):
        saved = copy.deepcopy(self.data)
        saved['password'] = self._protect_secret('password', saved.get('password', ''))
        for provider in saved['providers']:
            provider['key'] = self._protect_secret('provider:' + provider['id'], provider.get('key', ''))
        text = json.dumps(saved, ensure_ascii=False, indent=2)
        if text == self._serialized and self.path.exists():
            return
        temp = self.path.with_suffix('.tmp')
        temp.write_text(text, encoding='utf-8')
        temp.replace(self.path)
        self._serialized = text

    def load_sessions(self):
        path = self.directory / "sessions.json"
        if not path.exists():
            return []
        sessions = json.loads(path.read_text(encoding="utf-8"))
        legacy = self.directory / "sessions-legacy.json"
        if any("history" in session for session in sessions) and not legacy.exists():
            shutil.copy2(path, legacy)
        return sessions

    def save_sessions(self, sessions):
        path = self.directory / "sessions.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(sessions, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
