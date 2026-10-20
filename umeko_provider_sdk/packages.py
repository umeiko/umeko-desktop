"""Provider package validation and deterministic ZIP creation. No code execution."""
from __future__ import annotations

import json
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath

from . import API_VERSION, ProviderError

MAX_BYTES = 20 * 1024 * 1024
MAX_FILES = 512


def relative_path(value):
    if not isinstance(value, str) or "\\" in value or ":" in value or "\x00" in value:
        raise ProviderError("Invalid package path")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in (".", "..") for part in value.split("/")):
        raise ProviderError("Package paths must stay inside the package")
    for part in path.parts:
        if part.endswith((".", " ")) or re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part, re.I):
            raise ProviderError("Package path is not portable")
    return path


def validate_folder(folder):
    folder = Path(folder).resolve()
    def read(name):
        path = folder.joinpath(*relative_path(name).parts)
        if not path.resolve().is_relative_to(folder) or path.is_symlink():
            raise ProviderError("Package symlinks are not supported")
        return json.loads(path.read_text(encoding="utf-8-sig"))
    manifest = read("manifest.json")
    if manifest.get("apiVersion") != API_VERSION:
        raise ProviderError("Unsupported Provider API version")
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", manifest.get("id", "")):
        raise ProviderError("Provider id must use lowercase letters, digits and hyphens")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?", manifest.get("version", "")):
        raise ProviderError("Provider version must be a semantic version")
    if not isinstance(manifest.get("name"), str) or not manifest["name"].strip():
        raise ProviderError("Provider name is required")
    entry, sep, factory = manifest.get("entrypoint", "").partition(":")
    if not sep or not factory.isidentifier() or not entry.endswith(".py"):
        raise ProviderError("entrypoint must be scripts/provider.py:create_provider")
    if not folder.joinpath(*relative_path(entry).parts).is_file():
        raise ProviderError("Provider entrypoint is missing")
    fields = manifest.get("auth", {}).get("fields", [])
    if not isinstance(fields, list) or len(fields) > 20:
        raise ProviderError("Invalid authentication fields")
    seen = set()
    for item in fields:
        key = item.get("key", "")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", key) or key in seen or not isinstance(item.get("label"), str):
            raise ProviderError("Invalid authentication field")
        seen.add(key)
    config = read(manifest.get("config", "config.json"))
    schema = read(manifest.get("configSchema", "config.schema.json"))
    validate_config(config, schema)
    return manifest, config, schema


def validate_config(config, schema):
    """Small, explicit JSON Schema subset; no remote refs or executable validation."""
    def visit(value, rule, name):
        types = {"object": dict, "array": list, "string": str, "boolean": bool, "integer": int, "number": (int, float)}
        kind = rule.get("type")
        if kind not in types or not isinstance(value, types[kind]) or (kind in ("integer", "number") and isinstance(value, bool)):
            raise ProviderError(f"Invalid configuration value: {name}")
        if "enum" in rule and value not in rule["enum"]:
            raise ProviderError(f"Invalid configuration choice: {name}")
        if kind == "object":
            if any(key not in value for key in rule.get("required", [])):
                raise ProviderError(f"Missing configuration field: {name}")
            props = rule.get("properties", {})
            if rule.get("additionalProperties") is False and any(key not in props for key in value):
                raise ProviderError(f"Unknown configuration field: {name}")
            for key, item in value.items():
                if key in props: visit(item, props[key], f"{name}.{key}")
        elif kind == "array" and "items" in rule:
            for item in value: visit(item, rule["items"], name + "[]")
    visit(config, schema, "config")


def unpack_package(archive, destination):
    """Extract a bounded ZIP into an empty staging directory, then validate it."""
    destination = Path(destination)
    with zipfile.ZipFile(archive) as stream:
        entries = stream.infolist()
        if len(entries) > MAX_FILES or sum(i.file_size for i in entries) > MAX_BYTES:
            raise ProviderError("Provider package exceeds the size limit")
        roots = [i.filename for i in entries if i.filename.endswith("manifest.json")]
        if "manifest.json" in roots: prefix = ""
        elif len(roots) == 1 and roots[0].count("/") == 1: prefix = roots[0].split("/")[0] + "/"
        else: raise ProviderError("ZIP must contain one provider manifest.json")
        seen = set()
        for info in entries:
            relative_path(info.filename.rstrip("/"))
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ProviderError("Package symlinks are not supported")
            if info.is_dir(): continue
            if prefix and not info.filename.startswith(prefix):
                raise ProviderError("Unexpected file outside provider folder")
            name = info.filename[len(prefix):]
            relative_path(name)
            if name.casefold() in seen: raise ProviderError("Duplicate package path")
            seen.add(name.casefold())
            target = destination.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with stream.open(info) as source, target.open("xb") as output:
                remaining = info.file_size
                while remaining:
                    chunk = source.read(min(65536, remaining))
                    if not chunk: raise ProviderError("Truncated provider package")
                    output.write(chunk)
                    remaining -= len(chunk)
    return validate_folder(destination)


def pack_package(folder, archive):
    folder = Path(folder).resolve()
    validate_folder(folder)
    paths = sorted(p for p in folder.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    if len(paths) > MAX_FILES or sum(p.stat().st_size for p in paths) > MAX_BYTES:
        raise ProviderError("Provider package exceeds the size limit")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as stream:
        for path in paths:
            if path.is_symlink() or not path.resolve().is_relative_to(folder):
                raise ProviderError("Package symlinks are not supported")
            stream.write(path, path.relative_to(folder).as_posix())
