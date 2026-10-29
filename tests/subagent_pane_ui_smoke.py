"""Native QML acceptance fixture; execution/steering use the Node integration test."""
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
os.environ.setdefault("UMEKO_LANGUAGE", "zh")
os.environ["UMEKO_DATA_DIR"] = tempfile.mkdtemp(prefix="umeko-subagent-pane-ui-")
from PySide6.QtCore import Qt, QPoint, QPointF, QObject
from PySide6.QtTest import QTest
from main import create_application

app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))

def find(name):
    pending = [window.contentItem()]
    while pending:
        item = pending.pop()
        if item.objectName() == name:
            return item
        pending.extend(item.childItems())
    raise AssertionError(name)

def wait(predicate, label):
    for _ in range(300):
        QTest.qWait(10)
        if predicate():
            return
    raise AssertionError(label + "\n" + "\n".join(warnings))

def click(name):
    item = find(name)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, item.mapToScene(item.boundingRect().center()).toPoint())

try:
    QTest.qWait(300)
    window.setWidth(1600)
    window.setHeight(1000)
    record = backend._view
    record.id, record.title = "preview-parent", "子代理侧栏 · 界面验收"
    tasks = ["检查项目结构，梳理关键入口", "审阅实现，寻找边界问题", "整理验证方案与测试结果", "检查文档与交付物"]
    tools = []
    for i, task in enumerate(tasks):
        file = Path(os.environ["UMEKO_DATA_DIR"]) / f"child-{i}.jsonl"
        entries = [
            {"type": "session", "id": f"fixture-{i}", "cwd": str(ROOT)},
            {"type": "message", "id": "u", "parentId": None, "message": {"role": "user", "content": [{"type": "text", "text": task}]}},
            {"type": "message", "id": "a", "parentId": "u", "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": "先确认项目入口和现有约束，再给出检查结果。"}, {"type": "text", "text": "我已经找到主要入口，正在核对各模块之间的连接。\n\n- 确认会话隔离\n- 检查侧栏的状态切换\n- 验证消息只发给对应的子代理"}]}}
        ]
        file.write_text("\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries) + "\n")
        child = {"id": f"preview-{i}", "status": "running", "type": "Explore", "avatarSlot": i, "task": task,
                 "activity": "正在检查相关文件", "toolUses": i + 2, "outputFile": str(file)}
        backend.subagents.merge(record, child)
        tools.append({"id": "subagent:" + child["id"], "name": "subagent", "state": "running", "arguments": {}, "result": "", "subagent": child})
    record.messages = [{"role": "user", "text": "请分工检查这次修改。"}, {"role": "assistant", "text": "我把这次检查分给四个子代理。你可以单独查看它们的上下文并发送指引。", "tools": tools}]
    backend.chatChanged.emit()
    wait(lambda: backend.messageCount == 2, "No parent transcript")
    QTest.qWait(300)
    click("subagentCard_preview-0")
    wait(lambda: not backend.subagents.context["loading"] and find("webPane").property("mode") == "subagent" and not find("webPane").property("moving"), "Child pane did not settle")
    assert backend.subagents.selected["id"] == "preview-0"
    assert backend.subagents.messageCount == 2
    assert find("subagentPromptInput").isVisible()
    assert find("subagentConversation").property("count") == 2
    assert backend.messageCount == 2
    with patch.object(backend, "_command_pi", return_value=True) as command:
        find("subagentPromptInput").setProperty("text", "只检查这一项，不要修改其他文件。")
        QTest.qWait(30)
        click("sendSubagentButton")
        wait(lambda: command.called, "Steering input did not submit")
        assert command.call_args.args[0] == "subagent-open"
        payload = command.call_args.kwargs["command"]
        assert payload["action"] == "send" and payload["id"] == "preview-0"
        backend.subagents.handle(record, {"type": "subagent_command", "id": "preview-0", "requestId": payload["requestId"], "ok": True})
        QTest.qWait(40)
        assert find("subagentPromptInput").property("text") == ""
    click("subagentIndicator")
    QTest.qWait(450)
    click("activeSubagent_preview-3")
    wait(lambda: backend.subagents.selected.get("id") == "preview-3" and not backend.subagents.context["loading"], "Active menu did not open the chosen child")
    wait(lambda: not window.findChild(QObject, "subagentActiveMenu").property("visible"), "Active menu did not finish closing")
    output = ROOT / "artifacts/screenshots"
    output.mkdir(parents=True, exist_ok=True)
    assert window.grabWindow().save(str(output / "subagent-pane.png"))
    handle = find("webPaneResizeHandle")
    before = find("webPane").width()
    start = handle.mapToScene(QPointF(handle.width()/2, 150)).toPoint()
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(window, start+QPoint(100,0)); QTest.qWait(80)
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, start+QPoint(100,0)); QTest.qWait(80)
    assert find("webPane").width() < before-70, {
        "before": before, "after": find("webPane").width(), "handleEnabled": handle.isEnabled(),
        "blocked": find("webPane").property("blocked"), "popupVisible": find("subagentIndicator").property("popupVisible")}
    window.setProperty("page", "settings")
    wait(lambda: not find("webPane").property("moving"), "Settings left the right pane open")
    assert not find("webPane").property("opened") and not backend.subagents.selected
    window.setProperty("page", "chat")
    backend.subagents.open("preview-1")
    wait(lambda: not backend.subagents.context["loading"] and not find("webPane").property("moving"), "Could not reopen child history")
    click("closeSubagentPaneButton")
    wait(lambda: not find("webPane").property("moving"), "Child close did not settle")
    assert not find("webPane").property("opened") and backend.subagents.activeCount == 4
    backend.subagents.open("preview-0")
    backend.newSession()
    assert not backend.subagents.selected and backend.subagents.activeCount == 0
    assert not warnings, "\n".join(warnings)
    print("SUBAGENT_PANE_UI_OK: four cards/avatars, independent context, targeted input, active dropdown, PID pane, resize, close, settings and session isolation")
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
