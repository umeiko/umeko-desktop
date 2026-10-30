"""Child input uses the parent's queue widgets and shortcuts without cross-routing."""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["UMEKO_DATA_DIR"] = tempfile.mkdtemp(prefix="umeko-child-queue-ui-")
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


def click(name):
    item = find(name)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, item.mapToScene(item.boundingRect().center()).toPoint())


try:
    QTest.qWait(200)
    window.resize(1600, 1000)
    record = backend._view
    record.id = "child-queue-ui"
    record.messages = [{"role": "user", "text": "Parent task"}, {"role": "assistant", "text": "Delegated"}]
    backend.chatChanged.emit()
    for identifier in ("a", "b"): backend.subagents.merge(record, {"id": identifier, "status": "running", "task": "Child task"})
    with patch.object(backend, "_command_pi", return_value=True) as command, patch.object(backend, "steer") as parent_steer:
        def open_child(identifier):
            backend.subagents.open(identifier)
            backend.subagents.handle(record, {"type": "subagent_context", "id": identifier, "messages": [{"role": "user", "text": "Child task"}, {"role": "assistant", "text": "Working"}]})
            wait(lambda: find("subagentPromptInput") is not None and not find("webPane").property("moving"), "Child input did not appear")
            QTest.qWait(60)

        def acknowledge(payload):
            backend.subagents.handle(record, {"type": "subagent_command", "requestId": payload["requestId"], "ok": True})
            QTest.qWait(35)

        open_child("a")
        prompt = find("subagentPromptInput")
        prompt.setProperty("text", "after the current task")
        prompt.forceActiveFocus()
        QTest.keyClick(window, Qt.Key_Return)
        payload = command.call_args.kwargs["command"]
        assert (payload["id"], payload["mode"]) == ("a", "followUp")
        acknowledge(payload)
        assert prompt.property("text") == ""
        queued = {"id": payload["messageId"], "text": payload["text"], "mode": "followUp"}
        backend.subagents.handle(record, {"type": "subagent_queue", "id": "a", "items": [queued]})
        QTest.qWait(60)
        band, composer = find("subagentQueuedMessages"), find("subagentComposer")
        assert band.isVisible() and abs(band.y()+band.height()-composer.y()) < 1
        assert not backend.queuedMessages
        prompt.setProperty("text", "priority now"); prompt.forceActiveFocus()
        QTest.keyClick(window, Qt.Key_S, Qt.ControlModifier)
        payload = command.call_args.kwargs["command"]
        assert (payload["id"], payload["mode"]) == ("a", "interrupt")
        assert not parent_steer.called, "Child shortcut steered the parent"
        acknowledge(payload)
        QTest.keyClick(window, Qt.Key_S, Qt.ControlModifier)
        assert command.call_args.kwargs["command"]["action"] == "promote-queue"
        click("subagent_steerQueued_0")
        assert command.call_args.kwargs["command"]["queueId"] == queued["id"]
        assert command.call_args.kwargs["command"]["action"] == "steer-queued"
        click("subagent_removeQueued_0")
        assert command.call_args.kwargs["command"]["action"] == "delete-queue"
        click("subagent_editQueued_0")
        assert command.call_args.kwargs["command"]["action"] == "edit-queue"
        backend.subagents.handle(record, {"type": "subagent_queue", "id": "a", "items": []})
        backend.subagents.handle(record, {"type": "subagent_queue_edited", "id": "a", "item": queued})
        QTest.qWait(60)
        assert prompt.property("text") == "after the current task" and prompt.hasActiveFocus()
        prompt.setProperty("text", "line")
        before = command.call_count
        QTest.keyClick(window, Qt.Key_Return, Qt.AltModifier)
        QTest.keyClick(window, Qt.Key_Return, Qt.ShiftModifier)
        assert prompt.property("text").count("\n") == 2 and command.call_count == before
        backend.subagents.handle(record, {"type": "subagent_queue", "id": "a", "items": [queued]})
        open_child("b")
        assert not find("subagentQueuedMessages").isVisible() and not backend.subagents.queuedMessages
        open_child("a")
        assert backend.subagents.queuedMessages[0]["id"] == queued["id"]
        many = [{"id": str(i), "text": "Long queued instruction\n"*5, "mode": "followUp"} for i in range(30)]
        backend.subagents.handle(record, {"type": "subagent_queue", "id": "a", "items": many})
        backend.setFontScale(2.)
        window.resize(1060, 900)
        QTest.qWait(500)
        band = find("subagentQueuedMessages")
        assert band.height() > 0 and band.height() <= band.property("heightLimit")
        assert find("subagentConversation").height() >= 120
        screenshots = ROOT / "artifacts/screenshots"
        screenshots.mkdir(parents=True, exist_ok=True)
        assert window.grabWindow().save(str(screenshots / "subagent-input-queue.png"))
        assert backend.messageCount == 2 and not backend.queuedMessages
        assert not warnings, "\n".join(warnings)
        print("SUBAGENT_QUEUE_UI_OK: Enter queues, Ctrl+S interrupts/promotes only the child, shared queue widget above input, edit/delete/steer, multiline input, per-child isolation and bounded large-font layout")
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
