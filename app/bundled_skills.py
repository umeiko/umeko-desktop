"""First-run native Pi Skill folders; never overwrite or resurrect user edits."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import QLockFile


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
