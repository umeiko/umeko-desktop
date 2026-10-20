"""Prepare the full Pi Coding Agent after npm ci --prefix runtime."""
from pathlib import Path
from app.pi_runtime import project_runtime, verify_runtime, RELEASE_NAME

root = Path(__file__).resolve().parent
target = root / "runtime/releases" / RELEASE_NAME
if not target.exists():
    project_runtime(root / "runtime", target)
verify_runtime(target, root / "runtime/bridge.mjs")
print("Pi runtime verified:", target)
