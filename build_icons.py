"""Small, consistent 24 px vector icon set; no icon font or remote assets."""
from pathlib import Path

paths = {
    "pin": '<path d="m16 3 5 5-4 1-3 5-4 1-3-3 1-4 5-3ZM8 15l-5 6"/>',
    "archive": '<rect x="3" y="3" width="18" height="5" rx="1"/><path d="M5 8v13h14V8M9 12h6"/>',
    "download": '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
    "file": '<path d="M14 2H5v20h14V7Zm0 0v5h5M8 12h8m-8 4h6"/>',
    "image": '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8" cy="8" r="1.5"/><path d="m21 15-5-5L5 21"/>',
    "branch": '<circle cx="6" cy="5" r="2"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="5" r="2"/><path d="M6 7v10m0-5h6a6 6 0 0 0 6-5"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.7 8.5a2.4 2.4 0 1 1 4.2 1.6c-1.2.7-1.9 1.3-1.9 2.9m0 3h.01"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "x": '<path d="m6 6 12 12M18 6 6 18"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/>',
    "chat": '<path d="M20 11.5a7.8 7.8 0 0 1-8 7.5H5l-3 2 1.4-5.3A7.3 7.3 0 0 1 4 6.3 8.2 8.2 0 0 1 20 11.5Z"/>',
    "folder": '<path d="M3 7V5a1 1 0 0 1 1-1h5l2 3h9a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1Z"/>',
    "folder-code": '<path d="M3 7V5h6l2 3h10v12H3Z"/><path d="m10 12-3 3 3 3m4-6 3 3-3 3"/>',
    "code": '<path d="m8 5-6 7 6 7m8-14 6 7-6 7m-3-16-2 18"/>',
    "terminal": '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="m7 8 4 4-4 4m6 0h4"/>',
    "bulb": '<path d="M9 18v-2c0-2-4-3-4-7a7 7 0 0 1 14 0c0 4-4 5-4 7v2m-6 0h6m-5 3h4m-2-3v-7m-2-2 2 2 2-2"/>',
    "layers": '<path d="m12 3 10 5-10 5L2 8Zm-9 9 9 5 9-5M3 16l9 5 9-5"/>',
    "settings": '<path d="m9 3-1 3-3 1-2 3 2 2-1 3 2 3h3l2 3 3-1 1-3 3-1 2-3-2-2 1-3-2-3h-3l-2-2Z"/><circle cx="11.5" cy="12" r="3"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "chevron-right": '<path d="m9 6 6 6-6 6"/>',
    "arrow-up": '<path d="M12 20V4m-6 6 6-6 6 6"/>',
    "send": '<path d="M12 20V4m-6 6 6-6 6 6"/>',
    "arrow-right": '<path d="M4 12h16m-6-6 6 6-6 6"/>',
    "arrow-left": '<path d="M20 12H4m6-6-6 6 6 6"/>',
    "maximize": '<rect x="5" y="5" width="14" height="14" rx="1"/>',
    "layout": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
    "lock": '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 5v2"/>',
    "cpu": '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4m6-4v4M9 18v4m6-4v4M2 9h4m-4 6h4m12-6h4m-4 6h4"/><rect x="9" y="9" width="6" height="6" rx="1"/>',
    "check": '<path d="m5 12 4 4L19 6"/>',
    "sliders": '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3" fill="#fcfcfa"/><circle cx="15" cy="17" r="3" fill="#fcfcfa"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',
    "spark": '<path d="m12 3 2.8 6.2L21 12l-6.2 2.8L12 21l-2.8-6.2L3 12l6.2-2.8Z"/>',
    "building": '<path d="M5 21V3h14v18M2 21h20M9 7h1m4 0h1m-6 4h1m4 0h1m-5 10v-5h4v5"/>',
    "server": '<rect x="3" y="3" width="18" height="7" rx="2"/><rect x="3" y="14" width="18" height="7" rx="2"/><path d="M7 6.5h.1M7 17.5h.1M12 6.5h5M12 17.5h5"/>',
    "edit": '<path d="m15 4 5 5M4 20l5-1L21 7a2.1 2.1 0 0 0-4-4L5 15Z"/>',
    "trash": '<path d="M3 6h18M9 6V3h6v3M6 6l1 15h10l1-15m-8 4v7m4-7v7"/>',
    "copy": '<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
    "eye": '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
    "eye-off": '<path d="m3 3 18 18M9 5a12 12 0 0 1 13 7 18 18 0 0 1-4 4M6 6a19 19 0 0 0-4 6s4 7 10 7a12 12 0 0 0 4-1"/>',
    "refresh": '<path d="M20 9a8 8 0 0 0-14-5L3 7m0-5v5h5m-4 8a8 8 0 0 0 14 5l3-3m0 5v-5h-5"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="1"/>',
}
root = Path(__file__).resolve().parent / "app/icons"
root.mkdir(parents=True, exist_ok=True)
for name, path in paths.items():
    color = "#ffffff" if name in ("send", "stop") else "#7c877d"
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round">{path}</svg>'
    (root / (name + ".svg")).write_text(svg, encoding="utf-8")
mark = '<path d="m9 5-6 7 6 7m6-14 6 7-6 7m-2-9-2 4"/>'
(root / "mark.svg").write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#42674d" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round">{mark}</svg>')
(root / "logo.svg").write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 36"><rect width="36" height="36" rx="10" fill="#365e47"/><g transform="translate(6 6)" fill="none" stroke="#edf3e8" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{mark}</g></svg>')
print("Vector icons:", len(paths) + 2)
try:
    from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPainterPath
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtSvg import QSvgRenderer
    app = QGuiApplication.instance() or QGuiApplication([])
    image = QImage(str(root / "app.png"))
    if image.isNull():
        image = QImage(256, 256, QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        QSvgRenderer(str(root / "logo.svg")).render(painter)
        painter.end()
    else:
        rounded = QImage(256, 256, QImage.Format_ARGB32)
        rounded.fill(Qt.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, 256, 256), 46, 46)
        painter.setClipPath(clip)
        painter.drawImage(QRectF(0, 0, 256, 256), image)
        painter.end()
        image = rounded
    assert image.save(str(root / "app.ico"))
    from PySide6.QtCore import QByteArray, QBuffer, QIODevice
    import struct
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    assert image.save(buffer, "PNG")
    block = b"ic08" + struct.pack(">I", len(data) + 8) + bytes(data)
    (root / "app.icns").write_bytes(b"icns" + struct.pack(">I", len(block) + 8) + block)
except ImportError:
    pass
