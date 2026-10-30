"""Provider context metadata, offline suggestions and per-model overrides."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

DEFAULT_CONTEXT = 128000
MIN_CONTEXT = 1024
MAX_CONTEXT = 16 * 1024 * 1024

# Specific capacity labels take priority over family defaults. Boundaries avoid
# treating parameter counts, version numbers or fragments such as "k30" as K3.
_CAPACITY = re.compile(r"(?:^|-)(\d+(?:\.\d+)?)([km])(?=$|-)")
_FAMILIES = (
    (r"(?:^|-)k3-256k?(?=$|-)", 262144),
    (r"(?:^|-)k3(?=$|-(?!\d))", 1048576),
    (r"(?:^|-)kimi-for-coding-highspeed(?=$|-)", 262144),
    (r"(?:^|-)kimi-for-coding(?=$|-)", 1048576),
    (r"(?:^|-)kimi-k2\.[57](?=$|-)", 262144),
    (r"(?:^|-)kimi-k2\.8(?=$|-)", 1048576),
    (r"(?:^|-)deepseek-v4(?:\.1)?-(?:flash|pro)(?=$|-)", 1048576),
    (r"(?:^|-)gpt-4\.1(?=$|-)", 1047576),
    (r"(?:^|-)gpt-4o(?=$|-)", 128000),
    (r"(?:^|-)claude-(?:sonnet|opus)-4-6(?=$|-)", 1000000),
    (r"(?:^|-)claude-(?:sonnet|opus|haiku)-4-5(?=$|-)", 200000),
    (r"(?:^|-)gemini-2\.5-(?:pro|flash)(?=$|-)", 1048576),
)
_FAMILIES = tuple((re.compile(pattern), tokens) for pattern, tokens in _FAMILIES)

# Recognized model-list fields only: output limits (max_tokens, max_output_tokens)
# are deliberately excluded. Multiple advertised input limits use the smaller cap.
_PROVIDER_CONTEXT_KEYS = (
    "providerContextWindow", "contextWindow", "max_model_len", "context_length",
    "context_window", "max_context_length", "max_input_tokens", "inputTokenLimit",
)
_PROVIDER_CONTEXT_CONTAINERS = ("top_provider", "limits", "capabilities", "model_info", "metadata", "parameters")


def _parse_provider_context_window(value) -> int:
    """Provider capacities are positive JS-safe tokens, not editable UI values."""
    message = "供应商上下文上限必须为正安全整数 / Provider context limit must be a positive safe integer"
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(message)
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError(message)
        value = int(value)
    if not re.fullmatch(r"\s*\d+\s*", str(value)):
        raise ValueError(message)
    tokens = int(value)
    if not 0 < tokens < (1 << 53) - 1:
        raise ValueError(message)
    return tokens


def provider_context_window(model: dict) -> int | None:
    """Read supported provider model-list shapes, ignoring malformed metadata."""
    values = []

    def collect(row, depth=0):
        if not isinstance(row, dict) or depth > 3:
            return
        for key in _PROVIDER_CONTEXT_KEYS:
            if key in row:
                try:
                    values.append(_parse_provider_context_window(row[key]))
                except ValueError:
                    pass
        for key in _PROVIDER_CONTEXT_CONTAINERS:
            collect(row.get(key), depth + 1)

    collect(model)
    return min(values) if values else None


def parse_context_window(value) -> int:
    """Accept tokens or binary K/M shorthand without truncating decimals."""
    message = "上下文长度请输入 1024–16777216 的整数 token，也可填写 256K、1M"
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(message)
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kKmM]?)\s*", str(value))
    if not match:
        raise ValueError(message)
    try:
        amount = Decimal(match[1]) * {"": 1, "k": 1024, "m": 1048576}[match[2].lower()]
        if amount != amount.to_integral_value() or not MIN_CONTEXT <= amount <= MAX_CONTEXT:
            raise ValueError(message)
        return int(amount)
    except InvalidOperation as exc:
        raise ValueError(message) from exc


def context_suggestion(model_name: str) -> dict:
    name = re.sub(r"[\s_/:]+", "-", str(model_name).strip().lower())
    # The last capacity label is the closest override (e.g. a gateway suffix).
    for match in reversed(list(_CAPACITY.finditer(name))):
        try:
            return {"tokens": parse_context_window(match[1] + match[2]), "matched": True}
        except ValueError:
            pass
    for pattern, tokens in _FAMILIES:
        if pattern.search(name):
            return {"tokens": tokens, "matched": True}
    return {"tokens": DEFAULT_CONTEXT, "matched": False}


def normalize_context(model: dict, previous: dict | None = None) -> dict:
    """Legacy rows are automatic; explicit old values remain custom overrides.

    Older clients may omit both new fields when renaming an alias. Preserve an
    existing override in that case, but recalculate automatic values by the new
    upstream name. Never infer from the display alias.
    """
    source = model
    if "contextWindow" not in model and "contextWindowAuto" not in model:
        source = previous or model
    automatic = source.get("contextWindowAuto", "contextWindow" not in source)
    if not isinstance(automatic, bool):
        raise ValueError("上下文长度的自动设置必须为 true 或 false")
    # When editing a saved row, only the server's previous metadata is trusted.
    # Discovery calls normalize_context without previous after parsing its response.
    reported_source = previous if previous is not None else model
    if previous is not None and previous.get("upstream", model.get("upstream")) != model.get("upstream"):
        reported_source = {}
    reported = reported_source.get("providerContextWindow")
    reported = _parse_provider_context_window(reported) if reported is not None else None
    tokens = (reported or context_suggestion(model.get("upstream", ""))["tokens"]) if automatic else parse_context_window(source.get("contextWindow"))
    result = {"contextWindow": tokens, "contextWindowAuto": automatic}
    if reported is not None:
        result["providerContextWindow"] = reported
    return result
