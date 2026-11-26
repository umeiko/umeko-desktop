#!/usr/bin/env python3
"""Stage pinned official exec-server assets. Existing staged assets are reused.

Only newly downloaded product assets are SHA-256 checked, once, before rename.
This intentionally does not perform recurrent integrity scans of reused files.
"""
import argparse
import hashlib
import json
from pathlib import Path
import ssl
import urllib.request


def main():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "runtime/remote-exec-assets.json").read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", action="append", choices=[*manifest["assets"], "windows", "linux", "win-x64", "win-arm64"], help="Repeat for multiple assets; default all four")
    parser.add_argument("--arch", choices=["x64", "arm64"], default="x64")
    parser.add_argument("--dest", "--output", dest="dest", type=Path, default=root / "runtime/remote-exec-assets")
    args = parser.parse_args()
    args.dest.mkdir(parents=True, exist_ok=True)
    for platform in args.platform or manifest["assets"]:
        platform = platform.replace("win-", "windows-", 1)
        if platform in ("windows", "linux"):
            platform += "-" + args.arch
        asset = manifest["assets"][platform]
        target = args.dest / asset["name"]
        if target.is_file():
            print(f"Reusing {target.name}")
            continue
        temporary = target.with_name(target.name + ".download")
        digest = hashlib.sha256()
        try:
            # Public release download, no credentials. Company download policy
            # permits the corporate TLS interceptor without installing a CA.
            url = f"https://github.com/openai/codex/releases/download/{manifest['version']}/{asset['name']}"
            request = urllib.request.Request(url, headers={"User-Agent": "Umeko-remote-assets"})
            with urllib.request.urlopen(request, context=ssl._create_unverified_context(), timeout=60) as response, temporary.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    digest.update(chunk)
                    output.write(chunk)
            if digest.hexdigest() != asset["sha256"]:
                raise RuntimeError(f"Official release digest mismatch: {asset['name']}")
            temporary.replace(target)
            print(f"Staged {target.name}")
        finally:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
