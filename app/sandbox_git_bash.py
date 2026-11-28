"""Materialize the Git Bash bundle in the desktop profile on first use."""
from __future__ import annotations

import hashlib
import json
import lzma
from pathlib import Path, PureWindowsPath
import re
import shutil
import tarfile
from uuid import uuid4

ARCHIVE_NAME = "git-bash-2.56.1-r5.tar.xz"
VERSION = ARCHIVE_NAME.removesuffix(".tar.xz")
COMPONENT_MANIFEST = "windows-sandbox-git-bash.json"
REQUIRED_FILES = ("bin/bash.exe", "usr/bin/bash.exe", "usr/bin/msys-2.0.dll", "cmd/git.exe", "ucrt64/bin/git.exe", "usr/bin/rg.exe")


def component_metadata(path):
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    sha256 = record.get("sha256", "") if isinstance(record, dict) else ""
    if (not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256)
            or record.get("name") != f"{VERSION}-{sha256[:12]}.tar.xz"
            or type(record.get("size")) is not int or not 0 < record["size"] <= 512 * 1024**2):
        raise ValueError("Invalid Windows Git Bash component metadata")
    return record


def component_archive(manifest, directory, progress):
    from .project_info import PROJECT_URL, VERSION as APP_VERSION
    from .update_download import download_asset

    component = component_metadata(manifest)
    cached = directory / component["name"]
    if _reparse(directory) or _reparse(cached):
        raise PermissionError("Git Bash download cache must be an ordinary path")
    if cached.is_file() and cached.stat().st_size == component["size"]:
        with cached.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() == component["sha256"]:
                return cached
    for tag in (f"v{APP_VERSION}", "preview"):
        try:
            return Path(download_asset(
                {**component, "url": f"{PROJECT_URL}/releases/download/{tag}/{component['name']}"},
                directory, lambda status: progress(round(status.get("progress", 0) * 49)), lambda: False,
            ))
        except (OSError, ValueError) as error:
            last_error = error
    raise ValueError("Could not download the Windows sandbox Git Bash component") from last_error


def _reparse(path):
    return path.is_symlink() or path.is_junction()


def _is_executable(path):
    if not path.is_file() or _reparse(path):
        return False
    with path.open("rb") as executable:
        return executable.read(2) == b"MZ"


def git_bash_ready(root):
    try:
        if _reparse(root.parent.parent) or _reparse(root.parent) or _reparse(root):
            return False
        lengths = (root / ".ready").read_text(encoding="ascii").splitlines()
        files = [root / name for name in REQUIRED_FILES]
        if lengths != [str(path.stat().st_size) for path in files]:
            return False
        return all(_is_executable(path) for path in files)
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
    if _reparse(parent.parent) or _reparse(parent):
        raise PermissionError("Git Bash cache must be an ordinary directory")
    parent.mkdir(parents=True, exist_ok=True)
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
        lengths = [(partial / name).stat().st_size if _is_executable(partial / name) else 0
                   for name in REQUIRED_FILES]
        if any(length <= 0 for length in lengths):
            raise ValueError("Git Bash archive is incomplete")
        (partial / ".ready").write_text("\n".join(map(str, lengths)) + "\n", encoding="ascii")
        partial.rename(root)
        progress(100)
    finally:
        try:
            _remove(partial)
        except OSError:
            # A scanner or another process can temporarily hold staging open.
            # Preserve the original exception so recovery can choose a new path.
            pass


def find_git_bash(root):
    if git_bash_ready(root):
        return root
    return next((path for path in sorted(root.parent.glob(f"{root.name}-*"))
                 if git_bash_ready(path)), None)


def recover_git_bash(archive, root, progress, previous=None):
    """Work around an occupied version directory without deleting a live copy."""
    replacement = root.with_name(f"{root.name}-{uuid4().hex}")
    if previous is None:
        try:
            prepare_git_bash(archive, root, progress)
            return root
        except OSError:
            # A stale file or staging directory can be locked while the cache
            # parent is still writable. Try a different directory in that case.
            if not archive.is_file():
                raise
    prepare_git_bash(archive, replacement, progress)
    return replacement


def clean_git_bash_cache(root, keep=None):
    if _reparse(root.parent.parent) or _reparse(root.parent):
        return
    try:
        candidates = [root, *root.parent.glob(f"{root.name}-*"), *root.parent.glob(f".{root.name}*.partial")]
    except OSError:
        return
    for path in candidates:
        if path != keep:
            try:
                _remove(path)
            except OSError:
                pass
