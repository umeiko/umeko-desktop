"""Locate a Git for Windows Bash executable for ordinary shell tools."""

import os
from pathlib import Path
import shutil


def _git_bash(path):
    if not path.is_absolute() or path.name.lower() != "bash.exe" or not path.is_file():
        return None
    path = path.resolve()
    for root in (path.parent.parent, path.parent.parent.parent):
        if (root / "cmd/git.exe").is_file() and (root / "usr/bin/msys-2.0.dll").is_file():
            return str(path)
    return None


def find_git_bash(explicit="", environment=None):
    if explicit:
        return _git_bash(Path(os.path.expandvars(explicit.strip().strip('"'))))
    environment = os.environ if environment is None else environment
    search_path = environment.get("PATH", "")
    git = shutil.which("git.exe", path=search_path)
    directories = [Path(part.strip('"')) for part in search_path.split(os.pathsep) if part]
    if git:
        directories.append(Path(git).parent.parent / "bin")
    for key in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        if environment.get(key):
            parent = Path(environment[key])
            directories.append(parent / ("Programs/Git/bin" if key == "LOCALAPPDATA" else "Git/bin"))
    for directory in directories:
        if result := _git_bash(directory / "bash.exe"):
            return result
    return None
