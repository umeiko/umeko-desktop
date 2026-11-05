"""Exercise the task panel and real Pi bridge in a disposable profile."""
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

from PySide6.QtCore import QObject, Qt, QUrl
from PySide6.QtTest import QTest
from app.integration import Completion
from main import create_application


class Fixture:
    ready = True

    def __init__(self):
        self.calls = 0
        self.partial = False

    def complete(self, model, messages, tools, max_tokens):
        self.calls += 1
        if messages[-1]["role"] == "tool":
            return Completion("Report submitted.")
        items = [{"path": "report.txt"}]
        if self.partial:
            items.append({"path": "missing.txt"})
        return Completion(tool_calls=[{
            "id": f"report-{self.calls}", "name": "submit_to_chatbox",
            "arguments": {"items": items},
        }])


def until(predicate, description):
    for _ in range(400):
        if predicate():
            return
        QTest.qWait(50)
    raise AssertionError(description)


with tempfile.TemporaryDirectory(prefix="umeko-task-records-ui-") as temp:
    profile = Path(temp)
    os.environ.update(HOME=temp, UMEKO_DATA_DIR=str(profile / "data"))
    fixture = Fixture()
    with patch("app.controller.load_adapter", return_value=fixture):
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
        return window.findChild(QObject, name)

    def control(name):
        item = find(name)
        assert item is not None, name
        return item

    def click(name):
        item = control(name)
        assert item.property("enabled"), name
        item.clicked.emit()

    manager = backend.desktopPlugins
    ledger = backend._task_records

    def open_widget():
        menu = control("desktopPluginSessionMenu")
        until(lambda: not menu.property("animating"), "Previous Widget menu animation did not settle")
        click("desktopPluginMenuButton")
        until(lambda: menu.property("desiredOpen") and not menu.property("animating"), "Widget menu did not open")
        until(lambda: find("openDesktopPlugin_task-records") is not None, "Task Widget menu entry missing")
        entry = control("openDesktopPlugin_task-records")
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, entry.mapToScene(entry.boundingRect().center()).toPoint())
        until(lambda: find("taskRecordsWidget") is not None, "Task Widget did not open")
        panel = control("taskRecordsWidget")
        until(lambda: manager.page.get("id") == "task-records" and not manager.page["loading"]
              and panel.property("loaded") and not panel.property("request"), "Task Widget did not load its records")
        return panel

    def select_task(panel, task_id):
        until(lambda: find("openTask_" + task_id) is not None, "Task row not rendered")
        click("openTask_" + task_id)
        until(lambda: panel.property("view") == "task" and not panel.property("request"), "Task details did not load")

    workspace = profile / "project"
    workspace.mkdir()
    report = workspace / "report.txt"
    report.write_text("Fixture deliverable", encoding="utf-8")
    input_file = workspace / "input.txt"
    input_file.write_text("Fixture input", encoding="utf-8")
    backend.store.data.update(selectedProvider="internal", selectedModel="umeko-default",
        providers=[{"id": "internal", "name": "Fixture", "api": "internal", "baseUrl": "", "key": "",
                    "models": [{"upstream": "default", "alias": "umeko-default"}]}])
    backend.setWorkspace(QUrl.fromLocalFile(str(workspace)).toString())
    assert backend.addAttachments(json.dumps([QUrl.fromLocalFile(str(input_file)).toString()]))
    view = backend._view
    view.draft = "Existing unsent draft"
    attachments = list(view.attachments)
    try:
        assert window.findChild(QObject, "taskRecordsButton") is None
        panel = open_widget()
        click("newTaskRecord")
        control("taskObjective").setProperty("text", "Deliver the review report")
        control("taskScope").setProperty("text", "Read input.txt and submit report.txt in this project.")
        click("saveTaskRecord")
        until(lambda: panel.property("view") == "task" and not panel.property("request"), "Task was not created")
        task_id = ledger.store.tasks()[0]["id"]
        assert backend._view is view and view.draft == "Existing unsent draft"
        assert view.attachments == attachments and view.process is None and fixture.calls == 0

        click("prepareTaskAttempt")
        until(lambda: not panel.property("request") and view.prepared_task == task_id, "Task was not linked")
        assert fixture.calls == 0 and view.draft == "Existing unsent draft"
        manager.closePage()
        assert backend.send("Submit the report")
        until(lambda: ledger.store.tasks()[0]["state"] != "running", "Pi did not finish")
        assert ledger.store.tasks()[0]["state"] == "finished", warnings
        first = ledger.store.attempts(task_id)[0]
        result = ledger.store.details(task_id, first["id"])
        assert result["session_id"] == view.id and result["session_state"] == "available", result
        assert any(row["kind"] == "message" for row in result["steps"]), result
        assert [(row["source"], row["state"]) for row in result["files"]] == [
            ("input", "available"), ("submitted", "available")], result
        panel = open_widget()
        select_task(panel, task_id)
        until(lambda: control("verifyTaskArtifacts").property("enabled"), "Verification action did not load")
        click("verifyTaskArtifacts")
        until(lambda: control("acceptTaskAttempt").property("enabled"), "Acceptance action did not load")
        assert ledger.store.details(task_id, first["id"])["files"][-1]["check_result"] == "available"
        click("acceptTaskAttempt")
        until(lambda: ledger.store.tasks()[0]["state"] == "accepted", "Acceptance was not stored")
        manager.closePage()

        backend.newSession()
        assert backend._view is not view
        panel = open_widget()
        select_task(panel, task_id)
        click("prepareTaskAttempt")
        until(lambda: not panel.property("request") and backend._view.prepared_task == task_id, "Retry was not linked")
        manager.closePage()
        report.write_text("Revised fixture deliverable", encoding="utf-8")
        fixture.partial = True
        assert backend.send("Submit the revised report")
        until(lambda: ledger.store.tasks()[0]["state"] != "running", "Retry did not finish")
        attempts = ledger.store.attempts(task_id)
        assert len(attempts) == 2 and attempts[0]["session_id"] != attempts[1]["session_id"], attempts
        assert attempts[1]["accepted"] and attempts[0]["state"] == "failed", attempts
        revised = ledger.store.details(task_id, attempts[0]["id"])
        assert revised["files"][0]["state"] == "available" and any(
            step["kind"] == "delivery_error" for step in revised["steps"]), revised
        assert ledger.store.details(task_id, first["id"])["files"][-1]["state"] == "changed"

        before = fixture.calls
        panel = open_widget()
        select_task(panel, task_id)
        control("taskAttemptSelector").activated.emit(1)
        until(lambda: not panel.property("request"), "Earlier attempt not rendered")
        assert "report.txt" in control("taskAttemptDetails").property("text")
        assert fixture.calls == before
        assert not [line for line in warnings if "task-records/qml" in line or "taskRecords" in line], warnings
        if len(sys.argv) > 1:
            QTest.qWait(300)
            assert window.grabWindow().save(sys.argv[1])
        print("TASK_RECORDS_UI_OK: isolated browsing, real Pi delivery, retry, partial failure, and changed artifact")
    except AssertionError:
        panel = find("taskRecordsWidget")
        if panel:
            print({key: panel.property(key) for key in ("view", "request", "loaded", "error")}, warnings, file=sys.stderr)
        raise
    finally:
        backend.close()
        window.hide()
        import shiboken6
        shiboken6.delete(engine)
