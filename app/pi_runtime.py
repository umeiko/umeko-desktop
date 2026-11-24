"""Install the full Pi Coding Agent; change only its built-in provider catalog."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from .filesystem_paths import filesystem_path, ordinary_path

PACKAGE = "@earendil-works/pi-coding-agent"
PINNED_VERSION = "1.5.2"
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
    source, destination = filesystem_path(source), filesystem_path(destination)
    if destination.exists():
        raise ValueError("内核目标目录已存在")
    modules = source / "node_modules"
    version = json.loads((modules / PACKAGE / "package.json").read_text(encoding="utf-8"))["version"]
    # Preserve the complete upstream SDK, native tools, resource loader and dependencies.
    # The source checkout can live under a long Windows workspace path. npm
    # installs nested SDK type declarations beyond MAX_PATH; preserve them too.
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
    path = filesystem_path(release) / "node_modules/@earendil-works/pi-ai/dist/utils/retry.js"
    original = "const errorMessage = message.errorMessage;"
    replacement = r'const errorMessage = message.errorMessage.replace(/\[Umeko:[a-f0-9-]{36}\]/gi, "[Umeko report]");'
    text = path.read_text(encoding="utf-8")
    if replacement not in text:
        if text.count(original) != 1:
            raise RuntimeError("Pi retry classifier changed; update the diagnostics adapter")
        path.write_text(text.replace(original, replacement), encoding="utf-8")


def patch_bash_job(release: Path):
    # Keep the built-in tool's source, policy, output handling, and shell
    # settings. The hook also covers Pi's direct Bash execution API.
    path = release / "node_modules/@earendil-works/pi-coding-agent/dist/core/tools/bash.js"
    if not path.is_file():
        return  # The compatibility check below reports a missing SDK.
    text = path.read_text(encoding="utf-8")
    hook = 'const host = globalThis[Symbol.for("umeko:bash-job")];'
    if hook in text:
        return
    replacements = {
        "exec: async (command, cwd, { onData, signal, timeout, env }) => {":
            "exec: async (command, cwd, { onData, signal, timeout, env, toolCallId }) => {",
        'const commandFromStdin = shellConfig.commandTransport === "stdin";':
            f'{hook}\n            if (shellName === "bash" && host) {{\n'
            '                return host({ shellConfig, command, cwd, onData, signal, timeout, timeoutMs, env: env ?? getShellEnv(), toolCallId });\n'
            '            }\n            const commandFromStdin = shellConfig.commandTransport === "stdin";',
        "env: spawnContext.env,": "env: spawnContext.env,\n                        toolCallId: _toolCallId,",
    }
    for original, replacement in replacements.items():
        if text.count(original) != 1:
            raise RuntimeError("Pi Bash 接口已变化，需要更新进程清理适配")
        text = text.replace(original, replacement)
    path.write_text(text, encoding="utf-8")


def copy_runtime_file(source, destination):
    """Leave prepared adapters untouched; publish changed files atomically."""
    source, destination = Path(source), Path(destination)
    try:
        if source.read_bytes() == destination.read_bytes():
            return str(destination)
    except FileNotFoundError:
        pass
    descriptor, temporary = tempfile.mkstemp(prefix='.' + destination.name + '.', dir=destination.parent)
    os.close(descriptor)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return str(destination)


def verify_runtime(release: Path, bridge_source: Path):
    node_release = ordinary_path(release)
    release, bridge_source = filesystem_path(release), filesystem_path(bridge_source)
    manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("package") != PACKAGE or manifest.get("projection") != 2:
        raise RuntimeError("旧 Agent Core 内核不能用于完整 Pi Coding Agent")
    patch_retry_diagnostics(release)
    patch_bash_job(release)
    for name in ("tool-visibility.mjs", "session-capabilities.mjs", "bridge.mjs", "package-install.mjs", "update-engine.mjs", "provider-policy.mjs", "resources.mjs", "chatbox.mjs", "network-retry.mjs", "pi-commands.mjs", "umeko-control.mjs", "umeko-documents.mjs", "widget-messages.mjs", "tool-permissions.mjs", "background-jobs.mjs", "process-guard.mjs", "subagents.mjs", "subagent-sdk.mjs", "subagent-settings.mjs", "input-queue.mjs", "recent-images.mjs", "auxiliary-vision.mjs", "rpc-ui.mjs", "umeko-operations.json", "webview-component.mjs", "webview-component.json"):
        copy_runtime_file(bridge_source.parent / name, release / name)
    copy_runtime_file(bridge_source.parent / 'update-cleanup.mjs', release / 'update-cleanup.mjs')
    copy_runtime_file(bridge_source.parent / 'generation.mjs', release / 'generation.mjs')
    for name in ('cowork-tools.mjs', 'cowork-local.mjs', 'cowork-subagents.mjs', 'ssh-workspace.mjs'):
        copy_runtime_file(bridge_source.parent / name, release / name)
    # Updated or previously prepared Pi kernels may predate the Cowork parser.
    modules = release / 'node_modules'
    if not (modules / 'parse5/package.json').is_file():
        for source in (bridge_source.parent / 'node_modules',
                       bridge_source.parent / 'releases' / RELEASE_NAME / 'node_modules'):
            if (source / 'parse5/package.json').is_file() and (source / 'entities/package.json').is_file():
                shutil.copytree(source / 'parse5', modules / 'parse5', dirs_exist_ok=True)
                shutil.copytree(source / 'entities', modules / 'parse5/node_modules/entities', dirs_exist_ok=True)
                break
    copy_runtime_file(bridge_source.parent / 'http-retry-boundary.mjs', release / 'http-retry-boundary.mjs')
    copy_runtime_file(bridge_source.parent / 'system-prompt.mjs', release / 'system-prompt.mjs')
    copy_runtime_file(bridge_source.parent / 'skills.mjs', release / 'skills.mjs')
    copy_runtime_file(bridge_source.parent / 'coordinator-skills.mjs', release / 'coordinator-skills.mjs')
    copy_runtime_file(bridge_source.parent / 'markdown-preview.mjs', release / 'markdown-preview.mjs')
    shutil.copytree(bridge_source.parent/'umeko-docs', release/'umeko-docs', dirs_exist_ok=True, copy_function=copy_runtime_file)
    environment = node_environment(dict(os.environ, PI_OFFLINE="1"))
    environment.pop("NODE_OPTIONS", None)
    environment.pop("NODE_PATH", None)
    result = subprocess.run([node_executable(), str(node_release / "bridge.mjs"), "--self-test"],
                            capture_output=True, text=True, encoding="utf-8", timeout=60,
                            env=environment, creationflags=CREATE_NO_WINDOW)
    if result.returncode or '"ok":true' not in result.stdout:
        raise RuntimeError("新版本未通过完整 Pi 兼容性验证；已保留原有内核。" + result.stderr[-350:])


def installed_version(release: Path):
    return json.loads((filesystem_path(release) / "manifest.json").read_text(encoding="utf-8"))["version"]
