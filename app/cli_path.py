"""Expose the packaged CLI to the current user's terminal."""
from __future__ import annotations

import ntpath
import os
from pathlib import Path
import shlex
import stat
import sys
from tempfile import NamedTemporaryFile


WINDOWS_CLI = "Umeko-cli.exe"
_START = "# >>> Umeko CLI PATH >>>"
_END = "# <<< Umeko CLI PATH <<<"


def packaged_cli():
    if not getattr(sys, "frozen", False):
        return None
    executable = Path(sys.executable).resolve()
    if sys.platform == "win32":
        launcher = executable.with_name(WINDOWS_CLI)
    elif sys.platform == "darwin":
        launcher = executable.parent.parent / "Resources/umeko"
    else:
        launcher = executable.with_name("umeko")
    return launcher if launcher.is_file() and os.access(launcher, os.X_OK) else None


def configure_path(launcher):
    directory = str(launcher.parent)
    if any(character in directory for character in ("\n", "\r", os.pathsep)):
        raise ValueError(directory)
    if sys.platform == "win32":
        _configure_windows(directory)
        return

    shell = os.environ.get("SHELL")
    if not shell:
        import pwd
        shell = pwd.getpwuid(os.getuid()).pw_shell
    home = Path.home()
    quoted = shlex.quote(directory)
    command = (
        'case ":${PATH-}:" in\n'
        f'    *:{quoted}:*) ;;\n'
        f'    *) export PATH={quoted}"${{PATH:+:$PATH}}" ;;\n'
        f'esac'
    )
    match Path(shell).name:
        case "zsh":
            files = [Path(os.environ.get("ZDOTDIR") or home) / ".zshrc"]
        case "bash":
            profiles = [home / name for name in (".bash_profile", ".bash_login", ".profile")]
            login = next((path for path in profiles if path.exists()), profiles[-1])
            files = [home / ".bashrc", login]
        case "fish":
            config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
            files = [config / "fish/conf.d/umeko-cli-path.fish"]
            quoted = "'" + directory.replace("\\", "\\\\").replace("'", "\\'") + "'"
            command = f"if not contains -- {quoted} $PATH\n    set -gx PATH {quoted} $PATH\nend"
        case _:
            raise ValueError(shell)
    for path in files:
        _configure_shell_file(path, command)


def _configure_windows(directory):
    import ctypes
    from ctypes import wintypes
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, "Environment", 0,
                            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as key:
        try:
            value, kind = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            value, kind = "", winreg.REG_EXPAND_SZ
        if kind not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
            raise ValueError("HKCU\\Environment\\Path")

        def normalize(entry):
            entry = entry.strip().strip('"')
            if kind == winreg.REG_EXPAND_SZ:
                entry = winreg.ExpandEnvironmentStrings(entry)
            return ntpath.normcase(ntpath.normpath(entry))

        entries = value.split(";") if value else []
        target = normalize(directory)
        matching, other = [], []
        for entry in entries:
            (matching if normalize(entry) == target else other).append(entry)
        updated = ";".join([matching[0] if matching else directory, *other])
        if updated == value:
            return
        winreg.SetValueEx(key, "Path", 0, kind, updated)

    # Ask Explorer to refresh the environment inherited by new terminals.
    try:
        notify = ctypes.WinDLL("user32").SendMessageTimeoutW
        notify.argtypes = (
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPCWSTR,
            wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
        )
        notify(0xFFFF, 0x001A, 0, "Environment", 0x0002, 1000, None)
    except OSError:
        pass


def _configure_shell_file(path, command):
    # Follow dotfile symlinks so replacing the file keeps the symlink intact.
    path = path.expanduser().resolve()
    try:
        current = path.read_bytes()
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        current, mode = b"", 0o600
    start, end = _START.encode(), _END.encode()
    lines = current.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.rstrip(b"\r\n") == start]
    ends = [i for i, line in enumerate(lines) if line.rstrip(b"\r\n") == end]
    block = f"{_START}\n{command}\n{_END}\n".encode()
    if not starts and not ends:
        separator = b"\n" if current and not current.endswith(b"\n") else b""
        updated = current + separator + block
    elif len(starts) == len(ends) == 1 and starts[0] < ends[0]:
        updated = b"".join(lines[:starts[0]]) + block + b"".join(lines[ends[0] + 1:])
    else:
        raise ValueError(str(path))
    if current == updated:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        staged = Path(temporary.name)
        try:
            temporary.write(updated)
            temporary.close()
            staged.chmod(mode)
            staged.replace(path)
        finally:
            staged.unlink(missing_ok=True)
