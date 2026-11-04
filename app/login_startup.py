"""One per-user login registration for Umeko and its internal proxy.

Uses the same native registration approach as Tauri's autostart plugin:
HKCU Run, a user LaunchAgent, or an XDG autostart desktop entry. No shell,
service, or separate preference is involved; the registered arguments are
the source of truth. Importing this module never changes login items.
"""

import configparser
import ntpath
import os
from pathlib import Path
import plistlib
import subprocess
import sys
from xml.parsers.expat import ExpatError


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
LOGIN_FLAG = "--login-startup"
UMEKO_FLAG = "--login-umeko"
PROXY_FLAG = "--login-proxy"


def _windows_argv(command):
    """Read the Windows quoting rules used by subprocess.list2cmdline."""
    result, index = [], 0
    while index < len(command):
        while index < len(command) and command[index] in " \t":
            index += 1
        if index == len(command):
            break
        token, quoted = [], False
        while index < len(command) and (quoted or command[index] not in " \t"):
            slashes = 0
            while index < len(command) and command[index] == "\\":
                slashes += 1
                index += 1
            if index < len(command) and command[index] == '"':
                token.extend("\\" * (slashes // 2))
                if slashes % 2:
                    token.append('"')
                else:
                    quoted = not quoted
                index += 1
            else:
                token.extend("\\" * slashes)
                if index < len(command) and (quoted or command[index] not in " \t"):
                    token.append(command[index])
                    index += 1
        if quoted:
            return []
        result.append("".join(token))
    return result


def _desktop_exec(argv):
    # Desktop Entry strings are unescaped once before Exec quoting is undone.
    parts = []
    for arg in argv:
        arg = arg.replace("%", "%%")
        arg = "".join("\\" + char if char in '\\"`$' else char for char in arg)
        parts.append('"' + arg.replace("\\", "\\\\") + '"')
    return " ".join(parts)


def _desktop_argv(value):
    decoded, index = [], 0
    escapes = {"s": " ", "n": "\n", "t": "\t", "r": "\r", "\\": "\\"}
    while index < len(value):
        char = value[index]
        if char == "\\":
            index += 1
            if index == len(value) or value[index] not in escapes:
                return []
            char = escapes[value[index]]
        decoded.append(char)
        index += 1
    value = "".join(decoded)
    result, token, quoted, active, index = [], [], False, False, 0
    while index < len(value):
        char = value[index]
        if char == '"':
            quoted, active = not quoted, True
        elif char == "\\":
            index += 1
            if index == len(value) or value[index] not in '\\"`$':
                return []
            token.append(value[index])
            active = True
        elif char.isspace() and not quoted:
            if active:
                result.append("".join(token))
                token, active = [], False
        elif char == "%":
            index += 1
            if index == len(value) or value[index] != "%":
                return []
            token.append("%")
            active = True
        else:
            token.append(char)
            active = True
        index += 1
    if quoted:
        return []
    if active:
        result.append("".join(token))
    return result


class LoginStartup:
    """Read or change the current user's single Umeko login item.

    Tests inject a registry or home directory. Source launches are deliberately
    unavailable, including refresh, so Python interpreters are never registered.
    OS access errors propagate to the caller for presentation in the UI.
    """

    def __init__(self, platform=None, executable=None, frozen=None, registry=None,
                 home=None, environ=None, value_name="Umeko"):
        self.platform = sys.platform if platform is None else platform
        self.environ = os.environ if environ is None else environ
        appimage = self.environ.get("APPIMAGE") if self.platform.startswith("linux") else None
        self.executable = str(executable if executable is not None else (appimage or sys.executable))
        self.frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
        self.registry = registry
        self.home = Path.home() if home is None else Path(home)
        self.value_name = value_name
        if not value_name or any(char in value_name for char in "/\\\r\n\0"):
            raise ValueError("无效的登录启动项名称")

    def _reason(self):
        if not self.frozen:
            return "开机启动仅适用于打包后的应用。"
        if self.platform not in ("win32", "darwin") and not self.platform.startswith("linux"):
            return "当前系统不支持开机启动。"
        return ""

    def _file(self):
        if self.platform == "darwin":
            return self.home / "Library" / "LaunchAgents" / (self.value_name + ".plist")
        config = self.environ.get("XDG_CONFIG_HOME", "")
        base = Path(config) if config and Path(config).is_absolute() else self.home / ".config"
        return base / "autostart" / (self.value_name.lower() + ".desktop")

    def _winreg(self):
        if self.registry is None:
            import winreg
            self.registry = winreg
        return self.registry

    def _read(self):
        if self.platform == "win32":
            registry = self._winreg()
            try:
                with registry.OpenKey(registry.HKEY_CURRENT_USER, RUN_KEY, 0, registry.KEY_READ) as key:
                    command, kind = registry.QueryValueEx(key, self.value_name)
            except FileNotFoundError:
                return []
            return _windows_argv(command) if kind == registry.REG_SZ and isinstance(command, str) else []
        try:
            data = self._file().read_bytes()
        except FileNotFoundError:
            return []
        if self.platform == "darwin":
            try:
                entry = plistlib.loads(data)
            except (ValueError, plistlib.InvalidFileException, ExpatError):
                return []
            if not isinstance(entry, dict) or entry.get("Disabled", False) or entry.get("RunAtLoad") is not True:
                return []
            return entry.get("ProgramArguments", [])
        try:
            parser = configparser.ConfigParser(interpolation=None)
            parser.read_string(data.decode("utf-8"))
            entry = parser["Desktop Entry"]
            if entry.get("Type") != "Application" or entry.getboolean("Hidden", False):
                return []
            if not entry.getboolean("X-GNOME-Autostart-enabled", True):
                return []
            return _desktop_argv(entry.get("Exec", ""))
        except (configparser.Error, KeyError, ValueError, UnicodeError):
            return []

    def _flags(self, argv):
        if not isinstance(argv, list) or not all(isinstance(arg, str) for arg in argv):
            return False, False
        if len(argv) < 3 or not argv[0] or argv[1] != LOGIN_FLAG:
            return False, False
        if not (ntpath.isabs(argv[0]) if self.platform == "win32" else argv[0].startswith("/")):
            return False, False
        flags = argv[2:]
        if len(flags) != len(set(flags)) or any(arg not in (UMEKO_FLAG, PROXY_FLAG) for arg in flags):
            return False, False
        return UMEKO_FLAG in flags, PROXY_FLAG in flags

    def state(self):
        reason = self._reason()
        umeko, proxy = (False, False) if reason else self._flags(self._read())
        return {"available": not bool(reason), "reason": reason, "umeko": umeko, "proxy": proxy}

    def refresh(self):
        """Update a moved/upgraded executable only while registration is enabled."""
        if self._reason():
            return self.state()
        argv = self._read()
        umeko, proxy = self._flags(argv)
        if (umeko or proxy) and argv[0] != self.executable:
            self._write(umeko, proxy)
        return {"available": True, "reason": "", "umeko": umeko, "proxy": proxy}

    def set_enabled(self, umeko, proxy):
        if not self._reason():
            self._write(bool(umeko), bool(proxy))
        return self.state()

    def _write(self, umeko, proxy):
        absolute = ntpath.isabs(self.executable) if self.platform == "win32" else self.executable.startswith("/")
        if (umeko or proxy) and (not absolute or any(char in self.executable for char in "\0\r\n\t")):
            raise ValueError("无法确定应用程序路径")
        if (umeko or proxy) and self.platform.startswith("linux") and "=" in self.executable:
            raise ValueError("应用程序路径不支持登录启动")
        argv = [self.executable, LOGIN_FLAG]
        if umeko:
            argv.append(UMEKO_FLAG)
        if proxy:
            argv.append(PROXY_FLAG)
        enabled = umeko or proxy
        if self.platform == "win32":
            registry = self._winreg()
            if enabled:
                command = subprocess.list2cmdline(argv)
                if len(command) > 260:
                    raise ValueError("登录启动命令超过 Windows 支持的长度")
                with registry.CreateKeyEx(registry.HKEY_CURRENT_USER, RUN_KEY, 0, registry.KEY_SET_VALUE) as key:
                    registry.SetValueEx(key, self.value_name, 0, registry.REG_SZ, command)
            else:
                try:
                    with registry.OpenKey(registry.HKEY_CURRENT_USER, RUN_KEY, 0, registry.KEY_SET_VALUE) as key:
                        registry.DeleteValue(key, self.value_name)
                except FileNotFoundError:
                    pass
            return
        path = self._file()
        if not enabled:
            path.unlink(missing_ok=True)
            return
        if self.platform == "darwin":
            data = plistlib.dumps({"Label": self.value_name, "ProgramArguments": argv, "RunAtLoad": True})
        else:
            data = ("[Desktop Entry]\nType=Application\nName=Umeko\nExec=" + _desktop_exec(argv)
                    + "\nTerminal=false\nHidden=false\n").encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
