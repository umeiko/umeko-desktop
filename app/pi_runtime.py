"""Install the full Pi Coding Agent; change only its built-in provider catalog."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PACKAGE = "@earendil-works/pi-coding-agent"
PINNED_VERSION = "1.3.0"
RELEASE_NAME = "coding-" + PINNED_VERSION
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
CATALOG = '''// Umeko provider policy. Native coding-agent implementation is unchanged.
import { createModels } from "../models.js";
export const getBuiltinModel = () => undefined;
export const getBuiltinImageModel = () => undefined;
export const getBuiltinClassifierModel = () => undefined;
export const getBuiltinProviders = () => [];
export const getBuiltinModelDataGeneratedAt = () => undefined;
export const getBuiltinModels = () => [];
export const getBuiltinImageModels = () => [];
export const getBuiltinClassifierModels = () => [];
export const getAllBuiltinModels = () => [];
export const builtinProviders = () => [];
export const builtinModels = (options) => createModels(options);
export const radiusProvider = () => { throw new Error("Configure suppliers in Umeko settings"); };
'''


def node_executable():
    found = shutil.which("node")
    if not found and sys.platform == "darwin":
        found = next((path for path in ("/opt/homebrew/bin/node", "/usr/local/bin/node") if Path(path).is_file()), None)
    if not found:
        raise RuntimeError("需要 Node.js 22.19 或更新版本来运行 Pi 内核")
    return found


def project_runtime(source: Path, destination: Path):
    if destination.exists():
        raise ValueError("内核目标目录已存在")
    modules = source / "node_modules"
    version = json.loads((modules / PACKAGE / "package.json").read_text(encoding="utf-8"))["version"]
    # Preserve the complete upstream SDK, native tools, resource loader and dependencies.
    shutil.copytree(modules, destination / "node_modules")
    ai = destination / "node_modules/@earendil-works/pi-ai/dist"
    if not (ai / "providers/all.js").is_file() or not (ai / "models.generated.js").is_file():
        raise RuntimeError("Pi provider 接口已变化，需要更新桥接适配")
    (ai / "providers/all.js").write_text(CATALOG, encoding="utf-8")
    (ai / "models.generated.js").write_text("export const MODELS = {};\nexport const IMAGE_MODELS = {};\nexport const CLASSIFIER_MODELS = {};\n", encoding="utf-8")
    (destination / "manifest.json").write_text(json.dumps({
        "package": PACKAGE, "version": version, "providerCatalog": False,
        "projection": 2, "engine": "full-coding-agent", "nativeTools": True,
    }, indent=2), encoding="utf-8")


def verify_runtime(release: Path, bridge_source: Path):
    manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("package") != PACKAGE or manifest.get("projection") != 2:
        raise RuntimeError("旧 Agent Core 内核不能用于完整 Pi Coding Agent")
    for name in ("bridge.mjs", "provider-policy.mjs", "resources.mjs"):
        shutil.copy2(bridge_source.parent / name, release / name)
    environment = dict(os.environ, PI_OFFLINE="1")
    environment.pop("NODE_OPTIONS", None)
    environment.pop("NODE_PATH", None)
    result = subprocess.run([node_executable(), str(release / "bridge.mjs"), "--self-test"],
                            capture_output=True, text=True, encoding="utf-8", timeout=60,
                            env=environment, creationflags=CREATE_NO_WINDOW)
    if result.returncode or '"ok":true' not in result.stdout:
        raise RuntimeError("新版本未通过完整 Pi 兼容性验证；已保留原有内核。" + result.stderr[-350:])


def installed_version(release: Path):
    return json.loads((release / "manifest.json").read_text(encoding="utf-8"))["version"]
