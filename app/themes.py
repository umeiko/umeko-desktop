"""Versioned, declarative color themes shared by both desktop editions."""
import json
import re
from pathlib import Path

COLORS = frozenset('bg sidebar surface userBubble hover line ink muted accent accentBg selectionBg selectionText button buttonText danger'.split())
BASES = ('light', 'dark', 'yanami')
LIMIT = 32


def normalize_theme(value):
    if not isinstance(value, dict) or value.get('format') != 'umeko-theme' or type(value.get('version')) is not int or value['version'] != 1:
        raise ValueError('需要 format 为 umeko-theme、version 为 1 的 JSON 主题')
    if not isinstance(value.get('id'), str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', value['id']):
        raise ValueError('主题 id 只能使用小写字母、数字和短横线，最多 48 位')
    name = value.get('name')
    if not isinstance(name, str) or not name.strip() or len(name) > 48:
        raise ValueError('主题名称应为 1–48 个字符')
    if value.get('base') not in BASES:
        raise ValueError('base 应为 light、dark 或 yanami')
    colors = value.get('colors')
    if not isinstance(colors, dict) or colors.keys() - COLORS or any(not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', color) for color in colors.values()):
        raise ValueError('颜色需使用支持的颜色名称及 #RRGGBB 格式')
    return {'format': 'umeko-theme', 'version': 1, 'id': value['id'], 'name': name.strip(), 'base': value['base'], 'colors': dict(colors)}


def theme_library(values):
    result = []
    for value in values[:LIMIT] if isinstance(values, list) else []:
        try:
            item = normalize_theme(value)
            if not any(row['id'] == item['id'] for row in result):
                result.append(item)
        except ValueError:
            continue
    return result


def read_theme(file):
    with Path(file).open('rb') as source:
        raw = source.read(65537)
    if len(raw) > 65536:
        raise ValueError('主题文件不能超过 64 KiB')
    return normalize_theme(json.loads(raw.decode('utf-8-sig')))
