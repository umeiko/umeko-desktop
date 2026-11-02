"""Desktop presentation policy, also readable before native browser libraries load."""
import json
import os
from pathlib import Path
from .platform_support import data_directory, legacy_data_directory

DEFAULTS = {'autoOpenSubmissions': True, 'webDisplay': 'embedded'}


def normalize(value):
    value = value if isinstance(value, dict) else {}
    return {'autoOpenSubmissions': value.get('autoOpenSubmissions') if type(value.get('autoOpenSubmissions')) is bool else True,
            'webDisplay': value.get('webDisplay') if value.get('webDisplay') in ('embedded', 'external') else 'embedded'}


def validate_patch(value):
    if not isinstance(value, dict) or set(value) - DEFAULTS.keys():
        raise ValueError('Unknown Umeko Desktop setting')
    if 'autoOpenSubmissions' in value and type(value['autoOpenSubmissions']) is not bool:
        raise ValueError('autoOpenSubmissions must be boolean')
    if 'webDisplay' in value and value['webDisplay'] not in ('embedded', 'external'):
        raise ValueError('webDisplay must be embedded or external')
    return value


def startup_settings():
    custom = os.environ.get('UMEKO_DATA_DIR')
    paths = [Path(custom)] if custom else [data_directory(), legacy_data_directory()]
    for directory in paths:
        path = directory / 'settings.json'
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            return normalize(data.get('desktop'))
        except (OSError, ValueError, AttributeError):
            return dict(DEFAULTS)
    return dict(DEFAULTS)
