"""Archive a verified platform bundle, preserving Unix permissions and macOS links."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.project_info import VERSION
from macos_dmg import create_dmg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True, choices=("windows-x64", "linux-x64", "macos-x64", "macos-arm64"))
    args = parser.parse_args()
    report = json.loads((ROOT / "build/ci-smoke/result.json").read_text(encoding="utf-8"))
    if report["gui"] != "passed" or report["pi"] != "passed": raise RuntimeError("Package has not passed verification")
    if report.get('terminal')!='passed':raise RuntimeError('Packaged terminal has not passed verification')
    actual = ("windows" if sys.platform == "win32" else "macos" if sys.platform == "darwin" else "linux")
    if not args.platform.startswith(actual + "-"): raise RuntimeError("Package platform does not match the build host")
    architecture = report["build"]["architecture"].lower()
    expected_arch = "arm64" if "arm" in architecture or "aarch64" in architecture else "x64"
    if not args.platform.endswith("-" + expected_arch): raise RuntimeError("Package architecture does not match the build host")
    output = ROOT / "release-assets"
    output.mkdir(exist_ok=True)
    base = output / f"Umeko-{VERSION}-{args.platform}-{report['build']['commit'][:7]}"
    if sys.platform == "darwin":
        archive = Path(str(base) + ".zip")
        subprocess.run(["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(ROOT / "dist/Umeko.app"), str(archive)], check=True)
    elif sys.platform == "win32":
        archive = Path(shutil.make_archive(str(base), "zip", root_dir=ROOT / "dist", base_dir="Umeko"))
    else:
        archive = Path(str(base) + ".tar.gz")
        with tarfile.open(archive, "w:gz") as stream: stream.add(ROOT / "dist/Umeko", arcname="Umeko")
    digest = hashlib.sha256()
    with archive.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""): digest.update(chunk)
    checksum = digest.hexdigest()
    archive.with_name(archive.name + ".sha256").write_text(checksum + "  " + archive.name + "\n", encoding="utf-8")
    disk_image = {"diskImage": create_dmg(ROOT / "dist/Umeko.app", Path(str(base) + ".dmg"), "Umeko")} if sys.platform == "darwin" else {}
    (output / "build.json").write_text(json.dumps({**report, "platform": args.platform, "archive": archive.name, "sha256": checksum, **disk_image}, indent=2), encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(f"### {args.platform}\n\nGUI and Pi verification passed.\n\n- Package: `{archive.name}`\n- SHA-256: `{checksum}`\n")
    print(archive)


if __name__ == "__main__": main()
