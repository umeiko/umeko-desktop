"""Generation selections reference existing provider accounts; they contain no credentials."""
from __future__ import annotations

import copy
import math
import re

DEFAULTS = {
    'image': {'providerId': '', 'model': '', 'size': '', 'quality': '', 'count': 1, 'format': ''},
    'speech': {'providerId': '', 'model': '', 'voice': '', 'format': 'mp3', 'speed': 1.0},
    'video': {'providerId': '', 'model': '', 'seconds': '', 'size': ''},
}
IMAGE_FORMATS = ('', 'png', 'jpeg', 'webp')
SPEECH_FORMATS = ('mp3', 'opus', 'aac', 'flac', 'wav', 'pcm')


def validate(value):
    """Validate a settings patch before merging it into the saved selections."""
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError('多模态设置无效 / Invalid multimodal settings')
    result = {}
    for kind, row in value.items():
        if not isinstance(row, dict) or set(row) - set(DEFAULTS[kind]):
            raise ValueError('多模态设置字段无效 / Invalid generation settings fields')
        clean = {}
        for key, item in row.items():
            if key == 'count':
                if type(item) is not int or not 1 <= item <= 10:
                    raise ValueError('图片数量应为 1–10 / Image count must be 1–10')
            elif key == 'speed':
                if type(item) not in (int, float) or not math.isfinite(item) or not .25 <= item <= 4:
                    raise ValueError('语速应为 0.25–4 / Speech speed must be 0.25–4')
            else:
                if not isinstance(item, str) or len(item) > 512 or any(ord(c) < 32 for c in item):
                    raise ValueError('多模态设置文本无效 / Invalid generation settings text')
                item = item.strip()
                if kind == 'video' and key == 'seconds' and item:
                    if not re.fullmatch(r'[0-9]+', item) or int(item) <= 0:
                        raise ValueError('视频时长应为正整数秒或留空 / Video duration must be positive integer seconds or blank')
                if kind == 'video' and key == 'size' and item:
                    if not re.fullmatch(r'[0-9]+x[0-9]+', item) or any(int(n) <= 0 for n in item.split('x')):
                        raise ValueError('视频分辨率应为正整数宽x高或留空 / Video resolution must be positive WIDTHxHEIGHT or blank')
                if key == 'format' and item not in (IMAGE_FORMATS if kind == 'image' else SPEECH_FORMATS):
                    raise ValueError('生成格式无效 / Invalid generation format')
            clean[key] = item
        result[kind] = clean
    return result


def normalize(value):
    """Old profiles need no migration action; invalid optional values use defaults."""
    result = copy.deepcopy(DEFAULTS)
    if not isinstance(value, dict):
        return result
    for kind, default in DEFAULTS.items():
        row = value.get(kind)
        if not isinstance(row, dict):
            continue
        for key in default:
            if key not in row:
                continue
            try:
                result[kind].update(validate({kind: {key: row[key]}})[kind])
            except ValueError:
                pass
    return result
