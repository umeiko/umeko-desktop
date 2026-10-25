"""Separate desktop attachment presentation from Pi's original prompt text."""
import re
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import urlsplit


ATTACHMENT_HEADER = "\n\n附件（用户提供的路径；按需使用原生工具读取）：\n"
ATTACHMENT_ONLY_TEXT = "请查看这些附件。"


def split_attachments(text):
    body, marker, tail = text.rpartition(ATTACHMENT_HEADER)
    if not marker:
        return text, []
    attachments = []
    for line in tail.splitlines():
        match = re.fullmatch(r"- (file|folder|image|web): (.+)", line)
        if not match:
            return text, []  # Never hide arbitrary prose or a partially written section.
        kind, path = match.groups()
        name = (PureWindowsPath(path) if "\\" in path else PurePosixPath(path)).name or path
        item = {"kind": kind, "path": path, "name": name}
        if kind == "web":
            try:
                url = urlsplit(path)
                if url.scheme not in ("http", "https") or not url.hostname or url.username is not None:
                    return text, []
                item.update(url=path, name=url.hostname)
            except ValueError:
                return text, []
        attachments.append(item)
    if not attachments:
        return text, []
    return ("" if body == ATTACHMENT_ONLY_TEXT else body), attachments


def attachment_prompt(text, attachments):
    if not attachments:
        return text
    return (text or ATTACHMENT_ONLY_TEXT) + ATTACHMENT_HEADER + "\n".join(
        f"- {item['kind']}: {item['path']}" for item in attachments)
