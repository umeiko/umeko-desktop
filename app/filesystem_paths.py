"""Windows long paths for Python I/O; ordinary paths for Node and settings."""
import os
from pathlib import Path


def ordinary_path(path):
    value = os.fspath(path)
    if os.name == "nt":
        if value.startswith("\\\\?\\UNC\\"):
            value = "\\\\" + value[8:]
        elif value.startswith("\\\\?\\"):
            value = value[4:]
    return Path(value)


def filesystem_path(path):
    path = ordinary_path(path)
    if os.name != "nt":
        return path
    value = os.path.abspath(path)
    if value.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + value[2:])
    return Path("\\\\?\\" + value)
