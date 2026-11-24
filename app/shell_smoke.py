"""Drive the same desktop actions as the chat UI in a packaged offscreen smoke."""

import json
import os
from pathlib import Path

from PySide6.QtCore import QMetaObject, QObject, QTimer, QUrl
from PySide6.QtQml import QQmlEngine, QQmlExpression


def attach(app, controller, directory, window=None):
    directory = directory.resolve()
    profile = directory / "profile"
    workspace = directory / "workspace"
    if (app.platformName() != "offscreen" or
            Path(os.environ.get("UMEKO_DATA_DIR", "")).resolve() != profile or
            not (profile / "settings.json").is_file() or not workspace.is_dir()):
        app.exit(1)
        raise ValueError("Packaged shell smoke requires an isolated offscreen profile")

    request_path = directory / "request.json"
    response_path = directory / "response.json"
    workspace_url = QUrl.fromLocalFile(str(workspace)).toString()
    controller.setWorkspace(workspace_url)
    timer = QTimer(app)
    app._shell_smoke_timer = timer

    def receive():
        if not request_path.is_file():
            return
        request = json.loads(request_path.read_text(encoding="utf-8"))
        request_path.unlink()
        action = request["action"]
        accepted = True
        evidence = {}
        if action == "send":
            accepted = controller.send(request["text"])
        elif action == "stop":
            controller.stop()
        elif action == "new":
            controller.newSession()
            controller.setWorkspace(workspace_url)
        elif action == "agent_bus":
            service = controller.desktopPlugins.global_agents
            allowed = {"setAutomaticCreation", "snapshot", "send", "setModel"}
            method = request["method"]
            if method in allowed:
                try:
                    evidence = service.handle(method, request.get("arguments", {}))
                except ValueError as error:
                    accepted, evidence = False, {"error": str(error)}
            else:
                accepted = False
        elif action == "model_group":
            accepted = controller.selectModelGroup()
        elif action == "model_picker" and window:
            controller.setLanguage(request["language"])
            popup = window.findChild(QObject, "modelPopup")
            if popup and not popup.property("desiredOpen"):
                QMetaObject.invokeMethod(popup, "toggle")
            picker = window.findChild(QObject, "modelRolePicker")
            accepted = bool(picker and picker.setProperty("currentIndex", request.get("index", 1)))
            search = window.findChild(QObject, "modelSearch")
            if search:
                search.setProperty("text", "test-model")
            if picker:
                evidence["label"] = picker.property("currentText")
        elif action == "open_member_widget":
            popup = window.findChild(QObject, "modelPopup") if window else None
            if popup and popup.property("desiredOpen"):
                QMetaObject.invokeMethod(popup, "toggle")
            accepted = controller.desktopPlugins.openPage("global-agents")
        elif action == "member_picker" and window:
            controller.setLanguage(request["language"])
            page = window.findChild(QObject, "globalAgentsPage")
            if page:
                expression = QQmlExpression(QQmlEngine.contextForObject(page), page,
                                            "form(" + json.dumps(request.get("id", "")) + ")")
                expression.evaluate()
                accepted = not expression.hasError()
            else:
                accepted = False
        elif action == "capture" and window:
            name = request.get("name", "")
            if name not in {"model-picker-zh", "model-picker-en", "member-picker-zh", "member-picker-en"}:
                accepted = False
            else:
                accepted = window.grabWindow().save(str(directory / (name + ".png")))
        elif action not in {"status", "quit"}:
            accepted = False
        view = controller._view
        result = {"accepted": accepted, "busy": controller.busy, "phase": view.phase,
                  "session": view.id, "messages": view.messages, "evidence": evidence,
                  "piProcesses": [int(record.process.processId()) for record in controller._pool.records.values() if record.process]}
        temporary = response_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        temporary.replace(response_path)
        if action == "quit":
            app.quit()

    timer.timeout.connect(receive)
    timer.start(50)
    QTimer.singleShot(120_000, lambda: app.exit(2))
