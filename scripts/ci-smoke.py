"""Verify the frozen GUI and bundled Pi on the current build platform."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.pi_runtime import RELEASE_NAME, PINNED_VERSION, node_executable
from app.project_info import VERSION, git_output


def main():
    if sys.platform == "darwin":
        executable = ROOT / "dist/Umeko.app/Contents/MacOS/Umeko"
        resources = ROOT / "dist/Umeko.app/Contents/Frameworks"
    else:
        executable = ROOT / ("dist/Umeko/Umeko.exe" if sys.platform == "win32" else "dist/Umeko/Umeko")
        resources = ROOT / "dist/Umeko/_internal"
    if not executable.is_file(): raise RuntimeError("Packaged executable is missing")
    report_dir = ROOT / "build/ci-smoke"
    report_dir.mkdir(parents=True, exist_ok=True)
    diagnostic = report_dir / "application.log"
    screenshot = report_dir / "application.png"
    environment = dict(os.environ, UMEKO_DATA_DIR=str(report_dir / "profile"),
        CODEAGENT_DIAGNOSTICS=str(diagnostic), QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software")
    result = subprocess.run([str(executable), "--smoke", "--snapshot", str(screenshot)],
        env=environment, timeout=45, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (report_dir / "application-output.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    log = diagnostic.read_text(encoding="utf-8") if diagnostic.exists() else ""
    if result.returncode or log.strip() != "QML_READY\nEXIT:0":
        raise RuntimeError("Frozen GUI startup failed: " + log + result.stderr[-2000:])
    if not screenshot.is_file() or screenshot.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError("Frozen GUI did not render a screenshot")
    metadata = json.loads((resources / "build-info.json").read_text(encoding="utf-8"))
    if metadata["version"] != VERSION or metadata["commit"] != git_output(ROOT, "rev-parse", "HEAD"):
        raise RuntimeError("Frozen build provenance is missing")
    for name in ("umeko-provider-sdk-0.1.0.zip", "develop-umeko-provider.zip"):
        if not (resources / "provider-resources" / name).is_file():
            raise RuntimeError("Provider development resource is missing: " + name)
    runtime = resources / "runtime/releases" / RELEASE_NAME
    for name in ("bridge.mjs", "provider-policy.mjs", "resources.mjs"):
        if hashlib.sha256((runtime / name).read_bytes()).digest() != hashlib.sha256((ROOT / "runtime" / name).read_bytes()).digest():
            raise RuntimeError("Packaged Pi bridge differs from the source: " + name)
    pi = subprocess.run([node_executable(), str(runtime / "bridge.mjs"), "--self-test"],
        env=environment, timeout=60, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (report_dir / "pi.log").write_text(pi.stdout + pi.stderr, encoding="utf-8")
    if pi.returncode or '"ok":true' not in pi.stdout or '"version":"' + PINNED_VERSION + '"' not in pi.stdout:
        raise RuntimeError("Packaged Pi self-test failed: " + pi.stdout[-1500:] + pi.stderr[-1500:])
    if sys.platform == "darwin":
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(ROOT / "dist/Umeko.app")], check=True)
    (report_dir / "result.json").write_text(json.dumps({"gui": "passed", "pi": "passed", "build": metadata}, indent=2), encoding="utf-8")
    print("Packaged GUI rendered; bundled Pi self-test and build provenance verified")


if __name__ == "__main__": main()
