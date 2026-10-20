"""Named proxy keys and a replaceable authentication snapshot for HTTP threads."""
import hmac
import hashlib
import re
import secrets
import uuid
import threading
from datetime import datetime, timezone


def generate_key():
    return "umeko-" + secrets.token_urlsafe(32)


def validate_key(value):
    value = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9._~\-]{16,256}", value):
        raise ValueError("API Key 需为 16–256 位字母、数字或 . _ ~ -，也可点击生成")
    return value


def make_key(name="默认 Key", value=""):
    name = name.strip()
    if not name or len(name) > 80 or any(ord(c) < 32 for c in name):
        raise ValueError("Key 名称需为 1–80 个字符")
    value = validate_key(value) if value else generate_key()
    return {"id": str(uuid.uuid4()), "name": name, "digest": key_digest(value), "hint": "••••••••" + value[-4:],
            "enabled": True, "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "lastUsedAt": ""}


def key_digest(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def key_summary(row):
    return {k: row[k] for k in ("id", "name", "enabled", "createdAt", "lastUsedAt")} | {"maskedKey": row["hint"]}


class KeyCatalog:
    def __init__(self, rows):
        self._lock = threading.Lock()
        self._used = {}
        self.update(rows)

    def update(self, rows):
        # An immutable snapshot prevents HTTP threads observing a half-edited key.
        self._active = tuple((row["id"], bytes.fromhex(row["digest"])) for row in rows if row["enabled"])
        with self._lock:
            self._used = {row["id"]: self._used.get(row["id"], row.get("lastUsedAt", "")) for row in rows}

    def usage(self):
        with self._lock:
            return dict(self._used)

    def authorized(self, value):
        try:
            supplied = value.encode("ascii")
        except (UnicodeError, AttributeError):
            return False
        if not 0 < len(supplied) <= 256:
            return False
        digest = hashlib.sha256(supplied).digest()
        for key_id, expected in self._active:
            if hmac.compare_digest(digest, expected):
                with self._lock:
                    if key_id in self._used:
                        self._used[key_id] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                return True
        return False


def lan_addresses():
    # Interface enumeration makes no DNS, discovery or outbound network requests.
    from PySide6.QtNetwork import QAbstractSocket, QNetworkInterface
    addresses = set()
    for interface in QNetworkInterface.allInterfaces():
        if not interface.flags() & QNetworkInterface.IsUp:
            continue
        for entry in interface.addressEntries():
            ip = entry.ip()
            if ip.protocol() == QAbstractSocket.IPv4Protocol and not ip.isLoopback() and not ip.isNull():
                addresses.add(ip.toString())
    return sorted(addresses)
