"""Per-model reasoning effort names, in ascending order; off is always separate."""
import re

DEFAULT_LEVELS = ["low", "high", "max"]
_ORDER = ["minimal", "low", "medium", "high", "xhigh", "max"]


def normalize_reasoning(model, previous=None):
    source = model if "reasoningLevels" in model else previous or {}
    if "reasoningLevels" not in source:
        return {}
    levels = source["reasoningLevels"]
    if not isinstance(levels, list) or len(levels) > 32:
        raise ValueError("思考档位必须是最多 32 项的列表")
    result = []
    for level in levels:
        if not isinstance(level, str) or not re.fullmatch(r"[^\s\x00-\x1f\x7f]{1,64}", level.strip()):
            raise ValueError("档位名称需为 1–64 个字符，不能包含空白")
        level = level.strip()
        if level.lower() == "off" or level.casefold() in {item.casefold() for item in result}:
            raise ValueError("档位名称不能重复，也不能使用保留名称 off")
        result.append(level)
    return {"reasoningLevels": result}


def reasoning_levels(model):
    return list(model.get("reasoningLevels", DEFAULT_LEVELS))


def reconcile_effort(value, levels):
    if value == "off" or value in levels:
        return value
    if value in _ORDER and levels:
        known = [level for level in levels if level in _ORDER]
        if known:
            return min(known, key=lambda level: (abs(_ORDER.index(level) - _ORDER.index(value)), _ORDER.index(level)))
    return "off"
