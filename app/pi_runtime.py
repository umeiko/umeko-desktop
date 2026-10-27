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
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    bundled = root / "runtime/node" / ("node.exe" if os.name == "nt" else "bin/node")
    if bundled.is_file():
        return str(bundled.resolve())
    if getattr(sys, "frozen", False):
        raise RuntimeError("内置 Node.js 缺失，请重新解压完整安装包，不要只复制可执行文件")
    found = shutil.which("node")
    if not found and sys.platform == "darwin":
        found = next((path for path in ("/opt/homebrew/bin/node", "/usr/local/bin/node") if Path(path).is_file()), None)
    if not found:
        raise RuntimeError("需要 Node.js 22.19 或更新版本来运行 Pi 内核")
    return found


def node_environment(values=None):
    environment = dict(os.environ if values is None else values)
    environment["PATH"] = str(Path(node_executable()).parent) + os.pathsep + environment.get("PATH", "")
    environment.pop("NODE_OPTIONS", None)
    environment.pop("NODE_PATH", None)
    return environment


def npm_command():
    node = Path(node_executable())
    installed = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    candidates = [node.parent / "node_modules/npm/bin/npm-cli.js",
                  node.parent.parent / "lib/node_modules/npm/bin/npm-cli.js"]
    if installed:
        candidates.append(Path(installed).resolve())
    candidates.extend((Path("/usr/share/nodejs/npm/bin/npm-cli.js"), Path("/usr/local/lib/node_modules/npm/bin/npm-cli.js")))
    for path in candidates:
        if path.is_file() and path.suffix == ".js":
            return [str(node), str(path)]
    raise RuntimeError("内置 npm 缺失，请重新解压完整安装包")


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


def patch_retry_diagnostics(release: Path):
    # Pi recognizes transient errors from text. Random report IDs can contain
    # status digits such as 503; exclude only that opaque marker from matching.
    path = release / "node_modules/@earendil-works/pi-ai/dist/utils/retry.js"
    original = "const errorMessage = message.errorMessage;"
    replacement = r'const errorMessage = message.errorMessage.replace(/\[Umeko:[a-f0-9-]{36}\]/gi, "[Umeko report]");'
    text = path.read_text(encoding="utf-8")
    if replacement not in text:
        if text.count(original) != 1:
            raise RuntimeError("Pi retry classifier changed; update the diagnostics adapter")
        path.write_text(text.replace(original, replacement), encoding="utf-8")


def verify_runtime(release: Path, bridge_source: Path):
    manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("package") != PACKAGE or manifest.get("projection") != 2:
        raise RuntimeError("旧 Agent Core 内核不能用于完整 Pi Coding Agent")
    patch_retry_diagnostics(release)
    for name in ("bridge.mjs", "provider-policy.mjs", "resources.mjs", "chatbox.mjs", "network-retry.mjs", "pi-commands.mjs", "umeko-control.mjs", "umeko-operations.json", "webview-component.mjs", "webview-component.json"):
        shutil.copy2(bridge_source.parent / name, release / name)
    shutil.copytree(bridge_source.parent/'umeko-docs', release/'umeko-docs', dirs_exist_ok=True)
    environment = node_environment(dict(os.environ, PI_OFFLINE="1"))
    environment.pop("NODE_OPTIONS", None)
    environment.pop("NODE_PATH", None)
    result = subprocess.run([node_executable(), str(release / "bridge.mjs"), "--self-test"],
                            capture_output=True, text=True, encoding="utf-8", timeout=60,
                            env=environment, creationflags=CREATE_NO_WINDOW)
    if result.returncode or '"ok":true' not in result.stdout:
        raise RuntimeError("新版本未通过完整 Pi 兼容性验证；已保留原有内核。" + result.stderr[-350:])


def installed_version(release: Path):
    return json.loads((release / "manifest.json").read_text(encoding="utf-8"))["version"]
