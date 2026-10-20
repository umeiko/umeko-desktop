"""Offline model-name suggestions and persistent per-model context overrides.

These are defaults, not provider capability discovery. A deployment or account
can impose a smaller limit; an explicit user value always wins. See README for
the dated sources behind the small family table.
"""
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
    tokens = context_suggestion(model.get("upstream", ""))["tokens"] if automatic else parse_context_window(source.get("contextWindow"))
    return {"contextWindow": tokens, "contextWindowAuto": automatic}
