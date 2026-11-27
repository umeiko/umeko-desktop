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


def patch_shell_environment(release: Path, bridge_source: Path):
    # The existing Pi shell adapter remains the command and output entrypoint.
    path = release / "node_modules/@earendil-works/pi-coding-agent/dist/core/tools/bash.js"
    if not path.is_file():
        return
    copy_runtime_file(bridge_source.parent / 'shell-snapshot.mjs', release / 'shell-snapshot.mjs')
    text = path.read_text(encoding="utf-8")
    hook = 'const snapshotEnv = globalThis[Symbol.for("umeko:shell-environment")];'
    if hook in text:
        return
    anchor = 'const host = globalThis[Symbol.for("umeko:bash-job")];'
    if text.count(anchor) != 1:
        raise RuntimeError("Pi shell environment adapter is unavailable")
    path.write_text(text.replace(anchor, f'{hook}\n'
        '            if (snapshotEnv) env = await snapshotEnv(shellName, env ?? getShellEnv(), shellConfig);\n'
        f'            {anchor}'), encoding="utf-8")


def patch_command_sessions(release: Path, bridge_source: Path):
    path = release / "node_modules/@earendil-works/pi-coding-agent/dist/core/tools/bash.js"
    if not path.is_file():
        return
    copy_runtime_file(bridge_source.parent / 'command-process.mjs', release / 'command-process.mjs')
    text = path.read_text(encoding="utf-8")
    if "command_session: Type.Optional" in text:
        return
    replacements = {
        'if (shellName === "bash" && host) {\n                return host({ shellConfig, command, cwd, onData, signal, timeout, timeoutMs, env: env ?? getShellEnv(), toolCallId });':
            'if (host) {\n                const result = await host({ shellName, shellConfig, command, cwd, onData, signal, timeout, timeoutMs, env: env ?? getShellEnv(), toolCallId });\n'
            '                if (result) return result;',
        'exit_code: Type.Number(),': 'exit_code: Type.Union([Type.Number(), Type.Null()]),\n'
            '    command_session: Type.Optional(Type.Record(Type.String(), Type.Unknown())),',
        'let exitCode;': 'let exitCode, commandSession;',
        'exitCode = result.exitCode;': 'exitCode = result.exitCode;\n                    commandSession = result.commandSession;',
        'if (exitCode === null) {': 'if (exitCode === null && !commandSession) {',
        'exit_code: exitCode,': 'exit_code: exitCode,\n'
            '                    ...(commandSession ? { command_session: commandSession } : {}),',
        'if (exitCode !== 0) {': 'if (commandSession) {\n'
            '                    let text = appendStatus(snapshot.content, "Command session: " + JSON.stringify(commandSession));\n'
            '                    const failed = exitCode !== null && exitCode !== 0;\n'
            '                    if (failed) text = appendStatus(text, "Command exited with code " + exitCode);\n'
            '                    return { content: [{ type: "text", text }], details: { ...details, commandSession }, structuredContent, isError: failed };\n'
            '                }\n'
            '                if (exitCode !== 0) {',
    }
    for original, replacement in replacements.items():
        if text.count(original) != 1:
            raise RuntimeError("Pi shell tool interface changed; update command session adapter")
        text = text.replace(original, replacement)
    path.write_text(text, encoding="utf-8")


def patch_powershell_output_encoding(release: Path):
    # Extend the host-backed tool only; custom PowerShell operations (e.g. remote)
    # do not run through Umeko's local command log reader.
    tools = release / "node_modules/@earendil-works/pi-coding-agent/dist/core/tools"
    bash, powershell = tools / "bash.js", tools / "powershell.js"
    if not bash.is_file() or not powershell.is_file():
        return
    plans = [
        (bash, "supportsOutputEncoding ?", {
            'timeout, env, toolCallId }) => {': 'timeout, env, toolCallId, outputEncoding }) => {',
            'env: env ?? getShellEnv(), toolCallId });': 'env: env ?? getShellEnv(), toolCallId, outputEncoding });',
            '            const commandFromStdin = shellConfig.commandTransport === "stdin";':
                '            if (outputEncoding === "gbk") throw new Error("GBK output requires the Umeko Windows command host");\n'
                '            const commandFromStdin = shellConfig.commandTransport === "stdin";',
            '        parameters: bashSchema,': '        parameters: options?.supportsOutputEncoding ? Type.Object({ ...bashSchema.properties,\n'
                '            output_encoding: Type.Optional(Type.Union([Type.Literal("utf8"), Type.Literal("gbk")], { description: "Force UTF-8 or GBK on both streams; omit to detect the encoding" })),\n'
                '        }) : bashSchema,',
            'async execute(_toolCallId, { command, timeout }, signal, onUpdate, ctx)':
                'async execute(_toolCallId, { command, timeout, output_encoding }, signal, onUpdate, ctx)',
            '                        toolCallId: _toolCallId,':
                '                        toolCallId: _toolCallId,\n'
                '                        outputEncoding: options?.supportsOutputEncoding ? output_encoding : undefined,',
        }),
        (powershell, "supportsOutputEncoding:", {
            '        ...options,\n        operations: options?.operations ?? createLocalPowerShellOperations(),':
                '        ...options,\n        supportsOutputEncoding: process.platform === "win32" && options?.supportsOutputEncoding !== false && !options?.operations,\n'
                '        operations: options?.operations ?? createLocalPowerShellOperations(),',
        }),
    ]
    pending = []
    for path, marker, replacements in plans:
        text = path.read_text(encoding="utf-8")
        if marker in text:
            continue
        for original, replacement in replacements.items():
            if text.count(original) != 1:
                raise RuntimeError("Pi PowerShell interface changed; update output encoding adapter")
            text = text.replace(original, replacement)
        pending.append((path, text))
    for path, text in pending:
        path.write_text(text, encoding="utf-8")


def patch_windows_shell_selection(release: Path):
    path = release / "node_modules/@earendil-works/pi-coding-agent/dist/core/tools/bash.js"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    hook = 'globalThis[Symbol.for("umeko:bash-config")]'
    if hook in text:
        return
    replacements = {
        "createLocalShellOperations(shellName, resolveShellConfig)":
            "createLocalShellOperations(shellName, resolveShellConfig, shellPath)",
        "const shellConfig = resolveShellConfig();":
            f'const resolveBash = {hook};\n'
            '            const shellConfig = shellName === "bash" && resolveBash\n'
            '                ? await resolveBash(shellPath, signal) : resolveShellConfig();',
        'createLocalShellOperations("bash", () => getShellConfig(options?.shellPath))':
            'createLocalShellOperations("bash", () => getShellConfig(options?.shellPath), options?.shellPath)',
        'Optionally provide a timeout in seconds.`,':
            'Optionally provide a timeout in seconds.' +
            '${globalThis[Symbol.for("umeko:shell-hints")]?.(config.name) || ""}`,',
    }
    for original, replacement in replacements.items():
        if text.count(original) != 1:
            raise RuntimeError("Pi shell interface changed; update Windows shell selection")
        text = text.replace(original, replacement)
    path.write_text(text, encoding="utf-8")


def patch_command_previews(release: Path, bridge_source: Path):
    path = release / "node_modules/@earendil-works/pi-coding-agent/dist/core/tools/bash.js"
    if not path.is_file():
        return
    copy_runtime_file(bridge_source.parent / "command-output.mjs", release / "command-output.mjs")
    text = path.read_text(encoding="utf-8")
    if 'Process running with session ID' in text:
        return
    replacements = {
        'let exitCode, commandSession;': 'let exitCode, commandSession, outputPreview;',
        'commandSession = result.commandSession;':
            'commandSession = result.commandSession;\n                    outputPreview = result.outputPreview;',
        'truncated: fullOutput.truncated,': 'truncated: fullOutput.truncated || Boolean(outputPreview),',
        '...(fullOutput.truncated && snapshot.fullOutputPath\n                        ? { full_output_path: snapshot.fullOutputPath }':
            '...(outputPreview?.fullOutputPath || (fullOutput.truncated && snapshot.fullOutputPath)\n'
            '                        ? { full_output_path: outputPreview?.fullOutputPath || snapshot.fullOutputPath }',
        'let text = appendStatus(snapshot.content, "Command session: " + JSON.stringify(commandSession));':
            'let text = appendStatus(snapshot.content, `Process running with session ID ${commandSession.id}. '
            'Use background_job with action read, stdoutOffset ${commandSession.stdoutOffset} and '
            'stderrOffset ${commandSession.stderrOffset} to continue reading, or action wait to wait for completion.`);',
        'Output is truncated to last ${DEFAULT_MAX_LINES} lines or ${DEFAULT_MAX_BYTES / 1024}KB (whichever is hit first). '
        'If truncated, full output is saved to a temp file.':
            'Completed local commands show up to ${DEFAULT_MAX_LINES} lines or ${DEFAULT_MAX_BYTES / 1024} KiB, keeping the '
            'beginning and end when truncated. Full output remains in the logs. A command that is still running returns a '
            'session ID for background_job. Use background_job start if a command needs standard input.',
    }
    for original, replacement in replacements.items():
        if text.count(original) != 1:
            raise RuntimeError("Pi shell interface changed; update the local command preview")
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


def patch_search_sandbox(release: Path):
    # Keep Pi's argument parsing, output limits and cancellation for rg and fd.
    tools = release / 'node_modules/@earendil-works/pi-coding-agent/dist/core/tools'
    for name, file, directory, original in (
        ('grep', 'rgPath', 'isDirectory ? searchPath : undefined',
         'const child = spawn(rgPath, args, {\n'
         '                            cwd: isDirectory ? searchPath : undefined,\n'
         '                            stdio: ["ignore", "pipe", "pipe"],\n'
         '                        });'),
        ('find', 'fdPath', 'undefined',
         'const child = spawn(fdPath, args, { stdio: ["ignore", "pipe", "pipe"] });'),
    ):
        path = tools / f'{name}.js'
        if not path.is_file():
            continue
        text = path.read_text(encoding='utf-8')
        hook = 'const prepare = globalThis[Symbol.for("umeko:search-command")];'
        if 'child.once("close", () => launch.cleanup?.());' in text:
            continue
        current = f'''{hook}
                        const directory = {directory};
                        const launch = prepare ? await prepare({file}, args, directory, ctx?.cwd || cwd, signal) :
                            {{ file: {file}, args, cwd: directory }};
                        signal?.throwIfAborted();
                        const child = spawn(launch.file, launch.args, {{
                            cwd: launch.cwd, env: launch.env, windowsHide: launch.windowsHide,
                            stdio: ["ignore", "pipe", "pipe"],
                        }});'''
        anchor = current if hook in text else original
        if text.count(anchor) != 1:
            raise RuntimeError(f'Pi {name} tool interface changed; update the search sandbox adapter')
        path.write_text(text.replace(anchor, f'''{hook}
                        const directory = {directory};
                        const launch = prepare ? await prepare({file}, args, directory, ctx?.cwd || cwd, signal) :
                            {{ file: {file}, args, cwd: directory }};
                        let child;
                        try {{
                            signal?.throwIfAborted();
                            child = spawn(launch.file, launch.args, {{
                                cwd: launch.cwd, env: launch.env, windowsHide: launch.windowsHide,
                                stdio: ["ignore", "pipe", "pipe"],
                            }});
                        }} catch (error) {{
                            launch.cleanup?.();
                            throw error;
                        }}
                        child.once("close", () => launch.cleanup?.());'''), encoding='utf-8')


def verify_runtime(release: Path, bridge_source: Path):
    node_release = ordinary_path(release)
    release, bridge_source = filesystem_path(release), filesystem_path(bridge_source)
    manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("package") != PACKAGE or manifest.get("projection") != 2:
        raise RuntimeError("旧 Agent Core 内核不能用于完整 Pi Coding Agent")
    patch_retry_diagnostics(release)
    patch_bash_job(release)
    patch_shell_environment(release, bridge_source)
    patch_command_sessions(release, bridge_source)
    patch_powershell_output_encoding(release)
    patch_windows_shell_selection(release)
    patch_command_previews(release, bridge_source)
    patch_search_sandbox(release)
    for name in ("tool-visibility.mjs", "session-capabilities.mjs", "bridge.mjs", "package-install.mjs", "update-engine.mjs", "provider-policy.mjs", "resources.mjs", "chatbox.mjs", "network-retry.mjs", "pi-commands.mjs", "umeko-control.mjs", "umeko-documents.mjs", "widget-messages.mjs", "tool-permissions.mjs", "background-jobs.mjs", "process-guard.mjs", "subagents.mjs", "subagent-sdk.mjs", "subagent-settings.mjs", "input-queue.mjs", "recent-images.mjs", "auxiliary-vision.mjs", "rpc-ui.mjs", "umeko-operations.json", "webview-component.mjs", "webview-component.json"):
        copy_runtime_file(bridge_source.parent / name, release / name)
    copy_runtime_file(bridge_source.parent / 'update-cleanup.mjs', release / 'update-cleanup.mjs')
    copy_runtime_file(bridge_source.parent / 'apply-patch.mjs', release / 'apply-patch.mjs')
    # Older bridge sources have no sandbox adapter. The runtime self-test below
    # rejects a newer bridge whose import cannot be resolved.
    for name in ('windows-sandbox.mjs', 'windows-sandbox-mcp.mjs'):
        sandbox_adapter = bridge_source.parent / name
        if sandbox_adapter.is_file():
            copy_runtime_file(sandbox_adapter, release / name)
    copy_runtime_file(bridge_source.parent / 'generation.mjs', release / 'generation.mjs')
    for name in ('cowork-tools.mjs', 'cowork-local.mjs', 'cowork-subagents.mjs'):
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
    for source in sorted(bridge_source.parent.glob('remote-*')):
        if source.suffix in ('.mjs', '.json'):
            copy_runtime_file(source, release / source.name)
    shutil.copytree(bridge_source.parent/'umeko-docs', release/'umeko-docs', dirs_exist_ok=True, copy_function=copy_runtime_file)
    environment = node_environment(dict(os.environ, PI_OFFLINE="1"))
    environment.pop("NODE_OPTIONS", None)
    environment.pop("NODE_PATH", None)
    from .windows_job import run_managed
    result = run_managed([node_executable(), str(node_release / "bridge.mjs"), "--self-test"],
                         capture_output=True, text=True, encoding="utf-8", timeout=60,
                         env=environment, creationflags=CREATE_NO_WINDOW)
    if result.returncode or '"ok":true' not in result.stdout:
        raise RuntimeError("新版本未通过完整 Pi 兼容性验证；已保留原有内核。" + result.stderr[-350:])


def installed_version(release: Path):
    return json.loads((filesystem_path(release) / "manifest.json").read_text(encoding="utf-8"))["version"]
