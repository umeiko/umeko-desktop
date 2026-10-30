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


class PackageValidationError(ProviderError):
    def __init__(self, entry, rule, detail, conflict=""):
        self.entry, self.rule, self.detail, self.conflict = str(entry), rule, detail, conflict
        text = f'ZIP 条目 {json.dumps(self.entry, ensure_ascii=False)}\n规则 [{rule}]：{detail}'
        if conflict: text += '\n冲突条目：' + json.dumps(conflict, ensure_ascii=False)
        super().__init__(text)


def normalize_package_path(value, directory=False):
    def fail(rule, detail): raise PackageValidationError(value, rule, detail)
    if not isinstance(value, str): fail("PATH_TYPE", "路径必须是字符串")
    if "\x00" in value: fail("NUL_BYTE", "路径包含空字符")
    if value.startswith(("/", "\\")): fail("ABSOLUTE_PATH", "不允许绝对路径或网络共享路径")
    if "\\" in value: fail("BACKSLASH", "ZIP 路径请使用正斜杠 /，不要使用反斜杠")
    if ":" in value: fail("COLON", "路径不能包含冒号、盘符或文件流名称")
    parts = value[:-1].split("/") if directory and value.endswith("/") else value.split("/")
    normalized = []
    for part in parts:
        if part == "..": fail("PARENT_PATH", "路径包含上级目录段 ..，可能逃出插件目录")
        if not part: fail("EMPTY_SEGMENT", "路径包含空目录段或连续的斜杠")
        if part == ".": continue
        if part.endswith((".", " ")): fail("TRAILING_DOT_SPACE", "文件或目录名不能以点或空格结尾")
        if re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part, re.I):
            fail("RESERVED_NAME", "路径包含 Windows 保留名称")
        normalized.append(part)
    if not normalized and not directory: fail("EMPTY_PATH", "文件路径不能为空")
    return "/".join(normalized)


def relative_path(value):
    return PurePosixPath(normalize_package_path(value))


def validate_folder(folder):
    folder = Path(folder).resolve()
    def read(name):
        path = folder.joinpath(*relative_path(name).parts)
        if not path.resolve().is_relative_to(folder) or path.is_symlink():
            raise PackageValidationError(name, "SYMLINK", "不支持符号链接，请打包实际文件")
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
    description = manifest.get("description", "")
    if not isinstance(description, str):
        raise ProviderError("Provider description must be a string")
    manifest["description"] = description.strip()
    entry, sep, factory = manifest.get("entrypoint", "").partition(":")
    if not sep or not factory.isidentifier() or not entry.endswith(".py"):
        raise ProviderError("entrypoint must be scripts/provider.py:create_provider")
    if not folder.joinpath(*relative_path(entry).parts).is_file():
        raise ProviderError("Provider entrypoint is missing")
    manifest["entrypoint"] = relative_path(entry).as_posix() + ":" + factory
    manifest["config"] = relative_path(manifest.get("config", "config.json")).as_posix()
    manifest["configSchema"] = relative_path(manifest.get("configSchema", "config.schema.json")).as_posix()
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
        normalized, seen = [], {}
        for info in entries:
            original = info.orig_filename
            name = normalize_package_path(original, info.is_dir())
            if stat.S_ISLNK(info.external_attr >> 16):
                raise PackageValidationError(original, "SYMLINK", "不支持符号链接，请打包实际文件")
            mode = stat.S_IFMT(info.external_attr >> 16)
            if mode not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise PackageValidationError(original, "FILE_TYPE", "不支持设备、管道等特殊文件")
            if not name: continue  # A harmless ./ directory marker.
            key = name.casefold()
            if key in seen:
                previous, is_dir = seen[key]
                if is_dir and info.is_dir(): continue
                raise PackageValidationError(original, "DUPLICATE_PATH", "规范化后存在重复或大小写冲突的路径", previous)
            for existing, (original, is_dir) in seen.items():
                if (key.startswith(existing + "/") and not is_dir) or (existing.startswith(key + "/") and not info.is_dir()):
                    raise PackageValidationError(info.orig_filename, "PATH_TYPE_CONFLICT", "同一路径同时被用作文件和目录", original)
            seen[key] = (info.orig_filename, info.is_dir())
            normalized.append((info, name))
        roots = [name for info, name in normalized if not info.is_dir() and PurePosixPath(name).name == "manifest.json"]
        if "manifest.json" in roots: prefix = ""
        elif len(roots) == 1 and roots[0].count("/") == 1: prefix = roots[0].split("/")[0] + "/"
        else: raise ProviderError("ZIP must contain one provider manifest.json")
        for info, normalized_name in normalized:
            if info.is_dir(): continue
            if prefix and not normalized_name.startswith(prefix):
                raise PackageValidationError(info.orig_filename, "OUTSIDE_PROVIDER_FOLDER", "文件位于插件根目录之外")
            name = normalized_name[len(prefix):]
            relative_path(name)
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
                raise PackageValidationError(path.relative_to(folder).as_posix(), "SYMLINK", "不支持符号链接，请打包实际文件")
            stream.write(path, relative_path(path.relative_to(folder).as_posix()).as_posix())
