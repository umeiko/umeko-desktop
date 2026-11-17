"""Record release size by runtime component, using ZIP's actual compressed sizes."""
from __future__ import annotations
import json
from pathlib import Path
import tarfile
import zipfile


def category(name):
    parts = name.replace('\\', '/').split('/')
    parts = parts[1:]  # portable folder / .app
    if parts[:1] == ['_internal']: parts = parts[1:]
    if 'Resources' in parts: parts = parts[parts.index('Resources') + 1:]
    relative = '/'.join(parts)
    if relative.startswith('umeko-plugins/desktop-pet/assets/'): return 'Pet animations'
    if relative.startswith('app/icons/'): return 'UI artwork'
    if relative.startswith('runtime/node/'): return 'Node and npm'
    if relative.startswith('runtime/releases/'): return 'Pi and dependencies'
    if relative.startswith('runtime/python/') or relative.startswith(('python3', 'libpython3')): return 'Python'
    if relative.startswith('bundled-skills/'): return 'Bundled Skills'
    if relative.startswith('licenses/'): return 'Licenses'
    if 'PySide6' in parts or any(p.startswith(('Qt6', 'QtQuick', 'QtQml', 'QtCore', 'QtGui')) for p in parts) or parts[:1] in (['qml'], ['plugins'], ['lib'], ['Frameworks']): return 'Qt and native libraries'
    if relative.endswith(('.exe', '/MacOS/UmekoCpp', '/MacOS/Umeko')) or relative in ('UmekoCpp', 'Umeko'): return 'Application executable'
    return 'Other application resources'


def archive_report(archive):
    archive = Path(archive)
    groups = {}
    if archive.suffix == '.zip':
        with zipfile.ZipFile(archive) as stream:
            entries = [(f.filename, f.file_size, f.compress_size) for f in stream.infolist() if not f.is_dir()]
    else:
        with tarfile.open(archive) as stream:
            entries = [(f.name, f.size, None) for f in stream if f.isfile()]
    for name, expanded, compressed in entries:
        group = groups.setdefault(category(name), {'files': 0, 'expandedBytes': 0, 'compressedBytes': 0 if compressed is not None else None})
        group['files'] += 1
        group['expandedBytes'] += expanded
        if compressed is not None: group['compressedBytes'] += compressed
    return {'schema': 1, 'archive': archive.name, 'archiveBytes': archive.stat().st_size,
            'expandedBytes': sum(row[1] for row in entries), 'files': len(entries),
            'groups': dict(sorted(groups.items(), key=lambda row: -(row[1]['compressedBytes'] or row[1]['expandedBytes'])))}


def write_report(archive, output):
    report = archive_report(archive)
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def markdown(report):
    compressed = all(g['compressedBytes'] is not None for g in report['groups'].values())
    key = 'compressedBytes' if compressed else 'expandedBytes'
    heading = 'ZIP content (MB)' if compressed else 'Expanded content (MB)'
    rows = ['\nRelease: **%.1f MB**; expanded files: **%.1f MB**.\n' % (report['archiveBytes']/1e6, report['expandedBytes']/1e6), '| Component | '+heading+' |', '| --- | ---: |']
    rows += ['| '+name+' | %.1f |' % (group[key]/1e6) for name, group in report['groups'].items()]
    return '\n'.join(rows) + '\n'
