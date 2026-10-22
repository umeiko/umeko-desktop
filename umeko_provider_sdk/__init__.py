"""Public Provider API v1. This package has no Umeko application imports."""
from __future__ import annotations

import codecs
import json
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Any, Protocol

SDK_VERSION = "0.2.1"
API_VERSION = 1


class ProviderError(RuntimeError):
    """A short user-facing error. Never include credentials or raw auth responses."""


@dataclass
class Completion:
    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str = "stop"
    thinking: str = ""


class Secrets(Protocol):
    def get(self, name: str, default=None): ...
    def set(self, name: str, value: Any) -> None: ...
    def delete(self, name: str) -> None: ...


@dataclass
class ProviderContext:
    config: dict
    state_dir: Path
    secrets: Secrets
    cancelled: Event = field(default_factory=Event)


class Provider:
    def __init__(self, context: ProviderContext): self.context = context
    def authenticate(self, credentials: dict[str, str]) -> dict:
        """Return public account details; persist tokens with context.secrets."""
        raise NotImplementedError
    def list_models(self, refresh: bool = False) -> list[dict]:
        """Each model needs id; contextWindow and vision are optional metadata."""
        raise NotImplementedError
    def events(self, model: str, messages: list[dict], tools: list[dict], max_tokens: int, parameters: dict):
        """Yield OpenAI-compatible JSON chunks, including usage-only chunks."""
        raise NotImplementedError
    def close(self): self.context.cancelled.set()


def iter_sse(chunks):
    decoder = codecs.getincrementaldecoder("utf-8")()
    buffer, lines = "", []
    for chunk in chunks:
        buffer += decoder.decode(chunk) if isinstance(chunk, bytes) else chunk
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.rstrip("\r")
            if not line:
                if lines:
                    value = "\n".join(lines)
                    if value == "[DONE]": return
                    yield json.loads(value)
                    lines = []
            elif line.startswith("data:"): lines.append(line[5:].lstrip(" "))
    buffer += decoder.decode(b"", final=True)
    if buffer.startswith("data:"): lines.append(buffer[5:].strip())
    if lines and "\n".join(lines) != "[DONE]": yield json.loads("\n".join(lines))


def response_events(response):
    if "event-stream" not in response.headers.get("Content-Type", ""):
        raw = response.read(16 * 1024 * 1024)
        if raw.lstrip().startswith(b"{"): yield json.loads(raw)
        else: yield from iter_sse([raw])
        return
    yield from iter_sse(iter(response.readline, b""))


def collect_openai(events):
    text, thinking, calls, usage, finish, model = [], [], {}, {}, "stop", ""
    for event in events:
        if event.get("error"): raise ProviderError("上游返回错误，请检查供应商配置与权限")
        model = event.get("model", model)
        usage.update(event.get("usage") or {})
        for choice in event.get("choices") or []:
            delta = choice.get("delta") or choice.get("message") or {}
            if delta.get("content"): text.append(delta["content"])
            reason = delta.get("reasoning_content") or delta.get("reasoning") or delta.get("reasoning_text")
            if reason: thinking.append(reason)
            for index, call in enumerate(delta.get("tool_calls") or []):
                slot = calls.setdefault(call.get("index", index), {"id":"", "type":"function", "function":{"name":"", "arguments":""}})
                slot["id"] += call.get("id") or ""
                function = call.get("function") or {}
                slot["function"]["name"] += function.get("name") or ""
                slot["function"]["arguments"] += function.get("arguments") or ""
            finish = choice.get("finish_reason") or finish
    message = {"role":"assistant", "content":"".join(text)}
    if thinking: message["reasoning_content"] = "".join(thinking)
    if calls: message["tool_calls"] = [calls[i] for i in sorted(calls)]
    return {"object":"chat.completion", "model":model, "choices":[{"index":0, "message":message, "finish_reason":finish}], "usage":usage}


# Include common standard-library transports in frozen hosts as well as source runs.
from .http import HttpSession, ConsentForm, response_cookies
