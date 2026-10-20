"""Launch the embedded native Pi CLI in an actual, independent local terminal."""
import hashlib
import os
import shlex
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from .pi_runtime import PACKAGE, node_executable, verify_runtime


def console_runtime(release, directory, agent_dir, bridge_source):
    # Native `pi update` must never modify the application's factory baseline.
    key = hashlib.sha256((str(release.resolve()) + str(agent_dir)).encode()).hexdigest()[:20]
    base = directory / "pi-console" / key
    base.mkdir(parents=True, exist_ok=True)
    runtime = base / "runtime"
    if runtime.exists():
        try:
            verify_runtime(runtime, bridge_source)
            return runtime
        except (OSError, RuntimeError, ValueError):
            if runtime.resolve().parent != base.resolve():
                raise RuntimeError("Pi 终端副本路径无效")
            runtime.rename(base / ("previous-" + uuid.uuid4().hex))
    stage = base / ("preparing-" + uuid.uuid4().hex)
    shutil.copytree(release, stage)
    verify_runtime(stage, bridge_source)
    stage.rename(runtime)
    return runtime


def powershell_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def prepare_terminal(runtime, directory, agent_dir, cwd, sessions, platform=None):
    platform = platform or sys.platform
    node = node_executable()
    cli = runtime / "node_modules" / PACKAGE / "dist/cli.js"
    if not cli.is_file():
        raise RuntimeError("内嵌 Pi 命令行入口缺失，请恢复内核")
    scripts = directory / "pi-console" / "launchers"
    scripts.mkdir(parents=True, exist_ok=True)
    if platform == "win32":
        script = scripts / (uuid.uuid4().hex + ".ps1")
        quote = powershell_literal
        script.write_text(
            "$env:PI_CODING_AGENT_DIR=" + quote(agent_dir) + "\n"
            "$env:PI_CODING_AGENT_SESSION_DIR=" + quote(sessions) + "\n"
            "Remove-Item Env:NODE_OPTIONS,Env:NODE_PATH -ErrorAction SilentlyContinue\n"
            "Set-Location -LiteralPath " + quote(cwd) + "\n"
            "function global:pi { & " + quote(node) + " " + quote(cli) + " @args }\n"
            "Write-Host 'Umeko embedded Pi: pi config / pi install / pi list / pi remove'\n"
            "Write-Host 'Exit configuration to return to this terminal.'\n"
            "$previousOffline = $env:PI_OFFLINE\n$env:PI_OFFLINE='1'\n"
            "try { pi config } finally { $env:PI_OFFLINE=$previousOffline }\n", encoding="utf-8-sig")
        shell = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
        if not shell:
            raise RuntimeError("未找到 PowerShell，请检查本机终端")
        return [shell, "-NoLogo", "-NoProfile", "-NoExit", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    script = scripts / (uuid.uuid4().hex + ".bashrc")
    script.write_text(
        "export PI_CODING_AGENT_DIR=" + shlex.quote(str(agent_dir)) + "\n"
        "export PI_CODING_AGENT_SESSION_DIR=" + shlex.quote(str(sessions)) + "\n"
        "unset NODE_OPTIONS NODE_PATH\ncd -- " + shlex.quote(str(cwd)) + "\n"
        "pi() { " + shlex.quote(node) + " " + shlex.quote(str(cli)) + ' "$@"; }\n'
        "printf '%s\\n' 'Umeko embedded Pi: pi config / pi install / pi list / pi remove'\n"
        "PI_OFFLINE=1 pi config\n", encoding="utf-8")
    command = ["/bin/bash", "--noprofile", "--rcfile", str(script), "-i"]
    if platform == "darwin":
        escaped = shlex.join(command).replace("\\", "\\\\").replace('"', '\\"')
        return ["/usr/bin/osascript", "-e", 'tell application "Terminal"\nactivate\ndo script "' + escaped + '"\nend tell']
    for name, flags in (("x-terminal-emulator", ["-e"]), ("gnome-terminal", ["--"]),
                        ("konsole", ["--separate", "-e"]), ("xfce4-terminal", ["--disable-server", "--execute"]), ("xterm", ["-e"])):
        terminal = shutil.which(name)
        if terminal:
            return [terminal, *flags, *command]
    raise RuntimeError("未找到可用终端，请安装并配置本机终端模拟器")


def launch_terminal(command):
    options = {"creationflags": subprocess.CREATE_NEW_CONSOLE} if os.name == "nt" else {"start_new_session": True}
    # A visible console is intentional: this is the user's explicit terminal action.
    return subprocess.Popen(command, **options)
