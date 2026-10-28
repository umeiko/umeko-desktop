"""Per-desktop-profile package history; retain metadata, never tool arguments.

The package metadata model adapts pi-extmgr 0.4.2's InstalledPackage/UnifiedItem
concepts (src/types/index.ts and src/ui/installed/items.ts). Persistence here is
an original desktop bridge implementation, not a copy of its state machinery.
"""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def text(value, limit=2000):
    return str(value)[:limit] if value is not None else ""


def audit_notes(value):
    if isinstance(value, str):
        return value[:4000]
    if isinstance(value, dict):
        # Runtime emits a concise review, never keep arbitrary request fields.
        return "\n".join(text(value[key], 1500) for key in ("summary", "notes", "status", "findings") if key in value)
    return ""


class PackageRecords:
    def __init__(self, directory):
        self.path = Path(directory) / "package-records.json"
        self.data = {"version": 1, "installations": [], "usage": {}}
        if self.path.exists():
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            self.data.update({key: saved[key] for key in ("installations", "usage") if key in saved})

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def installed(self, event):
        row = {key: text(event.get(key)) for key in ("package", "version", "source", "reason", "session", "workspace", "scope")}
        row.update(time=text(event.get("time")) or timestamp(),
                   installedBy="agent" if event.get("installedBy") == "agent" else "user",
                   audit=audit_notes(event.get("audit")))
        if not row["source"] or not row["package"]:
            return
        self.data["installations"].append(row)
        self.save()

    def used(self, event):
        package = text(event.get("package"))
        source = text(event.get("source") or package)
        identity = package or source
        if not identity:
            return
        row = self.data["usage"].setdefault(identity, {"useCount": 0, "lastUsed": ""})
        row["useCount"] += 1
        row["lastUsed"] = text(event.get("time")) or timestamp()
        row["package"] = package
        row["source"] = source
        self.save()

    def metadata(self, source, package, scope="", workspace=""):
        installs = [row for row in self.data["installations"] if
                    (row["source"] == source or row["package"] == package) and
                    (not row.get("scope") or row["scope"] == scope) and
                    (scope != "project" or not row.get("workspace") or row["workspace"] == workspace)]
        latest = installs[-1] if installs else {}
        usage = self.data["usage"].get(package) or self.data["usage"].get(source, {})
        if not usage:
            usage = next((row for row in self.data["usage"].values() if row.get("package") == package), {})
        return {"installedBy": latest.get("installedBy", "unknown"), "reason": latest.get("reason", ""),
                "audit": latest.get("audit", ""), "installedAt": latest.get("time", ""),
                "version": latest.get("version", ""), "lastUsed": usage.get("lastUsed", ""),
                "useCount": usage.get("useCount", 0), "installations": copy.deepcopy(installs)}
