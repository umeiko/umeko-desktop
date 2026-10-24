"""Bundle pinned official Node.js and npm, with their upstream licenses."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def node_binary(folder, target):
    return folder / ('node.exe' if target.startswith('windows') else 'bin/node')


def prepare_cli_launchers(folder, target):
    """Keep npm usable when a portable bundle is copied without symlinks."""
    if target.startswith('windows'):
        return
    for name, entry in {'npm':'npm/bin/npm-cli.js', 'npx':'npm/bin/npx-cli.js',
                        'corepack':'corepack/dist/corepack.js'}.items():
        script = folder / 'lib/node_modules' / entry
        if not script.is_file():
            if name == 'corepack': continue
            raise RuntimeError('Bundled Node CLI is missing: '+name)
        path = folder / 'bin' / name
        text = '#!/bin/sh\nlauncher_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
        text += 'exec "$launcher_dir/node" "$launcher_dir/../lib/node_modules/'+entry+'" "$@"\n'
        if path.is_symlink(): path.unlink()
        path.write_text(text, encoding='utf-8')
        path.chmod(0o755)


def install_node(target, destination):
    config = json.loads((ROOT / 'scripts/node-distributions.json').read_text(encoding='utf-8'))
    record = config['platforms'][target]
    metadata = {'version': config['version'], 'url': config['baseUrl'] + record['name'], **record}
    if destination.exists():
        existing = json.loads((destination / 'distribution.json').read_text(encoding='utf-8'))
        if existing != metadata or not node_binary(destination, target).is_file():
            raise RuntimeError('Node staging destination contains a different distribution')
        prepare_cli_launchers(destination, target)
        return metadata
    cache = ROOT / 'runtime/downloads/node'
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / record['name']

    def valid():
        if not archive.is_file(): return False
        with archive.open('rb') as stream:
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b''): digest.update(chunk)
        return digest.hexdigest() == record['sha256']

    if not valid():
        print('Downloading pinned Node.js', config['version'], target, flush=True)
        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as stream:
            temporary = Path(stream.name)
            request = urllib.request.Request(metadata['url'], headers={'User-Agent': 'Umeko-Desktop-build'})
            with urllib.request.urlopen(request, timeout=60) as response:
                shutil.copyfileobj(response, stream)
        os.replace(temporary, archive)
        if not valid(): raise RuntimeError('Node.js archive SHA-256 mismatch')
    with tempfile.TemporaryDirectory(prefix='umeko-node-extract-') as staging:
        if archive.suffix == '.zip':
            with zipfile.ZipFile(archive) as package:
                for entry in package.infolist():
                    path = PurePosixPath(entry.filename)
                    if path.is_absolute() or '..' in path.parts or ':' in entry.filename or '\\' in entry.filename or stat.S_ISLNK(entry.external_attr >> 16):
                        raise RuntimeError('Unsafe Node archive path')
                package.extractall(staging)
        else:
            with tarfile.open(archive, 'r:gz') as package:
                package.extractall(staging, filter='data')
        folders = list(Path(staging).iterdir())
        if len(folders) != 1 or not node_binary(folders[0], target).is_file():
            raise RuntimeError('Node.js executable is missing from the archive')
        prepare_cli_launchers(folders[0], target)
        shutil.copytree(folders[0], destination, symlinks=False)
    (destination / 'distribution.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime/node')
    parser.add_argument('--platform', default='')
    args = parser.parse_args()
    arch = 'arm64' if platform.machine().lower() in ('arm64', 'aarch64') else 'x64'
    target = args.platform or {'win32': 'windows', 'darwin': 'macos', 'linux': 'linux'}[sys.platform] + '-' + arch
    info = install_node(target, args.output)
    result = subprocess.check_output([str(node_binary(args.output, target)), '--version'], text=True).strip()
    if result != 'v' + info['version']: raise RuntimeError('Bundled Node version mismatch')
    npm = args.output / ('node_modules/npm/bin/npm-cli.js' if os.name == 'nt' else 'lib/node_modules/npm/bin/npm-cli.js')
    subprocess.run([str(node_binary(args.output, target)), str(npm), '--version'], check=True)
    print('Bundled Node.js', result, flush=True)
