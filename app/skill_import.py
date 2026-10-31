"""Preview inert Skill folders/archives in memory; write only confirmed plans."""
from __future__ import annotations

import os
import shutil
import stat
import tempfile
import uuid
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from umeko_provider_sdk.packages import normalize_package_path

# Same import bounds as the existing Widget package importer.
MAX_BYTES = 128 * 1024 * 1024
MAX_FILES = 2048
_plans: dict[str, "_Plan"] = {}


@dataclass
class _Skill:
    row: dict
    files: dict[str, bytes]
    target: Path
    existed: bool


@dataclass
class _Plan:
    destination: Path
    skills: list[_Skill]


class _Names:
    """Apply the existing archive path rules to explicit and implicit folders."""
    def __init__(self):
        self.paths = {}

    def add(self, original, directory=False):
        name = normalize_package_path(original, directory)
        if not name:
            return ""
        parts = name.split("/")
        for count in range(1, len(parts) + 1):
            path = "/".join(parts[:count])
            is_directory = directory or count < len(parts)
            explicit = count == len(parts)
            previous = self.paths.get(path.casefold())
            if previous:
                old_path, old_directory, old_explicit = previous
                if path != old_path or is_directory != old_directory or (explicit and old_explicit):
                    raise ValueError("技能包存在重复、大小写或文件与目录冲突的路径")
                explicit = explicit or old_explicit
            self.paths[path.casefold()] = (path, is_directory, explicit)
        return name


def _linked(path):
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def _read_source(source):
    """Read a bounded immutable payload. Nothing is extracted to disk."""
    source = Path(source).expanduser()
    if _linked(source):
        raise ValueError("不支持符号链接或目录联接，请选择实际文件夹或压缩包")
    source_info = source.stat()
    mode = source_info.st_mode
    names, files = _Names(), {}
    total = 0
    entries = 0

    def reserve(name, directory, size):
        nonlocal entries, total
        entries += 1
        total += size
        if entries > MAX_FILES or total > MAX_BYTES:
            raise ValueError("技能包超过 128 MiB 或 2048 个条目的限制")
        return names.add(name, directory)

    if stat.S_ISDIR(mode):
        def walk(directory, prefix=""):
            with os.scandir(directory) as stream:
                for entry in stream:
                    path = Path(entry.path)
                    info = entry.stat(follow_symlinks=False)
                    if _linked(path) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                        raise ValueError("技能文件夹不支持链接或特殊文件")
                    is_directory = stat.S_ISDIR(info.st_mode)
                    name = reserve(prefix + entry.name, is_directory, 0 if is_directory else info.st_size)
                    if is_directory:
                        walk(path, name + "/")
                    else:
                        with path.open("rb") as document:
                            content = document.read(info.st_size + 1)
                        if len(content) != info.st_size:
                            raise ValueError("技能源文件在读取期间发生变化，请重新预览")
                        files[name] = content
        walk(source)
    elif stat.S_ISREG(mode) and source.suffix.lower() in (".zip", ".skill"):
        if source_info.st_size > MAX_BYTES:
            raise ValueError("技能压缩包超过 128 MiB 限制")
        with zipfile.ZipFile(source) as archive:
            normalized = []
            for info in archive.infolist():
                kind = stat.S_IFMT(info.external_attr >> 16)
                if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise ValueError("技能压缩包不支持链接或特殊文件")
                if info.flag_bits & 1:
                    raise ValueError("不支持加密的技能压缩包")
                if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise ValueError("技能压缩包只支持 ZIP stored/deflate 压缩")
                name = reserve(info.orig_filename, info.is_dir(), info.file_size)
                if name:
                    normalized.append((info, name))
            for info, name in normalized:
                if info.is_dir():
                    continue
                with archive.open(info) as document:
                    content = document.read(info.file_size + 1)
                if len(content) != info.file_size:
                    raise ValueError("技能压缩包内容大小无效")
                files[name] = content
    else:
        raise ValueError("请选择包含 SKILL.md 的文件夹、ZIP 或 .skill 压缩包")
    return source, files, source.stem if stat.S_ISREG(mode) else source.name


def _replace_target(destination, name, catalog):
    target = destination / name
    conflicts = [row for row in catalog if str(row.get("name", "")).casefold() == name.casefold()]
    for row in conflicts:
        candidate = Path(row.get("path", ""))
        if row.get("packageSource") or row.get("source") in ("package", "extension") or row.get("metadata", {}).get("origin") == "package":
            return target, True, False, "同名技能来自包或扩展，只能跳过；请先在对应管理入口处理。"
        if not candidate.is_absolute() or candidate.name != "SKILL.md":
            return target, True, False, "同名技能不在所选标准技能目录内，只能跳过。"
        folder = candidate.parent
        if _linked(folder) or _linked(candidate) or not folder.resolve().is_relative_to(destination) or folder.resolve() == destination:
            return target, True, False, "同名技能位于所选目录之外，只能跳过。"
        if len(conflicts) > 1:
            return target, True, False, "存在多个同名技能，只能跳过；请先处理已有冲突。"
        target = folder.resolve()
    existed = target.exists()
    if existed:
        if _linked(target) or not target.is_dir() or not (target / "SKILL.md").is_file() or _linked(target / "SKILL.md"):
            return target, True, False, "目标路径已存在且不是可替换的本地技能文件夹，只能跳过。"
        return target, True, True, ""
    if conflicts:
        return target, True, False, "已有技能路径不可用，只能跳过；请刷新技能目录。"
    return target, False, False, ""


def preview_import(source, destination, catalog, validate_markdown):
    """Return JSON-safe preview data; the sole pending plan retains source bytes.

    validate_markdown receives [{key, markdown, directoryName}] and returns
    [{key, name, description, valid, diagnostics}]. It must not create files.
    A new preview releases the previous plan rather than retaining 128 MiB per UI attempt.
    """
    _plans.clear()
    preview = {"planId": "", "source": Path(source).name, "skills": [], "errors": []}
    try:
        original_destination = Path(destination).expanduser()
        if any(_linked(path) for path in (original_destination, *original_destination.parents)):
            raise ValueError("技能目标目录不能使用符号链接或目录联接")
        destination = original_destination.resolve()
        source, files, source_name = _read_source(source)
        roots = []
        for file in sorted(files, key=lambda value: (value.count("/"), value)):
            path = PurePosixPath(file)
            if path.name != "SKILL.md":
                continue
            root = path.parent
            if not any(root == old or old in root.parents for old in roots):
                roots.append(root)
        if not roots:
            raise ValueError("没有找到 SKILL.md")
        documents = []
        for index, root in enumerate(roots):
            content = files[(root / "SKILL.md").as_posix()]
            try:
                markdown = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                markdown = None
            documents.append({"key": str(index), "markdown": markdown,
                              "directoryName": root.name or source_name})
        valid_documents = [document for document in documents if document["markdown"] is not None]
        results = {str(row["key"]): row for row in validate_markdown(valid_documents)} if valid_documents else {}
        skills = []
        for index, root in enumerate(roots):
            result = results.get(str(index), {})
            name = str(result.get("name") or documents[index]["directoryName"])[:256]
            row = {"name": name, "description": str(result.get("description", ""))[:1024], "conflict": False, "replaceable": False}
            if not result.get("valid"):
                row["error"] = "SKILL.md 必须为 UTF-8 且通过 Pi 原生格式验证。" + "；".join(str(item)[:500] for item in result.get("diagnostics", [])[:8])
            # The native validator owns metadata rules; this is the destination
            # path boundary, even when a caller supplies a faulty callback.
            if not name or normalize_package_path(name) != name or "/" in name:
                row["error"] = "技能名称不能作为安全的目标文件夹名称。"
            target, conflict, replaceable, error = _replace_target(destination, name, catalog)
            row.update(conflict=conflict, replaceable=replaceable)
            if error:
                row["error"] = error
            payload = {PurePosixPath(path).relative_to(root).as_posix(): data for path, data in files.items() if PurePosixPath(path).is_relative_to(root)}
            skills.append(_Skill(row, payload, target, conflict))
        by_name = {}
        for item in skills:
            by_name.setdefault(item.row["name"].casefold(), []).append(item)
        for duplicates in by_name.values():
            if len(duplicates) > 1:
                for item in duplicates:
                    item.row.update(conflict=True, replaceable=False, error="导入批次中存在多个同名技能，请分开处理。")
        token = uuid.uuid4().hex
        _plans[token] = _Plan(destination, skills)
        preview.update(planId=token, skills=[dict(item.row) for item in skills])
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, NotImplementedError, zlib.error, EOFError) as error:
        preview["errors"] = [str(error)[:1500]]
    return preview


def discard_import(preview):
    token = preview.get("planId", "") if isinstance(preview, dict) else str(preview)
    _plans.pop(token, None)


def commit_import(preview, decisions, expected_root):
    """Consume a confirmed plan, atomically replacing one skill at a time."""
    token = preview.get("planId", "") if isinstance(preview, dict) else str(preview)
    plan = _plans.get(token)
    if plan is None:
        raise ValueError("导入预览已关闭或被新的预览替代，请重新预览")
    if Path(expected_root).expanduser().resolve() != plan.destination:
        raise ValueError("技能目标目录与已确认的预览不一致")
    if not isinstance(decisions, dict) or any(value not in ("skip", "replace") for value in decisions.values()):
        raise ValueError("导入决定只能为 skip 或 replace")
    _plans.pop(token)
    result = {"imported": [], "skipped": [], "errors": []}
    selected = []
    for item in plan.skills:
        row = item.row
        choice = decisions.get(row["name"])
        if row.get("error") or choice == "skip" or (row["conflict"] and (choice != "replace" or not row["replaceable"])):
            result["skipped"].append(row["name"])
        else:
            selected.append(item)
    if not selected:
        return result
    plan.destination.mkdir(parents=True, exist_ok=True)
    for item in selected:
        temporary = Path(tempfile.mkdtemp(prefix=".umeko-import-", dir=plan.destination))
        stage, backup = temporary / "skill", temporary / "previous"
        old_moved = False
        cleanup = True
        try:
            stage.mkdir()
            for name, content in item.files.items():
                target = stage.joinpath(*PurePosixPath(name).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            if item.existed:
                item.target.rename(backup)
                old_moved = True
            stage.rename(item.target)
            result["imported"].append(item.row["name"])
        except OSError:
            if old_moved:
                try:
                    backup.rename(item.target)
                except OSError as error:
                    cleanup = False
                    raise RuntimeError("导入失败；原技能保留于 " + temporary.name + "/previous，请恢复后重试。") from error
            result["skipped"].append(item.row["name"])
            result["errors"].append({"name": item.row["name"], "error": "写入失败；已有技能已保留。"})
        finally:
            if cleanup:
                shutil.rmtree(temporary)
    return result
