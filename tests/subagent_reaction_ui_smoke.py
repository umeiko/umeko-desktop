"""Live tool state and each role's completed-reply interaction in the real pane."""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
test_base = Path("C:/UmekoTests") if os.name == "nt" else Path(tempfile.gettempdir())
test_base.mkdir(parents=True, exist_ok=True)
test_profile = tempfile.TemporaryDirectory(prefix="umeko-child-reaction-", dir=test_base)
os.environ["UMEKO_DATA_DIR"] = test_profile.name
os.environ["PI_CODING_AGENT_DIR"] = str(Path(test_profile.name) / "pi-agent")
os.environ["UMEKO_LANGUAGE"] = "zh"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
from PySide6.QtCore import QPointF, Qt, QMetaObject, Q_ARG, Q_RETURN_ARG
from PySide6.QtTest import QTest
from main import create_application

app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))


def find(name, root=None):
    stack = [root if root is not None else window.contentItem()]
    while stack:
        item = stack.pop()
        if item.objectName() == name: return item
        stack.extend(item.childItems())
    return None


def tool_item(name):
    pane = find("subagentConversation")
    if pane is None:
        return None
    # ListView keeps pooled delegates, and each child fixture repeats the same
    # tool IDs. Query the active assistant row rather than the first named item
    # anywhere in the view's retained item tree.
    message = QMetaObject.invokeMethod(pane, "itemAtIndex", Qt.DirectConnection,
        Q_RETURN_ARG("QQuickItem*"), Q_ARG(int, 1))
    return find(name, message) if message is not None else None


def item_state(item):
    if item is None: return None
    ancestors = []
    current = item
    while current is not None:
        point = current.mapToScene(QPointF(0, 0))
        ancestors.append({"object": current.objectName(), "type": current.metaObject().className(),
                          "visible": current.isVisible(), "enabled": current.isEnabled(),
                          "rect": [point.x(), point.y(), current.width(), current.height()],
                          "clip": current.property("clip"), "expanded": current.property("expanded")})
        current = current.parentItem()
    return {"name": item.property("name"), "ancestors": ancestors}


def clickable(item):
    if item is None or not item.isVisible() or not item.isEnabled() or item.width() <= 0 or item.height() <= 0:
        return False
    point = item.mapToScene(QPointF(item.width()/2, item.height()/2))
    if not (0 < point.x() < window.width() and 0 < point.y() < window.height()): return False
    ancestor = item.parentItem()
    while ancestor is not None:
        if ancestor.property("clip"):
            local = ancestor.mapFromScene(point)
            if not (0 <= local.x() < ancestor.width() and 0 <= local.y() < ancestor.height()): return False
        ancestor = ancestor.parentItem()
    return True


def wait(predicate, label):
    for _ in range(400):
        QTest.qWait(10)
        if predicate(): return
    diagnostic = {"child": backend.subagents.selected_id,
                  "header": item_state(tool_item("toggleTools_1_0")),
                  "status": item_state(tool_item("toolState_slow"))}
    raise AssertionError(label + "\n" + json.dumps(diagnostic, ensure_ascii=False) + "\n" + "\n".join(warnings))


def click(item):
    # Visibility can update before Positioners and the ListView have polished
    # their hit geometry. Complete a render before sending synthetic input.
    window.grabWindow()
    point = item.mapToScene(QPointF(item.width()/2, item.height()/2)).toPoint()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)


try:
    QTest.qWait(200)
    window.resize(1600, 1000)
    record = backend._view
    record.id = "role-reaction-fixture"
    directory = Path(os.environ["UMEKO_DATA_DIR"])
    file = directory / "completed.jsonl"
    file.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in [
        {"type": "session", "id": "completed", "cwd": str(directory)},
        {"type": "message", "id": "u", "message": {"role": "user", "content": [{"type": "text", "text": "检查任务。"}]}},
        {"type": "message", "id": "a", "parentId": "u", "message": {"role": "assistant", "content": [{"type": "text", "text": "任务已经完成，检查结果正常。"}]}}
    ]) + "\n", encoding="utf-8")
    roles = ["lemon-yakishio", "chika-komari", "kaju-nukumizu", "yumeko-shikiya"]
    seen = set()
    screenshots = directory / "screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    for i, role in enumerate(roles):
        child_id = f"role-{i}"
        backend.subagents.merge(record, {"id": child_id, "avatarSlot": i, "status": "completed", "outputFile": str(file)})
        backend.subagents.open(child_id)
        wait(lambda: not backend.subagents.loading and not find("webPane").property("moving"), "Child pane did not settle")
        wait(lambda: find("subagentReplyMascot_1") is not None, "Child reply delegate did not appear")
        mascot = find("subagentReplyMascot_1")
        wait(lambda: mascot.isVisible() and mascot.property("loaded"), "Completed child did not show its mascot")
        assert not find("subagentReplyMascot_0").isVisible()
        assert mascot.property("portraitSource").toString().endswith(role + ".png")
        click(mascot)
        lines = mascot.property("tapLines").toVariant()
        assert mascot.property("reaction") in lines
        assert mascot.property("animating")
        click(mascot)
        click(mascot)
        assert mascot.property("reaction") == mascot.property("celebrationLine")
        assert mascot.property("reaction") not in seen
        seen.add(mascot.property("reaction"))
        assert window.grabWindow().save(str(screenshots / f"reply-{role}.png"))
        backend.subagents.merge(record, {"id": child_id, "status": "running"})
        QTest.qWait(40)
        assert not mascot.isVisible() and mascot.property("reaction") == ""
        snapshot = [{"role": "user", "text": "检查任务。"}, {"role": "assistant", "text": "", "tools": [
            {"id": "slow", "name": "bash", "arguments": {"command": "sleep 60"}, "path": "", "state": "running", "result": ""}]}]
        backend.subagents.handle(record, {"type": "subagent_context", "id": child_id, "messages": snapshot})
        assert backend.subagents.messages[1]["tools"][0]["state"] == "running"
        wait(lambda: clickable(tool_item("toggleTools_1_0")), "Running tool header did not become clickable")
        toggle = tool_item("toggleTools_1_0")
        if not toggle.parentItem().parentItem().property("expanded"): click(toggle)
        wait(lambda: tool_item("toggleTools_1_0").parentItem().parentItem().property("expanded"), "Tool header click did not expand its rows")
        wait(lambda: tool_item("toolState_slow") is not None and tool_item("toolState_slow").isVisible()
             and tool_item("toolState_slow").property("name") == "hourglass", "Running tool did not show its hourglass")
        status = tool_item("toolState_slow")
        running_color = status.property("color")
        snapshot[1]["tools"][0]["state"] = "error"
        backend.subagents.handle(record, {"type": "subagent_context", "id": child_id, "messages": snapshot})
        wait(lambda: tool_item("toolState_slow") is not None and tool_item("toolState_slow").property("name") == "x", "Failed tool did not show its error marker")
        status = tool_item("toolState_slow")
        assert status.property("name") == "x" and status.property("color") != running_color
        assert not find("subagentReplyMascot_1").isVisible()
        backend.subagents.closeView()
    backend.subagents.merge(record, {"id": "role-1", "status": "completed"})
    backend.setFontScale(2.)
    window.resize(1060, 1000)
    backend.subagents.open("role-1")
    wait(lambda: not backend.subagents.loading and not find("webPane").property("moving"), "Large-font child did not settle")
    mascot = find("subagentReplyMascot_1")
    point = mascot.mapToScene(QPointF(mascot.width()/2, mascot.height()/2)).toPoint()
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.qWait(720)
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, point)
    assert mascot.property("reaction") == mascot.property("celebrationLine")
    bubble = next(item for item in mascot.childItems() if item.objectName() == "replyMascotBubble")
    assert bubble.mapToScene(QPointF(bubble.width(), 0)).x() <= window.width()
    QTest.keyClick(window, Qt.Key_Space)
    assert mascot.property("reaction") in mascot.property("tapLines").toVariant()
    backend.subagents.closeView()
    assert not warnings, "\n".join(warnings)
    print("SUBAGENT_REACTION_UI_OK: neutral running hourglass, genuine error marker, four role portraits and exclusive dialogue, combo/hold/keyboard interaction, hidden while running, 200% font bubble bounds")
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
    test_profile.cleanup()
