"""Desktop paths and input methods, configured before creating a Qt application."""
from __future__ import annotations

import os
import sys
import json
import shutil
import uuid
import hashlib
from pathlib import Path


def normalize_projects(data):
    """Keep path-derived identities consistent after a move and merge duplicates."""
    previous = data.get('projects', [])
    projects, positions, identifiers = [], {}, {}
    for value in previous:
        project = dict(value)
        if not project.get('path'):
            projects.append(project)
            continue
        path = str(Path(project['path']).expanduser().resolve())
        identifier = hashlib.sha256(os.path.normcase(path).encode()).hexdigest()[:16]
        if project.get('id'): identifiers[project['id']] = identifier
        project.update(path=path, id=identifier)
        if identifier not in positions:
            positions[identifier] = len(projects)
            projects.append(project)
        else:
            merged = projects[positions[identifier]]
            for key, value in project.items(): merged.setdefault(key, value)
            if project.get('pinned'): merged['pinned'] = True
            if not merged.get('name'): merged['name'] = project.get('name', '')
    active = identifiers.get(data.get('activeProject', ''), data.get('activeProject', ''))
    removed = list(dict.fromkeys(identifiers.get(value, value) for value in data.get('removedProjects', [])))
    changed = projects != previous or active != data.get('activeProject', '') or removed != data.get('removedProjects', [])
    if changed: data.update(projects=projects, activeProject=active, removedProjects=removed)
    return changed


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
        normalize_projects(data)
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
    if plugin_directory is None:
        from PySide6.QtCore import QCoreApplication, QLibraryInfo
        # Owned plugin first, without modifying PySide's installation or system Qt.
        owned = Path(__file__).resolve().parents[1] / 'build/input-method/plugins'
        if not getattr(sys, 'frozen', False) and owned.is_dir():
            QCoreApplication.addLibraryPath(str(owned))
            plugin_directory = owned / 'platforminputcontexts'
        else:
            plugin_directory = Path(QLibraryInfo.path(QLibraryInfo.PluginsPath)) / 'platforminputcontexts'
        # Resolve all Qt dependencies to PySide's Qt before loading the plugin.
        from PySide6 import QtDBus
    if "UMEKO_QT_IM_MODULE" in environment:
        environment["QT_IM_MODULE"] = environment["UMEKO_QT_IM_MODULE"]
        return
    plugins = Path(plugin_directory)
    module = environment.get("QT_IM_MODULE", "")
    fcitx = module in ("fcitx", "fcitx5") or (not module and "fcitx" in environment.get("XMODIFIERS", ""))
    if not fcitx:
        return  # Preserve native Wayland text input and unrelated IME choices.
    if any(plugins.glob("*fcitx*.so")):
        environment["QT_IM_MODULE"] = "fcitx"
