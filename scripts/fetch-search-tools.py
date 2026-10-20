"""Bundle pinned upstream fd/rg binaries and licenses for Pi's offline tools."""
from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.pi_runtime import RELEASE_NAME


def main():
    architecture = {"AMD64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}.get(platform.machine())
    target = {"win32": "pc-windows-msvc", "darwin": "apple-darwin", "linux": "unknown-linux-musl"}.get(sys.platform)
    key = f"{architecture}-{target}"
    manifest = json.loads((ROOT / "scripts/search-tools.json").read_text(encoding="utf-8"))
    if key not in manifest:
        raise RuntimeError("No pinned search tools for " + key)
    cache = ROOT / "runtime/downloads"
    output = ROOT / "runtime/releases" / RELEASE_NAME / "bin"
    cache.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    for entry in manifest[key]:
        archive = cache / entry["url"].rsplit("/", 1)[1]
        if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != entry["sha256"]:
            request = urllib.request.Request(entry["url"], headers={"User-Agent": "Umeko-build"})
            with urllib.request.urlopen(request, timeout=90) as response:
                raw = response.read(32 * 1024 * 1024)
            if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                raise RuntimeError("Upstream archive checksum mismatch: " + archive.name)
            archive.write_bytes(raw)
        raw = archive.read_bytes()
        executable = entry["binary"] + (".exe" if os.name == "nt" else "")
        members = {}
        if archive.suffix == ".zip":
            with zipfile.ZipFile(io.BytesIO(raw)) as handle:
                for member in handle.infolist():
                    name = PurePosixPath(member.filename).name
                    if not member.is_dir() and (name == executable or name.startswith(("LICENSE", "COPYING"))):
                        members[name] = handle.read(member)
        else:
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as handle:
                for member in handle.getmembers():
                    name = PurePosixPath(member.name).name
                    if member.isfile() and (name == executable or name.startswith(("LICENSE", "COPYING"))):
                        members[name] = handle.extractfile(member).read()
        if executable not in members or not any(name.startswith(("LICENSE", "COPYING")) for name in members):
            raise RuntimeError("Search tool or license missing: " + archive.name)
        for name, content in members.items():
            destination = output / (name if name == executable else entry["binary"] + "-" + name)
            destination.write_bytes(content)
            if name == executable: destination.chmod(0o755)
        subprocess.run([str(output / executable), "--version"], check=True)
    print("Bundled search tools verified:", key)


if __name__ == "__main__": main()
