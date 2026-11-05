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

from PySide6.QtCore import QObject, QUrl
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

    def control(name):
        item = window.findChild(QObject, name)
        assert item is not None, name
        return item

    def click(name):
        item = control(name)
        assert item.property("enabled"), name
        item.clicked.emit()

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
        click("taskRecordsButton")
        panel = control("taskRecordsPanel")
        until(lambda: panel.property("opened"), "Task panel did not open")
        click("newTaskRecord")
        control("taskObjective").setProperty("text", "Deliver the review report")
        control("taskScope").setProperty("text", "Read input.txt and submit report.txt in this project.")
        click("saveTaskRecord")
        task_id = backend.taskRecords.listTasks()[0]["id"]
        assert backend._view is view and view.draft == "Existing unsent draft"
        assert view.attachments == attachments and view.process is None and fixture.calls == 0

        click("prepareTaskAttempt")
        assert backend.taskRecords.selected == task_id and fixture.calls == 0
        assert view.draft == "Existing unsent draft"
        assert backend.send("Submit the report")
        until(lambda: backend.taskRecords.listTasks()[0]["state"] != "running", "Pi did not finish")
        assert backend.taskRecords.listTasks()[0]["state"] == "finished", warnings
        first = backend.taskRecords.listAttempts(task_id)[0]
        result = backend.taskRecords.store.details(task_id, first["id"])
        assert result["session_id"] == view.id and result["session_state"] == "available", result
        assert any(row["kind"] == "message" for row in result["steps"]), result
        assert [(row["source"], row["state"]) for row in result["files"]] == [
            ("input", "available"), ("submitted", "available")], result
        click("taskRecordsButton")
        until(lambda: control("verifyTaskArtifacts").property("enabled"), "Verification action did not load")
        click("verifyTaskArtifacts")
        until(lambda: control("acceptTaskAttempt").property("enabled"), "Acceptance action did not load")
        assert backend.taskRecords.store.details(task_id, first["id"])["files"][-1]["check_result"] == "available"
        click("acceptTaskAttempt")
        assert backend.taskRecords.listTasks()[0]["state"] == "accepted"
        panel.close()

        backend.newSession()
        assert backend._view is not view and backend.taskRecords.prepare(task_id)
        report.write_text("Revised fixture deliverable", encoding="utf-8")
        fixture.partial = True
        assert backend.send("Submit the revised report")
        until(lambda: backend.taskRecords.listTasks()[0]["state"] != "running", "Retry did not finish")
        attempts = backend.taskRecords.listAttempts(task_id)
        assert len(attempts) == 2 and attempts[0]["session_id"] != attempts[1]["session_id"], attempts
        assert attempts[1]["accepted"] and attempts[0]["state"] == "failed", attempts
        revised = backend.taskRecords.store.details(task_id, attempts[0]["id"])
        assert revised["files"][0]["state"] == "available" and any(
            step["kind"] == "delivery_error" for step in revised["steps"]), revised
        assert backend.taskRecords.store.details(task_id, first["id"])["files"][-1]["state"] == "changed"

        before = fixture.calls
        click("taskRecordsButton")
        until(lambda: not panel.property("loading"), "Results not rendered")
        control("taskAttemptSelector").activated.emit(1)
        until(lambda: not panel.property("loading"), "Earlier attempt not rendered")
        assert "report.txt" in control("taskAttemptDetails").property("text")
        assert fixture.calls == before
        assert not [line for line in warnings if "TaskRecords.qml" in line or "taskRecords" in line], warnings
        if len(sys.argv) > 1:
            QTest.qWait(300)
            assert window.grabWindow().save(sys.argv[1])
        print("TASK_RECORDS_UI_OK: isolated browsing, real Pi delivery, retry, partial failure, and changed artifact")
    finally:
        backend.close()
        window.hide()
        import shiboken6
        shiboken6.delete(engine)
