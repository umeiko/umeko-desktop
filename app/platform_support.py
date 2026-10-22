"""Desktop paths and input methods, configured before creating a Qt application."""
from __future__ import annotations

import os
import sys
import json
import shutil
import uuid
from pathlib import Path


def data_directory(platform=None, environment=None, home=None):
    return (Path.home() if home is None else Path(home)) / '.umeko' / 'desktop'


def legacy_data_directory(platform=None, environment=None, home=None):
    platform = platform or sys.platform
    environment = os.environ if environment is None else environment
    home = Path.home() if home is None else Path(home)
    if platform == "win32":
        return Path(environment.get("LOCALAPPDATA", str(home))) / "Umeko"
    if platform == "darwin":
        return home / "Library/Application Support/Umeko"
    return Path(environment.get("XDG_DATA_HOME") or home / ".local/share") / "umeko"


def migrate_profile(previous, target):
    """Copy once, remap managed paths, then atomically activate the new profile."""
    previous, target = Path(previous).resolve(), Path(target).resolve()
    if target.exists() or not (previous / 'settings.json').is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(target.name + '-migrate-' + uuid.uuid4().hex)
    shutil.copytree(previous, staging, symlinks=True)
    def remap(path):
        if not isinstance(path, str) or not path:
            return path
        try:
            return str(target / Path(path).relative_to(previous))
        except ValueError:
            return path
    def rewrite(path, transform):
        if path.is_file():
            data = json.loads(path.read_text(encoding='utf-8'))
            transform(data)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    def settings(data):
        data['workspace'] = remap(data.get('workspace', ''))
        if isinstance(data.get('agent'), dict):
            data['agent']['agentDir'] = remap(data['agent'].get('agentDir', ''))
        for project in data.get('projects', []):
            for key in ('path', 'workspace'):
                if key in project: project[key] = remap(project[key])
    def sessions(data):
        for session in data:
            for key in ('file', 'workspace'):
                if key in session: session[key] = remap(session[key])
    rewrite(staging / 'settings.json', settings)
    rewrite(staging / 'sessions.json', sessions)
    for path in (staging / 'pi/sessions').rglob('*.jsonl'):
        if path.is_symlink(): continue
        with path.open('rb') as source:
            first, remainder = source.readline(), source.read()
        try:
            header = json.loads(first)
        except (ValueError, UnicodeError):
            continue
        if header.get('type') != 'session': continue
        changed = False
        for key in ('cwd', 'parentSession'):
            if key in header and remap(header[key]) != header[key]:
                header[key] = remap(header[key]); changed = True
        if changed:
            path.write_bytes(json.dumps(header, ensure_ascii=False).encode() + b'\n' + remainder)
    staging.rename(target)


def configure_input_method(platform=None, environment=None, plugin_directory=None):
    platform = platform or sys.platform
    environment = os.environ if environment is None else environment
    if not platform.startswith("linux"):
        return
    if "UMEKO_QT_IM_MODULE" in environment:
        environment["QT_IM_MODULE"] = environment["UMEKO_QT_IM_MODULE"]
        return
    if plugin_directory is None:
        from PySide6.QtCore import QLibraryInfo
        plugin_directory = Path(QLibraryInfo.path(QLibraryInfo.PluginsPath)) / "platforminputcontexts"
    plugins = Path(plugin_directory)
    module = environment.get("QT_IM_MODULE", "")
    fcitx = module in ("fcitx", "fcitx5") or (not module and "fcitx" in environment.get("XMODIFIERS", ""))
    if not fcitx:
        return  # Preserve native Wayland text input and unrelated IME choices.
    if any(plugins.glob("*fcitx*.so")):
        environment["QT_IM_MODULE"] = "fcitx"
    elif any(plugins.glob("*ibus*.so")):
        # Fcitx5 implements the IBus protocol. PySide's own Qt normally bundles
        # this plugin; system fcitx Qt plugins may use an incompatible Qt ABI.
        environment["QT_IM_MODULE"] = "ibus"
