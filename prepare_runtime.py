"""Prepare the full Pi Coding Agent after npm ci --prefix runtime."""
import argparse
from pathlib import Path
import os
import subprocess
from app.pi_runtime import (
    BRIDGE_BUNDLE, CREATE_NO_WINDOW, RELEASE_NAME, node_environment, node_executable, project_runtime, verify_runtime,
)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--bundle-bridge", action="store_true", help="Build the optimized bridge for desktop packages")
args = parser.parse_args()
root = Path(__file__).resolve().parent
target = root / "runtime/releases" / RELEASE_NAME
if not target.exists():
    project_runtime(root / "runtime", target)
verify_runtime(target, root / "runtime/bridge.mjs")
if args.bundle_bridge:
    node = node_executable()
    environment = node_environment(dict(os.environ, PI_OFFLINE="1"))
    subprocess.run([node, str(root / "runtime/build-bridge.mjs"), str(target)],
                   env=environment, check=True, creationflags=CREATE_NO_WINDOW)
    bundle = subprocess.run([node, str(target / BRIDGE_BUNDLE), "--self-test"], env=environment,
                            capture_output=True, text=True, encoding="utf-8", timeout=60,
                            creationflags=CREATE_NO_WINDOW)
    if bundle.returncode or '"ok":true' not in bundle.stdout:
        raise RuntimeError("Bundled Pi bridge self-test failed: " + bundle.stderr[-1500:])
print("Pi runtime verified:", target)
