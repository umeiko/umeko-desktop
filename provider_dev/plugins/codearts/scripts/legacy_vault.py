"""Read/delete the old account's Windows generic credential, using stdlib only.

The service/compound target layout and UTF-16/UTF-8 decoding follow the
installed python-keyring WinVaultKeyring implementation. No enumeration,
writing, alternative profile discovery or CLI login-file access is supported.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os

SERVICE = "umeko-desktop-codearts"


class WindowsLegacyVault:
    def __init__(self):
        self._api = None

    def _load(self):
        if os.name != "nt":
            return None
        if self._api is not None:
            return self._api

        class Credential(ctypes.Structure):
            _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                        ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                        ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
                        ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
                        ("UserName", wintypes.LPWSTR)]

        api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        pointer = ctypes.POINTER(Credential)
        api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(pointer)]
        api.CredReadW.restype = wintypes.BOOL
        api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        api.CredDeleteW.restype = wintypes.BOOL
        api.CredFree.argtypes = [ctypes.c_void_p]
        api.CredFree.restype = None
        self._api = api, pointer
        return self._api

    def _read(self, target):
        loaded = self._load()
        if loaded is None:
            return None
        api, pointer = loaded
        value = pointer()
        if not api.CredReadW(target, 1, 0, ctypes.byref(value)):
            error = ctypes.get_last_error()
            if error == 1168:
                return None
            raise OSError(error, "Legacy credential read failed")
        try:
            entry = value.contents
            blob = ctypes.string_at(entry.CredentialBlob, entry.CredentialBlobSize)
            try:
                decoded = blob.decode("utf-16")
            except UnicodeDecodeError:
                decoded = blob.decode("utf-8")
            return entry.UserName, decoded
        finally:
            api.CredFree(value)

    def get_password(self, service, username):
        if service != SERVICE or not username:
            return None
        for target in (service, f"{username}@{service}"):
            entry = self._read(target)
            if entry and entry[0] == username:
                return entry[1]
        return None

    def delete_password(self, service, username):
        if service != SERVICE or not username:
            return
        for target in (service, f"{username}@{service}"):
            entry = self._read(target)
            if entry and entry[0] == username:
                api, _ = self._load()
                if not api.CredDeleteW(target, 1, 0):
                    error = ctypes.get_last_error()
                    if error != 1168:
                        raise OSError(error, "Legacy credential deletion failed")
