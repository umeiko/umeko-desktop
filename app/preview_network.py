"""Preview subprocess adapter for the updater's route and certificate policy."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile


NETWORK_MESSAGES = {
    "certificate": ("证书问题", "请检查系统时间，并将组织的根证书安装到系统受信任的根证书存储后重试。"),
    "proxy": ("代理问题", "请检查系统或环境中的代理地址与认证设置。预览版依赖下载需要 HTTP 代理或直连；不使用供应商代理。"),
    "dns": ("DNS 问题", "请检查系统 DNS 和代理设置，确认能解析下载服务后重试。"),
    "timeout": ("连接超时", "请检查网络连通性或代理设置，然后重新检查运行前提。"),
    "other": ("其他网络问题", "请检查网络设置和所需工具是否可用，然后重新检查运行前提。"),
}
UNSUPPORTED_PROXY_HINT = "依赖下载脚本不支持 SOCKS 或 HTTPS 代理；请使用 HTTP 代理或可用的直连。"


class PreviewNetwork:
    def __init__(self, environment, run, *, python=None, cwd=None):
        self.environment = dict(environment)
        self.run = run
        self.temporary = tempfile.TemporaryDirectory(prefix="umeko-preview-network-")
        self.directory = Path(self.temporary.name)
        self.result = None
        self.tools = {key: str(value) for key, value in {"python": python, "cwd": cwd}.items() if value}

    def _command(self, mode, file):
        from .pi_runtime import node_executable
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
        return [node_executable(), str(root / "runtime/preview-network.mjs"), mode, str(file)]

    def probe(self):
        configuration = self.directory / "tools.json"
        configuration.write_text(json.dumps(self.tools), encoding="utf-8")
        self.result = json.loads(self.run([*self._command("probe", self.directory / "ca.pem"), str(configuration)]))
        if not isinstance(self.result, dict) or type(self.result.get("ok")) is not bool:
            raise ValueError("Invalid Preview network result")
        return self.result

    def apply(self, environment):
        if not self.result or not self.result["ok"]:
            return dict(environment)
        removed = {key.lower() for key in self.result.get("removeEnvironment", [])}
        result = {key: value for key, value in environment.items() if key.lower() not in removed}
        result.update(self.result["environment"])
        return result

    def classify(self, detail):
        file = self.directory / "failure.txt"
        try:
            file.write_text(detail[-65536:], encoding="utf-8")
            file.chmod(0o600)
            value = json.loads(self.run(self._command("classify", file)))
            category = value.get("category", "other")
            return category if category in NETWORK_MESSAGES else "other"
        finally:
            file.unlink(missing_ok=True)

    def close(self):
        self.temporary.cleanup()


def network_failure(category, attempts=()):
    category = category if category in NETWORK_MESSAGES else "other"
    label, hint = NETWORK_MESSAGES[category]
    result = {"category": category, "detail": label, "hint": hint}
    if any(attempt.get("code") == "PREVIEW_PROXY_UNSUPPORTED" for attempt in attempts):
        result["limitation"] = UNSUPPORTED_PROXY_HINT
    return result
