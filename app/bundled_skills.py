"""First-run native Pi Skill folders; never overwrite or resurrect user edits."""
from __future__ import annotations

import json
import shutil
import tempfile
import hashlib
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QLockFile


@lru_cache(maxsize=4)
def _descriptions(source):
    try:
        source = Path(source)
        names = {row['name']: row['files']['SKILL.md'] for row in json.loads((source / 'sources.json').read_text(encoding='utf-8'))}
        return names, json.loads((source / 'descriptions.json').read_text(encoding='utf-8'))
    except (OSError, ValueError, KeyError):
        return {}, {}


@lru_cache(maxsize=128)
def _original(path, signature, expected):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected


def describe_bundled(rows, agent_dir, source=None):
    """UI translations only; user edits and same-name third-party Skills win."""
    source = source or Path(__file__).resolve().parents[1] / 'bundled-skills'
    hashes, descriptions = _descriptions(str(source))
    root = Path(agent_dir).resolve() / 'skills'
    for row in rows:
        path = Path(row.get('path', ''))
        name = path.parent.name
        if name not in descriptions or path.resolve() != (root / name / 'SKILL.md').resolve():
            continue
        try:
            info = path.stat()
            if _original(str(path), (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns), hashes[name]):
                row['descriptions'] = dict(descriptions[name])
        except (OSError, KeyError):
            continue


def install_bundled(source: Path, agent_dir: Path):
    if not (source / 'sources.json').is_file():
        return
    agent_dir.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(agent_dir / '.umeko-skills.lock'))
    if not lock.tryLock(0):
        return
    try:
        ledger = agent_dir / '.umeko-bundled-skills.json'
        seen = json.loads(ledger.read_text(encoding='utf-8')) if ledger.exists() else {}
        if not isinstance(seen, dict):
            raise ValueError('Invalid bundled Skill installation ledger')
        destination = agent_dir / 'skills'
        destination.mkdir(exist_ok=True)
        for row in json.loads((source / 'sources.json').read_text(encoding='utf-8')):
            name = row['name']
            if name in seen:
                continue
            folder = source / name
            target = destination / name
            if not target.exists() and not target.is_symlink():
                with tempfile.TemporaryDirectory(prefix='.umeko-skill-', dir=agent_dir) as temporary:
                    stage = Path(temporary) / name
                    shutil.copytree(folder, stage)
                    # rename won't replace an existing nonempty skill folder.
                    stage.rename(target)
            seen[name] = row['commit']
            temporary = ledger.with_suffix('.tmp')
            temporary.write_text(json.dumps(seen, indent=2) + '\n', encoding='utf-8')
            temporary.replace(ledger)
    finally:
        lock.unlock()
