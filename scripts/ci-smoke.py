"""Verify the frozen GUI and bundled Pi on the current build platform."""
from __future__ import annotations

import hashlib
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.pi_runtime import RELEASE_NAME, PINNED_VERSION
from app.project_info import VERSION, git_output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", default="dist")
    output = ROOT / parser.parse_args().dist
    if sys.platform == "darwin":
        executable = output / "Umeko.app/Contents/MacOS/Umeko"
        resources = output / "Umeko.app/Contents/Frameworks"
    else:
        executable = output / ("Umeko/Umeko.exe" if sys.platform == "win32" else "Umeko/Umeko")
        resources = output / "Umeko/_internal"
    if not executable.is_file(): raise RuntimeError("Packaged executable is missing")
    report_dir = ROOT / "build/ci-smoke"
    report_dir.mkdir(parents=True, exist_ok=True)
    diagnostic = report_dir / "application.log"
    screenshot = report_dir / "application.png"
    environment = dict(os.environ, UMEKO_DATA_DIR=str(report_dir / "profile"),
        CODEAGENT_DIAGNOSTICS=str(diagnostic), QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software")
    environment["PATH"] = str(report_dir / "no-system-node")
    environment.pop("NODE_OPTIONS", None); environment.pop("NODE_PATH", None)
    node = resources / "runtime/node" / ("node.exe" if os.name == "nt" else "bin/node")
    if not node.is_file(): raise RuntimeError("Bundled Node.js is missing")
    diagnostic.unlink(missing_ok=True)
    result = subprocess.run([str(executable), "--smoke", "--snapshot", str(screenshot)],
        env=environment, timeout=45, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (report_dir / "application-output.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    log = diagnostic.read_text(encoding="utf-8") if diagnostic.exists() else ""
    lines = log.strip().splitlines()
    selected = next((line.split(":", 1)[1] for line in lines if line.startswith("NODE_EXECUTABLE:")), "")
    if result.returncode or lines != ["QML_READY", "NODE_EXECUTABLE:" + selected, "EXIT:0"] or not selected or Path(selected).resolve() != node.resolve():
        raise RuntimeError("Frozen GUI startup failed: " + log + result.stderr[-2000:])
    if not screenshot.is_file() or screenshot.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError("Frozen GUI did not render a screenshot")
    metadata = json.loads((resources / "build-info.json").read_text(encoding="utf-8"))
    if metadata["version"] != VERSION or metadata["commit"] != git_output(ROOT, "rev-parse", "HEAD"):
        raise RuntimeError("Frozen build provenance is missing")
    for name in ("umeko-provider-sdk-0.2.1.zip", "develop-umeko-provider.zip"):
        if not (resources / "provider-resources" / name).is_file():
            raise RuntimeError("Provider development resource is missing: " + name)
    runtime = resources / "runtime/releases" / RELEASE_NAME
    for name in ("fd", "rg"):
        tool = runtime / "bin" / (name + (".exe" if os.name == "nt" else ""))
        subprocess.run([str(tool), "--version"], check=True, capture_output=True, timeout=15)
    for name in ("bridge.mjs", "provider-policy.mjs", "resources.mjs", "chatbox.mjs"):
        if hashlib.sha256((runtime / name).read_bytes()).digest() != hashlib.sha256((ROOT / "runtime" / name).read_bytes()).digest():
            raise RuntimeError("Packaged Pi bridge differs from the source: " + name)
    npm = resources / "runtime/node" / ("node_modules/npm/bin/npm-cli.js" if os.name == "nt" else "lib/node_modules/npm/bin/npm-cli.js")
    subprocess.run([str(node), str(npm), "--version"], env=environment, check=True, capture_output=True, timeout=15)
    pi = subprocess.run([str(node), str(runtime / "bridge.mjs"), "--self-test"],
        env=environment, timeout=60, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (report_dir / "pi.log").write_text(pi.stdout + pi.stderr, encoding="utf-8")
    if pi.returncode or '"ok":true' not in pi.stdout or '"version":"' + PINNED_VERSION + '"' not in pi.stdout:
        raise RuntimeError("Packaged Pi self-test failed: " + pi.stdout[-1500:] + pi.stderr[-1500:])
    if sys.platform == "darwin":
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(output / "Umeko.app")], check=True)
    (report_dir / "result.json").write_text(json.dumps({"gui": "passed", "pi": "passed", "build": metadata}, indent=2), encoding="utf-8")
    print("Packaged GUI rendered; bundled Pi self-test and build provenance verified")


if __name__ == "__main__": main()
