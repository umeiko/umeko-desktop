"""Materialize the Git Bash bundle in the desktop profile on first use."""
from __future__ import annotations

import lzma
from pathlib import Path, PureWindowsPath
import shutil
import tarfile

ARCHIVE_NAME = "git-bash-2.56.1-r3.tar.xz"
VERSION = ARCHIVE_NAME.removesuffix(".tar.xz")
REQUIRED_FILES = ("bin/bash.exe", "usr/bin/bash.exe", "usr/bin/msys-2.0.dll", "cmd/git.exe")


def _reparse(path):
    return path.is_symlink() or path.is_junction()


def git_bash_ready(root):
    try:
        if _reparse(root.parent) or _reparse(root):
            return False
        lengths = (root / ".ready").read_text(encoding="ascii").splitlines()
        return bool(lengths) and lengths == [str((root / name).stat().st_size) for name in REQUIRED_FILES]
    except (OSError, UnicodeError):
        return False


def _remove(path):
    # A junction at the cache location is unexpected. Do not write through it.
    if _reparse(path):
        if path.is_symlink():
            path.unlink()
        else:
            path.rmdir()
    elif path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _entry_path(member):
    parts = member.name.split("/")
    if any(not part or part in (".", "..") or part != part.rstrip(" .")
           or any(char in part for char in '\\:*?"<>|')
           or PureWindowsPath(part).is_reserved() for part in parts):
        raise ValueError("Unexpected Git Bash archive path")
    if not (member.isdir() or member.isfile()):
        raise ValueError("Unexpected Git Bash archive entry")
    return Path(*parts)


def prepare_git_bash(archive, root, progress):
    """Publish only a complete version. An interrupted attempt leaves staging only."""
    if git_bash_ready(root):
        return
    parent = root.parent
    parent.mkdir(parents=True, exist_ok=True)
    if _reparse(parent):
        raise ValueError("Git Bash cache root must be an ordinary directory")
    partial = parent / f".{root.name}.partial"
    _remove(partial)
    _remove(root)
    partial.mkdir()
    try:
        size = archive.stat().st_size
        last = 0
        with archive.open("rb") as compressed, lzma.LZMAFile(compressed) as stream:
            with tarfile.open(fileobj=stream, mode="r|") as bundle:
                for member in bundle:
                    target = partial / _entry_path(member)
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(exist_ok=True, parents=True)
                        with bundle.extractfile(member) as source, target.open("xb") as output:
                            shutil.copyfileobj(source, output, length=256 * 1024)
                    value = min(99, 100 * compressed.tell() // size)
                    if value > last:
                        last = value
                        progress(value)
            # Reading the XZ footer also checks the final compressed block.
            while stream.read(256 * 1024):
                pass
        lengths = [(partial / name).stat().st_size for name in REQUIRED_FILES]
        if any(length <= 0 for length in lengths):
            raise ValueError("Git Bash archive is incomplete")
        (partial / ".ready").write_text("\n".join(map(str, lengths)) + "\n", encoding="ascii")
        partial.rename(root)
        progress(100)
    finally:
        _remove(partial)
