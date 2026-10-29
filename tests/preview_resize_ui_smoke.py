"""Right-pane pointer limits, deferred snap collapse, mascots and draft preservation."""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["UMEKO_DATA_DIR"] = tempfile.mkdtemp(prefix="umeko-preview-resize-")
os.environ["UMEKO_LANGUAGE"] = "zh"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from main import create_application

app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))


def find(name):
    stack = [window.contentItem()]
    while stack:
        item = stack.pop()
        if item.objectName() == name: return item
        stack.extend(item.childItems())
    return None


def wait(predicate, label):
    for _ in range(400):
        QTest.qWait(10)
        if predicate(): return
    raise AssertionError(label + "\n" + "\n".join(warnings))


def begin():
    wait(lambda: not pane.property("moving"), "Preview animation did not settle")
    point = handle.mapToScene(QPointF(handle.width()/2, 250)).toPoint()
    width = pane.width()
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, point)
    assert handle.property("pressed") and handle.property("resizing")
    return point, width


def move(point, width, requested):
    QTest.mouseMove(window, point + QPoint(round(width-requested), 0))
    QTest.qWait(25)
    assert handle.isVisible() and handle.property("pressed"), "Preview lost the active pointer grab"
    assert pane.property("opened"), "Preview collapsed before mouse release"


def release(point, width, requested):
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, point + QPoint(round(width-requested), 0))
    QTest.qWait(60)
    wait(lambda: not pane.property("moving"), "Released preview did not settle")


try:
    QTest.qWait(200)
    window.resize(1700, 1050)
    record = backend._view
    record.id = "preview-resize-fixture"
    record.messages = [{"role": "user", "text": "检查界面。"}, {"role": "assistant", "text": "任务已经完成。"}]
    backend.chatChanged.emit()
    file = backend.store.directory / "completed.jsonl"
    file.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in [
        {"type": "session", "id": "completed", "cwd": str(backend.store.directory)},
        {"type": "message", "id": "u", "message": {"role": "user", "content": [{"type": "text", "text": "检查任务。"}]}},
        {"type": "message", "id": "a", "parentId": "u", "message": {"role": "assistant", "content": [{"type": "text", "text": "检查完成。"}]}}
    ]) + "\n", encoding="utf-8")
    backend.subagents.merge(record, {"id": "resize-child", "status": "completed", "avatarSlot": 1, "outputFile": str(file)})
    backend.subagents.open("resize-child")
    pane, handle = find("webPane"), find("webPaneResizeHandle")
    wait(lambda: not backend.subagents.loading and not pane.property("moving") and find("subagentReplyMascot_1") is not None, "Child conversation did not settle")
    wait(lambda: find("replyEndMascot_1") is not None, "Parent closing mascot did not appear")
    parent_mascot = find("replyEndMascot_1")
    child_mascot = find("subagentReplyMascot_1")
    for scale in (.5, 1., 1.5, 2.):
        backend.setFontScale(scale)
        QTest.qWait(60)
        assert child_mascot.width() == parent_mascot.width() == 56, "Role mascot grew beyond the main mascot"
    backend.setFontScale(1.5)
    QTest.qWait(120)
    prompt = find("promptInput")
    prompt.setProperty("text", "保留这条未发送的消息")
    maximum = window.property("webMaximumWidth")
    point, width = begin()
    move(point, width, maximum)
    assert abs(find("chatPage").width()-window.property("chatMinimumWidth")) < 2
    assert not parent_mascot.property("reaction"), "The limit hint appeared before continued dragging"
    QTest.qWait(100)
    assert not parent_mascot.property("reaction"), "Holding still retriggered the limit hint"
    move(point, width, maximum+36)
    assert parent_mascot.property("reaction") == "已经不能更窄啦！"
    parent_mascot.setProperty("reaction", "")
    move(point, width, maximum+60)
    assert not parent_mascot.property("reaction"), "One drag repeatedly restarted the hint"
    release(point, width, maximum+60)
    assert abs(pane.width()-maximum) < 2 and not handle.property("resizing")

    threshold = window.property("webMinimumWidth")*.7
    point, width = begin()
    move(point, width, threshold-25)
    # Reversing before release cancels snap collapse, like the left sidebar.
    move(point, width, threshold+25)
    release(point, width, threshold+25)
    assert pane.property("opened") and pane.width() == window.property("webMinimumWidth")
    remembered = window.property("webPreferredWidth")
    point, width = begin()
    move(point, width, threshold-1)
    release(point, width, threshold-1)
    assert not pane.property("opened") and pane.width() < .5
    assert not backend.subagents.selected and window.property("webPreferredWidth") == remembered
    assert backend.messageCount == 2 and prompt.property("text") == "保留这条未发送的消息"
    backend.subagents.open("resize-child")
    wait(lambda: not backend.subagents.loading and not pane.property("moving"), "Could not reopen collapsed child")
    assert abs(pane.width()-remembered) < 1 and backend.subagents.messageCount == 2

    # When the closing avatar is not present, the same Yanami hint stays
    # discoverable beside the composer without changing focus or the transcript.
    record.phase = "running"
    backend.chatChanged.emit()
    QTest.qWait(80)
    point, width = begin()
    move(point, width, maximum+36)
    fallback = find("chatWidthLimitMascot")
    assert fallback.isVisible() and fallback.property("reaction") == "已经不能更窄啦！"
    release(point, width, maximum+36)
    assert backend.messageCount == 2 and prompt.property("text") == "保留这条未发送的消息"
    screenshots = ROOT / "artifacts/screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    assert window.grabWindow().save(str(screenshots / "preview-resize-limit.png"))
    record.phase = "idle"
    backend.chatChanged.emit()
    assert not warnings, "\n".join(warnings)
    print("PREVIEW_RESIZE_UI_OK: equal mascot size across font scales, minimum chat width, continued-drag hint once per gesture, deferred snap/reversal, remembered width, child/history/draft preservation and fallback mascot")
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
