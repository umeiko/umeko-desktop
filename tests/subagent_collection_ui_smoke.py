"""Bounded child collections, multiline summaries and native child attachment drops."""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ["UMEKO_LANGUAGE"] = "zh"
os.environ["UMEKO_DATA_DIR"] = tempfile.mkdtemp(prefix="umeko-child-collection-")
from PySide6.QtCore import QObject, QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtTest import QTest
from main import create_application

app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))


def items():
    pending = [window.contentItem()]
    while pending:
        item = pending.pop()
        yield item
        pending.extend(item.childItems())


def find(name):
    return next(item for item in items() if item.objectName() == name)


def wait(predicate, label):
    for _ in range(400):
        QTest.qWait(10)
        if predicate(): return
    raise AssertionError(label + "\n" + "\n".join(warnings))


def click(name):
    item = find(name)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, item.mapToScene(item.boundingRect().center()).toPoint())


def compact_summaries():
    for item in items():
        if item.isVisible() and item.objectName().startswith(("subagentSummary_", "subagentTitle_", "subagentHeaderSummary")):
            text = item.property("text")
            assert "\n" not in text and "\r" not in text, text
            assert item.property("lineCount") == 1
            assert item.width() >= 0 and item.height() <= item.parentItem().height()


try:
    QTest.qWait(200)
    window.resize(1900, 1040)
    record = backend._view
    record.id, record.title = "collection-fixture", "子智能体集合验收"
    directory = Path(os.environ["UMEKO_DATA_DIR"])
    task = "请按以下步骤执行，每一步完成后汇报：\n1. 检查第一部分\n2. 检查第二部分\n3. 整理结果并结束任务。"
    native = directory / "child.jsonl"
    native.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in [
        {"type": "session", "id": "child-fixture", "cwd": str(directory)},
        {"type": "message", "id": "u", "message": {"role": "user", "content": [{"type": "text", "text": task}]}},
        {"type": "message", "id": "a", "parentId": "u", "message": {"role": "assistant", "content": [{"type": "text", "text": "已经收到，继续检查。"}]}}
    ]) + "\n", encoding="utf-8")
    tools = []
    for i in range(80):
        child = {"id": f"collection-{i}", "status": "running", "avatarSlot": i % 4,
                 "task": task, "activity": "检查文件\n准备结果", "outputFile": str(native)}
        backend.subagents.merge(record, child)
        tools.append({"id": "subagent:" + child["id"], "name": "subagent", "state": "running", "arguments": {}, "subagent": child})

    def render(count):
        record.messages = [{"role": "assistant", "text": "已安排子智能体。", "tools": tools[:count]}]
        backend.chatChanged.emit()
        QTest.qWait(200)

    render(4)
    assert sum(item.objectName().startswith("subagentCard_") and item.isVisible() for item in items()) == 4
    compact_summaries()
    render(80)
    assert find("subagentGroupCard").isVisible()
    assert not any(item.objectName().startswith("subagentCard_") and item.isVisible() for item in items())
    assert len({row["name"] for row in backend.subagents.agents}) == 80
    matrix = window.findChild(QObject, "subagentMatrix")
    anchor = find("subagentGroupCard")
    opening = []
    # Capture the seed before a render tick. QTest.mouseClick may process the
    # first PID frame before returning on some platform plugins.
    def capture_opening():
        opening.append(tuple(matrix.property(key) for key in ("x","y","width","height")))
    matrix.aboutToShow.connect(capture_opening)
    click("subagentGroupCard")
    assert opening, "Matrix did not announce its first opening"
    x,y,width,height=opening[0]
    assert abs(width-anchor.width())<2 and abs(height-anchor.height())<2, ("First frame started at the overlay size instead of the widget",opening[0])
    assert abs(x)<2 and abs(y)<2, ("First frame did not start at the widget origin",opening[0])
    matrix.aboutToShow.disconnect(capture_opening)
    wait(lambda: matrix.property("desiredOpen") and not matrix.property("animating"), "Matrix did not settle")
    grid = find("subagentMatrixGrid")
    assert grid.property("count") == 80
    assert grid.property("columns") >= 2
    assert grid.property("contentHeight") > grid.height()
    click("subagentGroupCard")
    wait(lambda: not matrix.property("visible"), "Second click did not close the matrix")
    click("subagentGroupCard")
    wait(lambda: matrix.property("desiredOpen") and not matrix.property("animating"), "Matrix did not reopen")
    assert sum(item.objectName().startswith("matrixSubagent_") for item in items()) < 60, "Matrix created every child eagerly"
    compact_summaries()
    screenshots = ROOT / "artifacts/screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    assert window.grabWindow().save(str(screenshots / "subagent-matrix.png"))
    grid.setProperty("contentY", grid.property("contentHeight") - grid.height())
    QTest.qWait(100)
    click("matrixSubagent_collection-79")
    wait(lambda: backend.subagents.selected.get("id") == "collection-79" and not backend.subagents.loading, "Matrix selected wrong child")
    wait(lambda: not matrix.property("visible") and not find("webPane").property("moving"), "Matrix did not close")

    # Every role uses its own receiver art, files and drafts. Drops never touch the parent.
    roles = ["lemon-yakishio", "chika-komari", "kaju-nukumizu", "yumeko-shikiya"]
    with patch.object(backend, "_command_pi", return_value=True) as command:
        for i, role in enumerate(roles):
            backend.subagents.open(f"collection-{i}")
            wait(lambda: not backend.subagents.loading, "Child history did not load")
            QTest.qWait(80)
            assert not backend.subagents.context["attachments"]
            pane = find("subagentPane")
            point = pane.mapToScene(QPointF(pane.width()/2, pane.height()/2)).toPoint()
            attachment = directory / f"drop-{i}.txt"
            attachment.write_text(f"child {i}", encoding="utf-8")
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(attachment))])
            app.sendEvent(window, QDragEnterEvent(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
            app.sendEvent(window, QDragMoveEvent(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
            assert find("subagentFileDropOverlay").isVisible()
            assert not find("chatFileDropOverlay").isVisible()
            mascot = find("subagentFileCatchMascot")
            assert str(mascot.property("source").toString()).endswith(role + "-catch.png")
            if i == 1:
                QTest.qWait(160)
                assert window.grabWindow().save(str(screenshots / "subagent-attachment-drop.png"))
            event = QDropEvent(QPointF(point), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
            app.sendEvent(window, event)
            QTest.qWait(150)
            assert event.isAccepted() and find("subagentPromptInput").hasActiveFocus()
            if app.platformName() == "windows":
                import ctypes
                ctypes.windll.user32.GetForegroundWindow.restype = ctypes.c_void_p
                foreground = ctypes.windll.user32.GetForegroundWindow()
                assert foreground == int(window.winId()), (foreground, int(window.winId()), window.isActive())
            assert not backend.attachments
            assert len(backend.subagents.context["attachments"]) == 1
            if i == 0:
                click("sendSubagentButton")
                payload = command.call_args.kwargs["command"]
                assert payload["id"] == "collection-0" and str(attachment.resolve()) in payload["text"]
                backend.subagents.handle(record, {"type": "subagent_command", "requestId": payload["requestId"], "ok": True})
                assert not backend.subagents.context["attachments"]

        for scale in (1., 2.):
            backend.setFontScale(scale)
            window.resize(1060 if scale == 2. else 1900, 1000)
            QTest.qWait(600)
            compact_summaries()
            if scale == 2.:
                assert window.grabWindow().save(str(screenshots / "subagent-large-font.png"))
        backend.setFontScale(1.)
        window.resize(1600, 1000)
        QTest.qWait(300)
        click("subagentIndicator")
        menu = window.findChild(QObject, "subagentActiveMenu")
        wait(lambda: menu.property("desiredOpen") and not menu.property("animating"), "Active list did not settle")
        active = find("activeSubagentList")
        assert active.property("count") == 80 and active.property("contentHeight") > active.height()
        assert sum(item.objectName().startswith("activeSubagent_collection-") for item in items()) < 35
        compact_summaries()
        active.setProperty("contentY", active.property("contentHeight") - active.height())
        QTest.qWait(100)
        click("activeSubagent_collection-79")
        wait(lambda: backend.subagents.selected.get("id") == "collection-79", "Active menu selected wrong child")
        wait(lambda: not menu.property("visible"), "Active list did not close")
        click("closeSubagentPaneButton")
        wait(lambda: not find("webPane").property("moving"), "Child pane did not close")
        backend.setFontScale(2.)
        window.resize(1060, 1000)
        QTest.qWait(350)
        click("subagentGroupCard")
        wait(lambda: matrix.property("desiredOpen") and not matrix.property("animating"), "Large-font matrix did not settle")
        assert find("subagentMatrixGrid").property("columns") == 1
        body = find("subagentMatrixGrid")
        assert body.mapToScene(QPointF(0, 0)).x() >= 0
        assert body.mapToScene(QPointF(body.width(), body.height())).x() <= window.width()
        compact_summaries()
        backend.newSession()
        wait(lambda: not matrix.property("visible"), "Session switch kept stale matrix open")
    assert not warnings, "\n".join(warnings)
    print("SUBAGENT_COLLECTION_UI_OK: 80 children, one collapsed group, bounded scrollable matrix/list, exact selection, multiline summaries, 200% font, four role drops, isolated attachments and input focus")
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
