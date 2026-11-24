"""Drive the same desktop actions as the chat UI in a packaged offscreen smoke."""

import json
import os
from pathlib import Path

from PySide6.QtCore import QObject, QTimer


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
    controller.setWorkspace(str(workspace))
    timer = QTimer(app)
    app._shell_smoke_timer = timer
    dsh_smoke = os.environ.get("UMEKO_DSH_SMOKE") == "1"

    def click(name):
        item = window.findChild(QObject, name)
        if item is None or not item.property("visible") or not item.property("enabled"):
            return False
        item.clicked.emit()
        return True

    def dsh_action(action, request):
        if action == "agent_settings":
            window.setProperty("settingsTab", 3)
            window.setProperty("page", "settings")
        elif action == "chat":
            window.setProperty("page", "chat")
        elif action == "backend":
            return controller.setSessionBackend(request["backend"])
        elif action == "open":
            controller.openSession(request["session"])
        elif action == "click":
            name = request["name"]
            return name in {"openDshSettingsButton", "checkDshRuntimeButton", "downloadDshRuntimeButton",
                            "allowToolButton", "denyToolButton"} and click(name)
        elif action == "snapshot":
            name = request["name"]
            return name in {"settings", "chat"} and window.grabWindow().save(str(directory / (name + ".png")))
        else:
            return False
        return True

    def receive():
        if not request_path.is_file():
            return
        request = json.loads(request_path.read_text(encoding="utf-8"))
        request_path.unlink()
        action = request["action"]
        accepted = True
        if action == "send":
            accepted = controller.send(request["text"])
        elif action == "stop":
            controller.stop()
        elif action == "new":
            controller.newSession()
            controller.setWorkspace(str(workspace))
        elif action not in {"status", "quit"}:
            accepted = dsh_smoke and dsh_action(action, request)
        view = controller._view
        result = {"accepted": accepted, "busy": controller.busy, "phase": view.phase,
                  "session": view.id, "messages": view.messages}
        if dsh_smoke:
            runtime = controller.dshRuntime
            result.update(backend=controller.sessionBackend, acpSession=getattr(view, "acp_session_id", ""),
                          approval=controller.pendingApproval, runtime={"busy": runtime.busy, "ready": runtime.ready,
                              "version": runtime.version, "status": runtime.status, "hint": runtime.hint})
        temporary = response_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        temporary.replace(response_path)
        if action == "quit":
            app.quit()

    timer.timeout.connect(receive)
    timer.start(50)
    QTimer.singleShot(720_000 if dsh_smoke else 120_000, lambda: app.exit(2))
