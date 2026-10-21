"""Per-application npm overrides; never modify a user's global npm configuration."""
import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .pi_runtime import CREATE_NO_WINDOW, node_environment, npm_command

ENV_KEYS = {"npmRegistry": "npm_config_registry", "npmUserconfig": "npm_config_userconfig", "npmCafile": "npm_config_cafile"}


def validate_npm_config(values):
    if not isinstance(values, dict) or any(not isinstance(values.get(key, ""), str) for key in ENV_KEYS):
        raise ValueError("npm 配置格式无效")
    result = {key: values.get(key, "").strip() for key in ENV_KEYS}
    if any(any(char in value for char in "\r\n\0") for value in result.values()):
        raise ValueError("npm 配置不能包含换行或空字符")
    registry = result["npmRegistry"]
    if registry:
        try:
            url = urlsplit(registry)
            valid = url.scheme in ("http", "https") and bool(url.hostname) and not (url.username or url.password or url.query or url.fragment)
            _ = url.port
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("npm 源须为完整的 HTTP(S) 地址；登录凭据请放在 .npmrc 中")
    for key in ("npmUserconfig", "npmCafile"):
        if result[key]:
            path = Path(result[key]).expanduser().resolve()
            if not path.is_file() or not os.access(path, os.R_OK):
                raise ValueError("npm 配置文件或 CA 证书不存在或不可读")
            result[key] = str(path)
    return result


def npm_overrides(agent):
    return {environment: str(agent[key]) for key, environment in ENV_KEYS.items() if agent.get(key)}


def npm_environment(agent):
    environment = node_environment()
    overrides = npm_overrides(agent)
    for key in list(environment):
        if key.lower() in overrides: del environment[key]
    return {**environment, **overrides}


def probe_npm(agent, cwd):
    environment = npm_environment(agent)
    command = npm_command()
    result = subprocess.run([*command, "config", "get", "registry"], env=environment, cwd=cwd,
                            capture_output=True, text=True, encoding="utf-8", timeout=15, creationflags=CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError("无法读取 npm 配置，请检查 .npmrc")
    url = urlsplit(result.stdout.strip())
    host = url.netloc.rsplit("@", 1)[-1]
    registry = urlunsplit((url.scheme, host, url.path, "", ""))
    result = subprocess.run([*command, "ping", "--fetch-retries=0", "--fetch-timeout=10000"], env=environment, cwd=cwd,
                            capture_output=True, timeout=15, creationflags=CREATE_NO_WINDOW)
    origin = "Umeko 自定义源" if agent.get("npmRegistry") else "npm 原生配置"
    return f"{origin} · {registry} · " + ("连接正常" if not result.returncode else "连接失败，请检查网络、登录信息和 CA 证书")
