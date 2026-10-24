"""Pinned sources, with links materialized for exFAT/NTFS workspaces."""
import hashlib
import posixpath
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

DIGEST = '74b2c43ca865ec9ede257bcd3bdadafc20f571900cb2440a4488335e4d4e91cc'
destination = Path(sys.argv[1])
marker = destination / '.umeko-source-sha256'
if marker.is_file() and marker.read_text().strip() == DIGEST:
    raise SystemExit(0)
destination.parent.mkdir(parents=True, exist_ok=True)
archive = destination.parent / 'fcitx5-qt-5.1.13.tar.gz'
if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != DIGEST:
    request = urllib.request.Request('https://codeload.github.com/fcitx/fcitx5-qt/tar.gz/refs/tags/5.1.13', headers={'User-Agent':'Umeko-build'})
    archive.write_bytes(urllib.request.urlopen(request, timeout=90).read())
if hashlib.sha256(archive.read_bytes()).hexdigest() != DIGEST:
    raise SystemExit('fcitx5-qt source SHA-256 mismatch')
shutil.rmtree(destination, ignore_errors=True)
destination.mkdir()
with tarfile.open(archive) as stream:
    def relative(name):
        name = posixpath.normpath(name)
        if not name.startswith('fcitx5-qt-5.1.13/') or '..' in name.split('/'):
            raise ValueError('Unsafe source archive path: ' + name)
        return Path(name.split('/', 1)[1])
    links = []
    for member in stream.getmembers():
        if member.name.rstrip('/') == 'fcitx5-qt-5.1.13': continue
        target = destination / relative(member.name)
        if member.isdir(): target.mkdir(parents=True, exist_ok=True)
        elif member.isfile():
            target.parent.mkdir(parents=True, exist_ok=True)
            with stream.extractfile(member) as source, target.open('wb') as output:
                shutil.copyfileobj(source, output)
        elif member.issym():
            links.append((target, destination / relative(posixpath.join(posixpath.dirname(member.name), member.linkname))))
        else: raise ValueError('Unexpected source archive entry')
    for target, source in links:
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir(): shutil.copytree(source, target, dirs_exist_ok=True)
        else: shutil.copy2(source, target)
marker.write_text(DIGEST + '\n')
