"""Data-only desktop pet packs. Imports never execute user code."""
from __future__ import annotations

import json
import re
import shutil
import stat
import tempfile
import uuid
import zipfile
from pathlib import Path

from PySide6.QtGui import QImageReader

STATES = ('idle', 'thinking', 'working', 'waiting', 'done', 'error')
BUILTIN_APPEARANCES = ('yanami', 'komari', 'tiara', 'whale-girl')
MAX_BYTES = 128 * 1024 * 1024


def image_files(value):
    return dict.fromkeys([*value['states'].values(),
                          *([value['rareIdle']['image']] if 'rareIdle' in value else [])])


def relative(name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name or name.startswith('/'):
        raise ValueError('形象文件必须使用包内相对路径：' + str(name))
    parts = name.rstrip('/').split('/')
    if any(p in ('', '.', '..') or p.endswith(('.', ' ')) or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', p, re.I) for p in parts):
        raise ValueError('形象路径包含不安全的目录段：' + name)
    return '/'.join(parts)


def inspect_image(path):
    if path.suffix.lower() not in ('.webp', '.gif', '.png') or not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError('形象支持最多 32 MiB 的 WebP、GIF 或 PNG：' + path.name)
    reader = QImageReader(str(path))
    size = reader.size()
    count = max(1, reader.imageCount())
    if not reader.canRead() or not 1 <= size.width() <= 1024 or not 1 <= size.height() <= 1024 or count > 240 or size.width() * size.height() * count > 60_000_000:
        raise ValueError('无法读取形象，或动画超过 1024px / 240 帧 / 6000 万像素限制：' + path.name)
    duration = 0
    for _ in range(count):
        image = reader.read()
        if image.isNull():
            raise ValueError('形象包含无法解码的帧：' + path.name)
        duration += max(0, reader.nextImageDelay())
    if duration > 30000:
        raise ValueError('单段动画不能超过 30 秒：' + path.name)
    return {'animated': count > 1, 'width': size.width(), 'height': size.height(), 'frames': count}


def read_pack(folder, check=False):
    folder = Path(folder).resolve()
    manifest = folder / 'pet.json'
    if manifest.stat().st_size > 65536:
        raise ValueError('pet.json 不能超过 64 KiB')
    value = json.loads(manifest.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict) or value.get('format') != 'umeko-pet' or type(value.get('version')) is not int or value['version'] != 1:
        raise ValueError('需要 format 为 umeko-pet、version 为 1 的 pet.json')
    if not isinstance(value.get('id'), str) or not re.fullmatch('[a-z][a-z0-9-]{0,47}', value['id']):
        raise ValueError('形象 id 需要 1–48 位小写字母、数字或短横线，以字母开头')
    if not isinstance(value.get('name'), str) or not value['name'].strip() or len(value['name']) > 48:
        raise ValueError('形象名称需要 1–48 个字符')
    states = value.get('states')
    if not isinstance(states, dict) or 'idle' not in states or states.keys() - set(STATES):
        raise ValueError('states 必须包含 idle，其余可选状态为 thinking、working、waiting、done、error')
    if 'rareIdle' in value:
        rare = value['rareIdle']
        if (not isinstance(rare, dict) or not isinstance(rare.get('image'), str)
                or not isinstance(rare.get('line'), str) or not rare['line'].strip()
                or len(rare['line']) > 120):
            raise ValueError('rareIdle 需要包内 image 和最多 120 字的 line')
    info = {}
    total = 0
    pixels = 0
    for name in image_files(value):
        path = folder / relative(name)
        if not path.resolve().is_relative_to(folder) or any(p.is_symlink() for p in (path, *path.parents) if p != folder and p.is_relative_to(folder)):
            raise ValueError('形象不能使用链接或指向包外：' + name)
        total += path.stat().st_size
        if check:
            info[name] = inspect_image(path)
            pixels += info[name]['width'] * info[name]['height'] * info[name]['frames']
    if total > MAX_BYTES or pixels > 220_000_000:
        raise ValueError('形象资源总量超过 128 MiB 或 2.2 亿像素')
    dialogue = value.get('dialogue', {})
    if not isinstance(dialogue, dict) or dialogue.keys() - {'tap', 'hover', 'drag', 'done', 'error'}:
        raise ValueError('dialogue 支持 tap、hover、drag、done、error')
    for lines in dialogue.values():
        if not isinstance(lines, list) or not 1 <= len(lines) <= 16 or any(not isinstance(s, str) or not s.strip() or len(s) > 120 for s in lines):
            raise ValueError('每种互动台词需要 1–16 条、每条最多 120 字')
    return {**value, 'images': info or value.get('images', {})}


def import_pack(source, destination):
    source, destination = Path(source).expanduser().resolve(), Path(destination)
    if not source.is_file():
        raise ValueError('请选择本机形象 ZIP、pet.json 或动画文件')
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.import-', dir=destination) as temporary:
        stage = Path(temporary) / 'pack'
        stage.mkdir()
        if source.suffix.lower() == '.zip':
            if source.stat().st_size > MAX_BYTES:
                raise ValueError('形象 ZIP 不能超过 128 MiB')
            with zipfile.ZipFile(source) as archive:
                entries = archive.infolist()
                if len(entries) > 64 or sum(e.file_size for e in entries) > MAX_BYTES:
                    raise ValueError('形象最多包含 64 个文件、解压后不超过 128 MiB')
                seen = set()
                names = []
                for entry in entries:
                    name = relative(entry.filename)
                    if name.casefold() in seen or stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG, stat.S_IFDIR):
                        raise ValueError('形象包含重复路径或链接：' + name)
                    if entry.flag_bits & 1:
                        raise ValueError('不支持加密的形象 ZIP')
                    seen.add(name.casefold())
                    names.append((entry, name))
                roots = [name for entry, name in names if not entry.is_dir() and name.split('/')[-1] == 'pet.json']
                prefix = '' if 'pet.json' in roots else roots[0].rsplit('/', 1)[0] + '/' if len(roots) == 1 and roots[0].count('/') == 1 else None
                if prefix is None:
                    raise ValueError('ZIP 根目录或单层目录中需要 pet.json')
                for entry, name in names:
                    if entry.is_dir():
                        continue
                    if not name.startswith(prefix):
                        raise ValueError('形象 ZIP 包含目录外文件：' + name)
                    target = stage / relative(name[len(prefix):])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry) as src, target.open('xb') as out:
                        shutil.copyfileobj(src, out, 65536)
        elif source.name.lower() == 'pet.json':
            value = read_pack(source.parent)
            (stage / 'pet.json').write_bytes(source.read_bytes())
            for name in image_files(value):
                target = stage / relative(name)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source.parent / name, target)
        else:
            inspect_image(source)
            name = 'animation' + source.suffix.lower()
            shutil.copyfile(source, stage / name)
            value = {'format': 'umeko-pet', 'version': 1, 'id': 'custom-' + uuid.uuid4().hex[:12], 'name': source.stem[:48], 'states': {'idle': name}}
            (stage / 'pet.json').write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        value = read_pack(stage, check=True)
        if value['id'] in BUILTIN_APPEARANCES or (destination / value['id']).exists():
            raise ValueError('该形象 id 已存在，请修改 pet.json 中的 id 后再导入')
        # Retain only declared data files, never Python/QML/HTML from the ZIP.
        keep = {'pet.json', *image_files(value)}
        for path in stage.rglob('*'):
            if path.is_file() and path.relative_to(stage).as_posix() not in keep:
                path.unlink()
        (stage / 'pet.json').write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        stage.rename(destination / value['id'])
        return value
