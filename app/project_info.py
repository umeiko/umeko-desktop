"""Public project identity and build provenance; no account or workspace data."""
from __future__ import annotations

import json
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

NAME = "Umeko"
VERSION = "0.3.4"
AUTHOR = "umeiko"
PROJECT_URL = "https://github.com/umeiko/umeko-desktop"
AUTHOR_URL = "https://github.com/umeiko"
RELEASES_URL = PROJECT_URL + "/releases"
RELEASE_API = "https://api.github.com/repos/umeiko/umeko-desktop/releases/latest"


def git_output(root, *args):
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), *args], text=True, stderr=subprocess.DEVNULL,
            timeout=3, creationflags=0x08000000 if sys.platform == "win32" else 0,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def build_metadata(root):
    return {
        "version": VERSION, "system": platform.system(), "architecture": platform.machine(),
        "builtAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commit": git_output(root, "rev-parse", "HEAD"),
        "dirty": bool(git_output(root, "status", "--porcelain", "--untracked-files=normal")),
    }


def project_info(root: Path, *, frozen=None):
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    metadata = {}
    if frozen:
        try:
            value = json.loads((root / "build-info.json").read_text(encoding="utf-8"))
            if isinstance(value, dict) and value.get("version") == VERSION:
                metadata = value
        except (OSError, ValueError):
            pass
    system = str(metadata.get("system") or platform.system())
    system = {"Darwin": "macOS"}.get(system, system)
    arch = str(metadata.get("architecture") or platform.machine())
    arch = {"amd64": "x64", "x86_64": "x64", "aarch64": "ARM64", "arm64": "ARM64", "i686": "x86"}.get(arch.lower(), arch)
    commit = str(metadata.get("commit", "")) if frozen else git_output(root, "rev-parse", "HEAD")
    commit = commit[:8] if re.fullmatch(r"[a-fA-F0-9]{7,64}", commit) else "未记录"
    built_at = "未记录" if frozen else "源码运行"
    try:
        if metadata.get("builtAt"):
            built_at = datetime.fromisoformat(metadata["builtAt"].replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    except (ValueError, TypeError, AttributeError):
        pass
    return {
        "name": NAME, "version": VERSION, "author": AUTHOR, "projectUrl": PROJECT_URL,
        "authorUrl": AUTHOR_URL, "buildPlatform": system + " · " + arch,
        "buildType": "打包版" if frozen else "源码运行", "builtAt": built_at,
        "commit": commit, "dirty": bool(metadata.get("dirty", False)),
    }
