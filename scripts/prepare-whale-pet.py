"""Reproduce the optional developer asset conversion; never run at app startup.

Requires the desktop's Python dependencies and FFmpeg with libvpx/libwebp.
Only downloaded, pinned community artwork is transcoded; no AI generation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from urllib.parse import quote
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
from PySide6.QtGui import QImage, QImageReader


def inspect_image(path):
    reader = QImageReader(str(path))
    if not reader.canRead():
        raise ValueError('Could not decode converted animation: ' + str(path))
    size, frames = reader.size(), max(1, reader.imageCount())
    top = size.height()
    threshold = bytes(1 if value >= 32 else 0 for value in range(256))
    for _ in range(frames):
        frame = reader.read().convertToFormat(QImage.Format_RGBA8888)
        if frame.isNull():
            raise ValueError('Could not decode converted frame: ' + str(path))
        first = bytes(frame.constBits())[3::4].translate(threshold).find(b'\x01')
        if first >= 0:
            top = min(top, first // frame.width())
    return {'animated': frames > 1, 'width': size.width(), 'height': size.height(),
            'frames': frames, 'contentTop': top / size.height() if top < size.height() else 0}

REPOSITORY = 'https://github.com/yanzwzz/dsh-whale-girl-pet'
COMMIT = '53e9ab8e2c779f4c0feb902cfa940c098c83d228'
SOURCES = {
    'idle': ('待机呼吸休闲', 'ee459a2e181c2b3d0d9ede9559319b7a2ea6b9f21d9a395a4754ffe5c770adde'),
    'thinking': ('工作思考', '619370c39cf9090367d8c21e5fb2df30b41b991b18d71a177941e2bcac05a74f'),
    'working': ('认真工作', '127fffa3844d91b3887bb85e1aebc26e5a888ba933e752132565ff9a8eccfefa'),
    'waiting': ('看表叹气', '01390209a6661a74c90342e02c9b472147f4f46265ecb096169afa9480ad036b'),
    'done': ('工作结束', '6f4b5aeda10ea925cf1067cf9516847241bbd18e6a64d0303ec8c0fa5a1ce59a'),
    'error': ('摸鱼被抓', '0c363a0d23f78e73099f1398e3a550311741c386418d62770f0dcc84f7b17b7b'),
}


def download(relative, target):
    url = f'https://raw.githubusercontent.com/yanzwzz/dsh-whale-girl-pet/{COMMIT}/' + quote(relative)
    with urlopen(url, timeout=30) as response:
        data = response.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise ValueError('Source download exceeds 10 MiB')
    target.write_bytes(data)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg', default=shutil.which('ffmpeg'))
    parser.add_argument('--source-dir', type=Path, default=ROOT / 'build/whale-pet-source')
    args = parser.parse_args()
    if not args.ffmpeg:
        parser.error('Provide an FFmpeg executable with --ffmpeg')
    args.source_dir.mkdir(parents=True, exist_ok=True)
    output = ROOT / 'umeko-plugins/desktop-pet/assets/whale-girl'
    output.mkdir(parents=True, exist_ok=True)
    records, images = {}, {}
    for state, (name, expected) in SOURCES.items():
        relative = 'assets/thumb/' + name + '.webm'
        source = args.source_dir / (state + '.webm')
        data = source.read_bytes() if source.is_file() else download(relative, source)
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('Community source checksum mismatch: ' + state)
        target = output / (state + '.webp')
        # libvpx is deliberate: FFmpeg's default VP9 decoder drops WebM alpha.
        subprocess.run([args.ffmpeg, '-v', 'error', '-nostdin', '-y',
                        '-c:v', 'libvpx-vp9', '-i', str(source), '-an', '-t', '12',
                        '-vf', 'fps=10,format=bgra', '-c:v', 'libwebp_anim',
                        '-q:v', '80', '-compression_level', '2', '-loop', '0', str(target)],
                       check=True, timeout=180)
        images[target.name] = inspect_image(target)
        records[state] = {'path': relative, 'url': f'https://raw.githubusercontent.com/yanzwzz/dsh-whale-girl-pet/{COMMIT}/' + quote(relative), 'sourceSha256': expected,
                          'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                          'bytes': target.stat().st_size}
        print(state, images[target.name], target.stat().st_size, flush=True)
    download('LICENSE', output / 'LICENSE.txt')
    manifest = {
        'format': 'umeko-pet', 'version': 1, 'id': 'whale-girl', 'name': '鲸鱼娘',
        'author': 'dsh-whale-girl-pet contributors', 'license': 'MIT',
        'source': REPOSITORY, 'sourceCommit': COMMIT,
        'states': {state: state + '.webp' for state in SOURCES}, 'images': images,
        'dialogue': {
            'tap': ['要米', '米', '米呢', '米？', '米！'],
            'hover': ['饿，饿', '米呢', '米？'],
            'drag': ['米', '米！'],
            'done': ['好了米', '没问题了米'],
            'error': ['有问题了'],
        },
    }
    provenance = {'format': 'umeko-community-art-provenance', 'version': 1,
                  'repository': REPOSITORY, 'commit': COMMIT, 'license': 'MIT',
                  'conversion': 'Original 360x360 VP9 alpha animations, 10 fps animated WebP, quality 80, looping; no visual redesign.',
                  'assets': records}
    for name, value in [('pet.json', manifest), ('source.json', provenance)]:
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
