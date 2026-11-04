"""Reasoning effort configuration, explicit metadata, and bounded API discovery.

There are no model-name guesses here. Probe results describe values accepted by
an API; accepting the deliberately invalid value warns that the API may ignore
the parameter. A caller supplies the small request and preserves its old cache
if discovery fails for reasons unrelated to effort validation.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping


EFFORT_CANDIDATES = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
OPENROUTER_EFFORTS = EFFORT_CANDIDATES[:-1]
_RANK = {value: index for index, value in enumerate(EFFORT_CANDIDATES)}
_RANK["ultra"] = _RANK["max"]  # DeepSeek's documented alias.
_INVALID_EFFORT = "__umeko_invalid_effort__"
_STATES = {"unknown", "probing", "known", "failed"}
_EFFORT = re.compile(r"\beffort\b|reasoning[_. -]*effort", re.I)
_REJECTION = re.compile(
    r"invalid|unsupported|not supported|unknown|unrecognized|unexpected|not permitted|"
    r"not allowed|must be|should be|permitted|allowed|expected|extra.forbidden|enum", re.I)
_UNRELATED = re.compile(
    r"unauthori[sz]ed|forbidden|invalid.api.key|authentication|rate.limit|too many requests|"
    r"timed?\s*out|timeout|connection|network|quota|insufficient.{0,12}(?:credit|balance)|"
    r"max[_ ](?:output[_ ]|completion[_ ])?tokens|maximum.{0,15}tokens|context.length", re.I)


def normalize_levels(raw: object) -> list[str]:
    """Validate a configured ordered list; 'off' is a separate UI action."""
    if not isinstance(raw, list):
        raise ValueError("推理等级必须为字符串列表")
    result = []
    for value in raw:
        if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("推理等级必须为非空字符串")
        value = value.strip()
        if value != "off" and value not in result:
            result.append(value)
    return result


def _canonical_levels(raw: object) -> list[str]:
    levels = normalize_levels(raw)
    return sorted(levels, key=lambda value: _RANK.get(value, len(_RANK)))


def metadata_levels(row: object) -> list[str] | None:
    """Read only documented server fields and the explicit plugin host contract.

    None means no usable declaration, whereas [] explicitly declares no levels.
    Malformed optional remote metadata is ignored rather than guessing support.
    """
    if not isinstance(row, Mapping):
        return None
    if "reasoningLevels" in row:
        try:
            return _canonical_levels(row["reasoningLevels"])
        except ValueError:
            return None
    capabilities = row.get("capabilities")
    effort = capabilities.get("effort") if isinstance(capabilities, Mapping) else None
    if isinstance(effort, Mapping):
        if effort.get("supported") is False:
            return []
        declared = [value for value in ("low", "medium", "high", "xhigh", "max")
                    if isinstance(effort.get(value), Mapping)
                    and isinstance(effort[value].get("supported"), bool)]
        if declared:
            return [value for value in declared if effort[value].get("supported") is True]
    effort = row.get("effort")
    if isinstance(effort, Mapping):
        if isinstance(effort.get("supported_levels"), list):
            try:
                return _canonical_levels(effort["supported_levels"])
            except ValueError:
                return None
    reasoning = row.get("reasoning")
    if isinstance(reasoning, Mapping) and "supported_efforts" in reasoning:
        values = reasoning["supported_efforts"]
        if values is None:
            return list(OPENROUTER_EFFORTS)
        try:
            return _canonical_levels(values)
        except ValueError:
            return None
    return None


def _normalize_detection(raw: object) -> dict:
    if not isinstance(raw, Mapping):
        raise ValueError("推理等级检测状态必须为对象")
    state = raw.get("state", "unknown")
    if not isinstance(state, str) or state not in _STATES:
        raise ValueError("推理等级检测状态无效")
    result = {"state": state, "levels": normalize_levels(raw.get("levels", []))}
    if "rejected" in raw:
        result["rejected"] = normalize_levels(raw["rejected"])
    for name in ("source", "error"):
        if name in raw:
            if not isinstance(raw[name], str):
                raise ValueError("推理等级检测说明必须为字符串")
            result[name] = raw[name]
    for name in ("noParameter", "invalidAccepted"):
        if name in raw:
            if not isinstance(raw[name], bool):
                raise ValueError("推理等级检测标志必须为 true 或 false")
            result[name] = raw[name]
    return result


def normalize_reasoning(model: dict, previous: dict | None = None) -> dict:
    """Normalize settings without erasing fields omitted by an older editor."""
    previous = previous or {}
    automatic = model.get("reasoningLevelsAuto", previous.get(
        "reasoningLevelsAuto", "reasoningLevels" not in model and "reasoningLevels" not in previous))
    if not isinstance(automatic, bool):
        raise ValueError("推理等级的自动设置必须为 true 或 false")
    detection = _normalize_detection(model.get("reasoningDetection", previous.get(
        "reasoningDetection", {"state": "unknown", "levels": []})))
    raw_levels = model.get("reasoningLevels", previous.get("reasoningLevels", []))
    if automatic and "reasoningDetection" in model and detection["state"] == "known" \
            and "reasoningLevels" not in model:
        raw_levels = detection["levels"]
    return {"reasoningLevels": normalize_levels(raw_levels), "reasoningLevelsAuto": automatic,
            "reasoningDetection": detection}


def clamp_effort(value: object, levels: list[str]) -> str:
    """Keep a supported effort or choose the nearest supported canonical rank."""
    levels = normalize_levels(levels)
    if value == "off" or not levels:
        return "off"
    if value in levels:
        return value
    rank = _RANK.get(value) if isinstance(value, str) else None
    ranked = [level for level in levels if level in _RANK]
    if rank is None or not ranked:
        return levels[0]
    return min(ranked, key=lambda level: (abs(_RANK[level] - rank), _RANK[level]))


def effort_options(levels: list[str]) -> list[dict[str, str]]:
    return [{"value": "off", "label": "关闭"},
            *({"value": value, "label": value} for value in normalize_levels(levels))]


def _error_text(error: object) -> str:
    if isinstance(error, (Mapping, list)):
        return json.dumps(error, ensure_ascii=False, default=str)
    return str(error)


def is_effort_rejection(error: object) -> bool:
    """Distinguish effort validation from auth, transport, and token-cap failures."""
    status = getattr(error, "status_code", None)
    if status in (401, 403, 408, 429) or (isinstance(status, int) and status >= 500):
        return False
    text = _error_text(error)
    return bool(_EFFORT.search(text) and _REJECTION.search(text) and not _UNRELATED.search(text))


def _field_is_effort(value: object) -> bool:
    if isinstance(value, (list, tuple)):
        return any(_field_is_effort(part) for part in value)
    return isinstance(value, str) and bool(_EFFORT.search(value))


def _structured_allowed(value: object, effort_context: bool = False) -> list[str] | None:
    if isinstance(value, Mapping):
        context = effort_context or any(_field_is_effort(value.get(key))
                                       for key in ("param", "parameter", "field", "loc", "path"))
        for key in ("allowed", "allowed_values", "enum", "permitted", "expected"):
            candidate = value.get(key)
            if context and isinstance(candidate, list):
                try:
                    return _canonical_levels(candidate)
                except ValueError:
                    pass
        for key, child in value.items():
            found = _structured_allowed(child, context or _field_is_effort(key))
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _structured_allowed(child, effort_context)
            if found is not None:
                return found
    return None


def _validation_messages(value: object) -> list[str]:
    if isinstance(value, Mapping):
        scopes = [value[key] for key in ("param", "parameter", "field", "loc", "path") if key in value]
        messages = []
        effort_scoped = any(_field_is_effort(scope) for scope in scopes)
        if not scopes or effort_scoped:
            messages.extend(("reasoning_effort: " if effort_scoped else "") + value[key]
                            for key in ("message", "msg", "detail")
                            if isinstance(value.get(key), str))
        for child in value.values():
            if isinstance(child, (Mapping, list)):
                messages.extend(_validation_messages(child))
        return messages
    if isinstance(value, list):
        return [message for child in value for message in _validation_messages(child)]
    return []


def allowed_levels(error: object) -> list[str] | None:
    """Extract an explicit effort enum, never a generic list elsewhere in an error."""
    if not is_effort_rejection(error):
        return None
    structured = error
    text = _error_text(error)
    if not isinstance(error, (Mapping, list)):
        try:
            structured = json.loads(text)
        except (ValueError, TypeError):
            structured = None
    found = _structured_allowed(structured)
    if found is not None:
        return found
    if isinstance(structured, (Mapping, list)):
        text = "\n".join(_validation_messages(structured))
    # Common OpenAI-compatible and Python/Pydantic enum validation messages.
    # Only inspect an alternatives clause near the explicitly named parameter.
    for mention in _EFFORT.finditer(text):
        clause = text[max(0, mention.start() - 60):mention.end() + 450]
        match = re.search(r"(?:supported values|allowed(?: values)?|permitted(?: values)?|"
                          r"expected(?: (?:one of|values?))?|should be|must be(?: one of)?|"
                          r"one of|valid values)\s*(?:are|is)?\s*[:=]?\s*(.+)", clause, re.I)
        if match:
            alternatives = re.split(r"[\n;}]", match.group(1), maxsplit=1)[0]
            sequence = re.match(r"\s*\[?\s*(['\"][A-Za-z][A-Za-z0-9_.-]*['\"]"
                                r"(?:(?:\s*,\s*(?:(?:or|and)\s+)?|\s+(?:or|and)\s+)"
                                r"['\"][A-Za-z][A-Za-z0-9_.-]*['\"])*)(?:\s*\])?", alternatives)
            values = re.findall(r"['\"]([A-Za-z][A-Za-z0-9_.-]*)['\"]", sequence.group(1)) if sequence else []
            if values:
                return _canonical_levels(values)
    return None


def _parameter_unsupported(error: object) -> bool:
    if not is_effort_rejection(error):
        return False
    text = _error_text(error)
    return bool(re.search(
        r"(?:unsupported|unknown|unrecognized|unexpected)\s+(?:request\s+)?(?:parameter|argument|field)"
        r"[^\n]{0,90}(?:effort)|(?:effort)[^\n]{0,90}"
        r"(?:parameter (?:is )?(?:unsupported|not supported)|is not supported|does not support)|"
        r"extra inputs are not permitted", text, re.I))


def detect_levels(request: Callable[[str | None], object]) -> dict:
    """Discover accepted values using a caller-controlled minimal request.

    The callback receives a raw effort, or None to omit the parameter. It must
    raise on an unsuccessful response. There are at most ten calls: one invalid
    value, the eight documented candidates, and a no-parameter baseline if needed.
    This function does not retry failures or choose token budgets.
    """
    invalid_accepted = False
    try:
        request(_INVALID_EFFORT)
        invalid_accepted = True
    except Exception as error:
        allowed = allowed_levels(error)
        if allowed is not None:
            return {"state": "known", "source": "probe", "levels": allowed}
        if _parameter_unsupported(error):
            try:
                request(None)
            except Exception as baseline_error:
                return {"state": "failed", "source": "probe", "levels": [],
                        "error": _error_text(baseline_error)}
            return {"state": "known", "source": "probe", "levels": [], "noParameter": True}
        if not is_effort_rejection(error):
            return {"state": "failed", "source": "probe", "levels": [], "error": _error_text(error)}
    accepted = []
    for level in EFFORT_CANDIDATES:
        try:
            request(level)
        except Exception as error:
            if not is_effort_rejection(error):
                result = {"state": "failed", "source": "probe", "levels": accepted,
                          "error": _error_text(error)}
                if invalid_accepted:
                    result["invalidAccepted"] = True
                return result
        else:
            accepted.append(level)
    result = {"state": "known", "source": "probe", "levels": accepted}
    if not accepted:
        try:
            request(None)
        except Exception as error:
            result.update(state="failed", error=_error_text(error))
        else:
            result["noParameter"] = True
    if invalid_accepted:
        result["invalidAccepted"] = True
    return result
