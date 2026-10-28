"""Install a pasted Pi package command through the bundled CLI, without a shell."""
import os
import re
import shlex
import signal
import subprocess
import tempfile
from pathlib import Path

from .pi_runtime import CREATE_NO_WINDOW, PACKAGE, node_executable, node_environment
from .npm_config import npm_environment


def parse_install_command(command, local=False):
    command = command.strip()
    if not command or len(command) > 4096 or any(c in command for c in "\r\n\x00;&|`$"):
        raise ValueError("请粘贴一条 pi install 命令，例如 pi install npm:billion-context")
    try:
        # Non-POSIX tokenization preserves backslashes in quoted Windows paths.
        lexer = shlex.shlex(command, posix=False)
        lexer.whitespace_split, lexer.commenters = True, ""
        tokens = list(lexer)
    except ValueError:
        raise ValueError("安装命令的引号不完整") from None
    if tokens[:2] == ["pi", "install"]:
        tokens = tokens[2:]
    sources = []
    for token in tokens:
        if token in ("-l", "--local"):
            local = True
        else:
            sources.append(token[1:-1] if token[0] in "\"'" and token[-1] == token[0] else token)
    if len(sources) != 1 or not sources[0] or sources[0].startswith("-"):
        raise ValueError("一次安装一个扩展；支持 pi install <来源> 和 --local / -l")
    return sources[0], bool(local)


def _log_tail(log):
    log.seek(0, os.SEEK_END)
    log.seek(max(0, log.tell() - 6000))
    text = log.read().decode("utf-8", errors="replace")
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    text = re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1***@", text)
    return text.strip()[-2000:]


def install_package(release, cwd, agent_dir, source, local=False, timeout=180, npm_config=None):
    return package_operation(release, cwd, agent_dir, source, local, timeout, npm_config, operation="install")


def remove_package(release, cwd, agent_dir, source, local=False, timeout=180, npm_config=None, package_root=None):
    # Native relative package registrations are relative to their settings file,
    # while CLI local source parsing is relative to the working directory.
    base = Path(cwd) / ".pi" if local else Path(agent_dir)
    if source in (".", "..") or source.startswith(("./", "../", ".\\", "..\\")) or (
            package_root and (base / source).resolve() == Path(package_root).resolve()):
        source = str((base / source).resolve())
    return package_operation(release, cwd, agent_dir, source, local, timeout, npm_config, operation="remove")


def package_operation(release, cwd, agent_dir, source, local=False, timeout=180, npm_config=None, *, operation):
    if operation not in ("install", "remove"):
        raise ValueError("Unsupported package operation")
    environment = npm_environment(npm_config or {})
    environment.update(PI_CODING_AGENT_DIR=str(agent_dir), PI_SKIP_VERSION_CHECK="1", NO_COLOR="1")
    for key in ("NODE_OPTIONS", "NODE_PATH", "PI_OFFLINE"):
        environment.pop(key, None)
    # Explicit scope avoids the CLI's interactive project-trust prompt/hooks.
    args = [node_executable(), str(Path(release) / "node_modules" / PACKAGE / "dist/cli.js"),
            operation, source, "--approve" if local else "--no-approve"]
    if local: args.append("--local")
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(args, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW,
            start_new_session=os.name != "nt")
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # npm/git are descendants of Pi; stop the whole owned process group.
            try:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=10)
                else:
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
            finally:
                process.kill()
                process.wait(timeout=10)
            raise RuntimeError(("安装" if operation == "install" else "卸载") + "超时，请检查软件源或网络后重试") from None
        output = _log_tail(log)
    if code:
        raise RuntimeError("Pi " + ("安装" if operation == "install" else "卸载") + "失败：" + (output or "退出码 " + str(code)))
    return output
