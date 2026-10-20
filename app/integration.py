"""Compatibility contract for explicit legacy adapter overrides. New providers use the SDK."""
from __future__ import annotations

import importlib
import os
from typing import Protocol
from umeko_provider_sdk import Completion, ProviderError


IntegrationRequired = ProviderError


class InternalAdapter(Protocol):
    def authenticate(self, employee_id: str, password: str) -> None: ...
    def complete(self, model: str, messages: list[dict], tools: list[dict], max_tokens: int) -> Completion: ...


class UnconfiguredAdapter:
    ready = False
    def authenticate(self, employee_id, password):
        raise IntegrationRequired("请先导入自定义供应商实现，再登录账号")

    def complete(self, model, messages, tools, max_tokens):
        raise IntegrationRequired("请先导入自定义供应商，或添加 API 供应商")


def load_adapter(directory=None, profile=None) -> InternalAdapter:
    entry = os.environ.get("CODEAGENT_ADAPTER", "")
    if not entry:
        return UnconfiguredAdapter()
    module, factory = entry.split(":", 1)
    return getattr(importlib.import_module(module), factory)()
