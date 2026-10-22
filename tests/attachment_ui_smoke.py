"""Attachment path fallback and inline user tags with native-history replay."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('UMEKO_LANGUAGE','zh')
os.environ["UMEKO_DATA_DIR"] = tempfile.mkdtemp(prefix="umeko-attachment-ui-")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
from PySide6.QtCore import QPoint, QPointF, Qt, QMetaObject
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from app.storage import Store
from app.message_attachments import attachment_prompt
from app.transcripts import preview
from main import create_application

store = Store()
store.data["agent"]["agentDir"] = str(store.directory / "agent")
store.data.update(selectedProvider="internal", selectedModel="umeko-default", providers=[{"id":"internal", "name":"Fixture", "api":"internal", "baseUrl":"", "key":"", "models":[{"upstream":"default", "alias":"umeko-default"}]}])
store.data["providers"][0]["models"][0].update(vision=False, visionAuto=False)
store.save()
app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))


def find(name):
    stack = [window.contentItem()]
    while stack:
        item = stack.pop()
        if item.objectName() == name: return item
        stack.extend(item.childItems())
    raise AssertionError(name)


def capture(name):
    out = ROOT / "artifacts/screenshots" / (name + ".png")
    out.parent.mkdir(parents=True, exist_ok=True)
    assert window.grabWindow().save(str(out))


try:
    backend.setTheme("yanami")
    file = store.directory / "Kimi Code.lnk"
    file.write_text("synthetic shortcut fixture; never executed")
    image = store.directory / "screenshot.png"
    pixels = QImage(30,30,QImage.Format_ARGB32); pixels.fill(Qt.blue); assert pixels.save(str(image))
    backend.addAttachments(json.dumps([file.as_uri(), image.as_uri()]))
    notices = []; backend.toast.connect(notices.append)
    with patch.object(backend, "_command_pi", return_value=True) as command:
        assert backend._send("你给我详细讲解这些附件")
        raw = command.call_args.kwargs["text"]
        assert command.call_args.kwargs["images"] == []
        assert str(file) in raw and str(image) in raw
    backend.chatChanged.emit(); backend.transcriptChanged.emit(); QTest.qWait(250)
    assert "未启用视觉，降级为普通文件路径" in notices
    assert find("userAttachment_0_0").isVisible() and find("userAttachment_0_1").isVisible()
    assert find("userAttachmentName_0_0").property("text") == "Kimi Code.lnk"
    assert backend.displayMessages[0]["text"] == "你给我详细讲解这些附件"
    assert "附件（用户提供" not in backend.displayMessages[0]["text"]
    assert find("promptInput").property("text") == ""
    bubble = find("messageBubble_0")
    assert bubble.height() < 65, bubble.height()
    assert bubble.x() > 0
    capture("58-inline-user-attachments")
    # File tags participate in cross-region selection and copying.
    selection = find("chatSelection")
    QMetaObject.invokeMethod(selection, "selectAll")
    QMetaObject.invokeMethod(selection, "copy")
    copied = app.clipboard().text()
    assert "Kimi Code.lnk" in copied and "screenshot.png" in copied
    assert "用户提供的路径" not in copied and str(store.directory) not in copied
    # Reopening native JSONL projects the same tags without rewriting its contents.
    native = store.directory / "fixture.jsonl"
    native.write_text("\n".join(json.dumps(row,ensure_ascii=False) for row in [
        {"type":"session","cwd":str(store.directory)},
        {"type":"message","id":"u1","parentId":None,"message":{"role":"user","content":[{"type":"text","text":raw}]}}
    ]), encoding="utf-8")
    original = native.read_bytes()
    backend._view.messages, backend._view.tree = preview(native)
    backend.chatChanged.emit(); backend.transcriptChanged.emit(); backend.viewChanged.emit(); QTest.qWait(150)
    assert find("userAttachmentName_0_0").property("text") == "Kimi Code.lnk"
    assert native.read_bytes() == original
    # Attachment-only messages and long, literal names stay inside a narrow bubble.
    long_name = "example<&>" + "very-long-file-name-" * 10 + ".txt"
    backend._view.messages = [{"role":"user","text":attachment_prompt("", [{"kind":"file","path":"/tmp/"+long_name}])}]
    backend.chatChanged.emit(); backend.transcriptChanged.emit(); QTest.qWait(100)
    window.resize(1060,700); QTest.qWait(150)
    chip, bubble = find("userAttachment_0_0"), find("messageBubble_0")
    assert chip.width() <= bubble.width() - 28
    assert find("userAttachmentName_0_0").property("text") == long_name
    assert backend.displayMessages[0]["text"] == ""
    capture("59-attachment-only-narrow")
    assert not warnings, "\n".join(warnings)
    print("ATTACHMENT_UI_OK: text-only image fallback, clean inline tags, selection/copy, native-history replay, attachment-only/long names, narrow window")
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
