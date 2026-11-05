"""Per-model reasoning effort names, in ascending order; off is always separate."""
import re
import copy

from .thinking_formats import valid_format

DEFAULT_LEVELS = ["low", "high", "max"]
_ORDER = ["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"]


def normalize_reasoning(model, previous=None):
    previous = previous or {}
    source = model if "reasoningLevels" in model else previous
    result = {}
    if 'reasoningLevels' in source:
        result['reasoningLevels'] = _levels(source['reasoningLevels'])
    automatic = model.get('reasoningLevelsAuto', previous.get('reasoningLevelsAuto', 'reasoningLevels' not in source))
    if 'reasoningLevels' in model and 'reasoningLevelsAuto' not in model and previous.get('reasoningLevelsAuto') is True:
        automatic = model['reasoningLevels'] == previous.get('reasoningLevels')
    format_auto = model.get('reasoningFormatAuto', previous.get('reasoningFormatAuto', True))
    if type(automatic) is not bool or type(format_auto) is not bool:
        raise ValueError('思考自动设置必须为 true 或 false')
    value = model.get('reasoningFormat', previous.get('reasoningFormat', 'openai'))
    if not valid_format(value):
        raise ValueError('未知思考参数格式')
    result.update(reasoningLevelsAuto=automatic, reasoningFormat=value, reasoningFormatAuto=format_auto)
    for field in ('reasoningDetection', 'reasoningFormatDetection'):
        detection = copy.deepcopy(model.get(field, previous.get(field, {'state': 'unknown'})))
        if not isinstance(detection, dict) or detection.get('state', 'unknown') not in ('unknown', 'probing', 'known', 'failed'):
            raise ValueError('思考检测状态无效')
        detection.setdefault('state', 'unknown')
        if 'levels' in detection:
            detection['levels'] = _levels(detection['levels'])
        if 'rejected' in detection:
            detection['rejected'] = _levels(detection['rejected'])
        result[field] = detection
    same_model = not model.get('upstream') or not previous.get('upstream') or model['upstream'] == previous['upstream']
    if previous and same_model:
        _keep_automatic(result, previous)
    return result


def _keep_automatic(result, previous):
    """Editor drafts never own automatic values; mirror the controller setters."""
    if result['reasoningLevelsAuto']:
        cached = result['reasoningDetection']
        if previous.get('reasoningLevelsAuto') is False:
            if cached['state'] == 'known':
                result['reasoningLevels'] = list(cached.get('levels', []))
            else:
                cached['state'] = 'unknown'
                result.pop('reasoningLevels', None)
        elif 'reasoningLevels' in previous:
            result['reasoningLevels'] = _levels(previous['reasoningLevels'])
        else:
            result.pop('reasoningLevels', None)
    if result['reasoningFormatAuto']:
        cached = result['reasoningFormatDetection']
        if previous.get('reasoningFormatAuto') is False:
            if cached['state'] == 'known' and valid_format(cached.get('format')):
                result['reasoningFormat'] = cached['format']
            else:
                cached['state'] = 'unknown'
        elif valid_format(previous.get('reasoningFormat')):
            result['reasoningFormat'] = previous['reasoningFormat']


def _levels(levels):
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
    return result


def reasoning_levels(model):
    if model.get('reasoningLevelsAuto') is True and (
            'reasoningLevels' not in model or (model.get('reasoningDetection', {}).get('state', 'unknown') in ('unknown', 'probing')
            and 'levels' not in model.get('reasoningDetection', {}))):
        return []
    return list(model.get("reasoningLevels", DEFAULT_LEVELS))


def reconcile_effort(value, levels):
    if value == "off" or value in levels:
        return value
    if value in _ORDER and levels:
        known = [level for level in levels if level in _ORDER]
        if known:
            return min(known, key=lambda level: (abs(_ORDER.index(level) - _ORDER.index(value)), _ORDER.index(level)))
    return "off"
