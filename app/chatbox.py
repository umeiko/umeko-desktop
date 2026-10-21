"""Bounded, cached presentation of local references from Pi tool results."""
from functools import lru_cache
from pathlib import Path
from PySide6.QtCore import QUrl
from PySide6.QtGui import QImageReader


def result_media(name, result):
    details = (result or {}).get("details")
    payload = details.get("umekoChatbox") if isinstance(details, dict) else None
    if not isinstance(payload, dict): return []
    if name != "submit_to_chatbox" or (result or {}).get("isError") or payload.get("version") != 1:
        return []
    items = payload.get("items")
    return items[:12] if isinstance(items, list) else []


def media_view(items):
    out = []
    for item in items[:12]:
        if not isinstance(item, dict): continue
        path, kind = item.get("path"), item.get("kind")
        if not isinstance(path, str) or not Path(path).is_absolute() or any(c in path for c in "\0\r\n") or kind not in ("image", "file", "folder"):
            continue
        title, caption = item.get("title"), item.get("caption")
        out.append(dict(_media_item(path, kind, str(title or Path(path).name)[:160], str(caption or "")[:1000], str(item.get("modified", "")))))
    return out


@lru_cache(maxsize=256)
def _media_item(path, kind, title, caption, modified):
    file = Path(path)
    try:
        exists, size = file.exists(), file.stat().st_size
    except OSError:
        exists, size = False, 0
    row = {"path": path, "name": file.name, "title": title, "caption": caption, "kind": kind,
           "bytes": size, "url": QUrl.fromLocalFile(path).toString(QUrl.FullyEncoded), "preview": False, "previewNote": ""}
    if kind == "image":
        reader = QImageReader(path)
        dimensions = reader.size()
        row.update(pixelWidth=dimensions.width(), pixelHeight=dimensions.height())
        row["preview"] = exists and 0 < size <= 20 * 1024 * 1024 and dimensions.width() > 0 and dimensions.height() > 0 and dimensions.width() * dimensions.height() <= 16_000_000
        row["previewNote"] = "" if row["preview"] else "图片过大或暂不可预览，可打开原文件查看"
    return row
