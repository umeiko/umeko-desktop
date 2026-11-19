"""Public Provider API v1. This package has no Umeko application imports."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Any, Callable, Protocol

SDK_VERSION = "0.2.1"
API_VERSION = 1
_request_cancelled: ContextVar[Event | None] = ContextVar("umeko_request_cancelled", default=None)


@contextmanager
def request_scope(cancelled: Event):
    """Expose one request's cancellation event without changing Provider API v1.

    The host wraps the complete provider call/stream iteration in this scope.
    Providers should capture context.request_cancelled before starting workers.
    """
    token = _request_cancelled.set(cancelled)
    try:
        yield cancelled
    finally:
        _request_cancelled.reset(token)


def current_request_cancelled() -> Event:
    """Host transports can share the current request's cooperative stop event."""
    event = _request_cancelled.get()
    return Event() if event is None else event


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
    profile_dir: Path | None = None
    downloads_dir: Path | None = None
    language: str = "zh"
    notify: Callable[[dict], None] | None = None
    report_status: Callable[[str], None] | None = None

    @property
    def request_cancelled(self) -> Event:
        """Current request event; outside a scope, use the instance close event."""
        event = _request_cancelled.get()
        return self.cancelled if event is None else event


class Provider:
    def __init__(self, context: ProviderContext): self.context = context
    def card_actions(self) -> list[dict]:
        """Local, nonblocking public buttons: key, label, optional url and hint."""
        return []
    def card_action(self, key: str) -> dict:
        """Handle a user click; return public message, url and/or refreshModels.

        Only the host opens a returned public HTTP(S) URL. Never include secrets.
        """
        raise ProviderError("该供应商不支持此操作")
    def card_status(self) -> str:
        """Return a public status message, locally and without blocking."""
        return ""
    def card_fields(self) -> list[dict]:
        """Public extra-secret descriptors; return [] until they should be shown.

        Each descriptor has key, label, optional hint/link/message and hasValue.
        Never return secret values. This accessor must be local and nonblocking.
        """
        return []
    def set_card_secret(self, key: str, value: str) -> dict:
        """Update a card field using context.secrets; return a public message.

        The host refreshes list_models after this management operation.
        """
        raise ProviderError("该供应商不支持额外密钥字段")
    def authenticate(self, credentials: dict[str, str]) -> dict:
        """Return public account details; persist tokens with context.secrets.

        During sign-in, observe context.request_cancelled to stop cooperatively.
        Hosts may provide context.report_status for short public progress text.
        """
        raise NotImplementedError
    def list_models(self, refresh: bool = False) -> list[dict]:
        """Each model needs id; contextWindow and vision are optional metadata."""
        raise NotImplementedError
    def events(self, model: str, messages: list[dict], tools: list[dict], max_tokens: int, parameters: dict):
        """Yield OpenAI-compatible JSON chunks, including usage-only chunks."""
        raise NotImplementedError
    def generate_image(self, model: str, prompt: str, parameters: dict) -> list[dict]:
        """Optional generation extension; return [{data: bytes, mimeType: str}].

        Advertise 'image' in manifest.generationCapabilities. Observe both
        context.request_cancelled and context.cancelled during network work.
        Old API v1 providers inherit an explicit unsupported result.
        """
        raise ProviderError('该供应商不支持图片生成')
    def generate_speech(self, model: str, text: str, parameters: dict) -> list[dict]:
        """Optional speech extension, with the same bytes/cancellation contract.

        Advertise 'speech' in manifest.generationCapabilities. Credentials must
        remain in context.secrets, as for streaming inference.
        """
        raise ProviderError('该供应商不支持语音生成')
    def generate_video(self, model: str, prompt: str, parameters: dict, on_progress=None) -> list[dict]:
        """Optional video extension returning [{data: bytes, mimeType: 'video/mp4'}].

        Advertise 'video' in manifest.generationCapabilities. Report public
        {id, status, progress} values through on_progress when provided. Observe
        context.request_cancelled throughout polling and downloading, stop after
        cancellation, and attempt remote cleanup when the provider supports it.
        """
        raise ProviderError('该供应商不支持视频生成')
    def close(self): self.context.cancelled.set()


from .streaming import iter_sse, response_events, collect_openai, normalize_openai_events


# Include common standard-library transports in frozen hosts as well as source runs.
from .http import HttpSession, ConsentForm, response_cookies
