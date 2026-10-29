"""Live tool state and each role's completed-reply interaction in the real pane."""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["UMEKO_DATA_DIR"] = tempfile.mkdtemp(prefix="umeko-child-reaction-")
os.environ["UMEKO_LANGUAGE"] = "zh"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
from PySide6.QtCore import QPointF, Qt
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


def click(item):
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, item.mapToScene(QPointF(item.width()/2, item.height()/2)).toPoint())


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
    screenshots = ROOT / "artifacts/screenshots"
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
        QTest.qWait(70)
        toggle = find("toggleTools_1_0")
        if not toggle.parentItem().parentItem().property("expanded"): click(toggle)
        QTest.qWait(30)
        status = find("toolState_slow")
        assert status.isVisible() and status.property("name") == "hourglass"
        running_color = status.property("color")
        snapshot[1]["tools"][0]["state"] = "error"
        backend.subagents.handle(record, {"type": "subagent_context", "id": child_id, "messages": snapshot})
        QTest.qWait(50)
        status = find("toolState_slow")
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
