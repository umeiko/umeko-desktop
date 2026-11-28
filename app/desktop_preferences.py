"""Desktop presentation policy, also readable before native browser libraries load."""
import json
import os
import sys
from pathlib import Path
from .platform_support import data_directory, legacy_data_directory
from .subagent_admission import valid_subagent_limit

DEFAULTS = {'autoOpenSubmissions': True, 'webDisplay': 'embedded', 'chatWidthHints': True,
            'coworkEnabled': False, 'teamCollaborationEnabled': False, 'remoteWorkspaceEnabled': False,
            'disableDxgiVblankThread': False, 'preferGitBash': False, 'gitBashPath': '',
            'subagentConcurrency': None}


def normalize(value):
    value = value if isinstance(value, dict) else {}
    limit = value.get('subagentConcurrency')
    return {'autoOpenSubmissions': value.get('autoOpenSubmissions') if type(value.get('autoOpenSubmissions')) is bool else True,
            'webDisplay': value.get('webDisplay') if value.get('webDisplay') in ('embedded', 'external') else 'embedded',
            'chatWidthHints': value.get('chatWidthHints') if type(value.get('chatWidthHints')) is bool else True,
            'coworkEnabled': value.get('coworkEnabled') is True,
            'teamCollaborationEnabled': value.get('teamCollaborationEnabled') is True,
            'remoteWorkspaceEnabled': value.get('remoteWorkspaceEnabled') is True,
            'disableDxgiVblankThread': value.get('disableDxgiVblankThread') is True,
            'preferGitBash': value.get('preferGitBash') is True,
            'gitBashPath': value['gitBashPath'].strip() if isinstance(value.get('gitBashPath'), str) else '',
            'subagentConcurrency': limit if valid_subagent_limit(limit) else None}


def validate_patch(value):
    if not isinstance(value, dict) or set(value) - DEFAULTS.keys():
        raise ValueError('Unknown Umeko Desktop setting')
    if 'autoOpenSubmissions' in value and type(value['autoOpenSubmissions']) is not bool:
        raise ValueError('autoOpenSubmissions must be boolean')
    if 'chatWidthHints' in value and type(value['chatWidthHints']) is not bool:
        raise ValueError('chatWidthHints must be boolean')
    for key in ('coworkEnabled', 'teamCollaborationEnabled', 'remoteWorkspaceEnabled', 'disableDxgiVblankThread', 'preferGitBash'):
        if key in value and type(value[key]) is not bool:
            raise ValueError(key + ' must be boolean')
    if 'webDisplay' in value and value['webDisplay'] not in ('embedded', 'external'):
        raise ValueError('webDisplay must be embedded or external')
    if 'gitBashPath' in value and (not isinstance(value['gitBashPath'], str) or '\0' in value['gitBashPath']):
        raise ValueError('Invalid Git Bash path')
    if 'subagentConcurrency' in value and not valid_subagent_limit(value['subagentConcurrency']):
        raise ValueError('子智能体并发上限须为可精确表示的正整数，或设为不限 / Subagent concurrency must be a positive safe integer or unlimited')
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


def configure_graphics(settings):
    # Qt reads this when it first creates its DXGI vblank service (issue #198).
    if sys.platform == 'win32' and settings['disableDxgiVblankThread']:
        os.environ['QT_D3D_NO_VBLANK_THREAD'] = '1'
