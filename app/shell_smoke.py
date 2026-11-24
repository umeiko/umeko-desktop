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
    dsh_smoke = os.environ.get("UMEKO_DSH_SMOKE") == "1"
    remote_settings_smoke = os.environ.get("UMEKO_REMOTE_SETTINGS_SMOKE") == "1"

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

    def remote_settings_action(action, request):
        if action == "remote_settings":
            window.setHeight(max(window.height(), 1050))
            window.setProperty("settingsTab", 3)
            window.setProperty("page", "settings")
        elif action == "open_remote_settings":
            return click("openUmekoDesktopSettingsButton")
        elif action == "remote_settings_snapshot":
            language = request.get("language")
            state = request.get("state")
            if language != controller.language or state not in {"connected", "reconnecting", "long-outage"}:
                return False
            settings = window.findChild(QObject, "umekoDesktopSettings")
            scroll = window.findChild(QObject, "settingsScroll")
            if not settings or not settings.property("visible") or not scroll:
                return False
            flickable = scroll.property("contentItem")
            flickable.setProperty("contentY", max(0, flickable.property("contentHeight") - flickable.height()))
            return window.grabWindow().save(str(directory / f"{language}-{state}.png"))
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
        evidence = {}
        extra = {}
        if action == "send":
            accepted = controller.send(request["text"])
        elif action == "stop":
            controller.stop()
        elif action == "new":
            controller.newSession()
            controller.setWorkspace(workspace_url)
        elif action in {"team_setup", "team_send", "team_state"}:
            try:
                extra = team_action(controller, action, request)
            except (OSError, ValueError) as error:
                accepted, extra = False, {"error": str(error)}
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
            accepted = (remote_settings_smoke and remote_settings_action(action, request)) or (dsh_smoke and dsh_action(action, request))
        view = controller._view
        result = {"accepted": accepted, "busy": controller.busy, "phase": view.phase,
                  "session": view.id, "messages": view.messages, "evidence": evidence,
                  "piProcesses": [int(record.process.processId()) for record in controller._pool.records.values() if record.process],
                  **extra}
        if dsh_smoke:
            runtime = controller.dshRuntime
            result.update(backend=controller.sessionBackend, acpSession=getattr(view, "acp_session_id", ""),
                          approval=controller.pendingApproval, runtime={"busy": runtime.busy, "ready": runtime.ready,
                              "version": runtime.version, "status": runtime.status, "hint": runtime.hint})
        if remote_settings_smoke:
            result["remoteEnvironments"] = controller.remoteEnvironments
        temporary = response_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        temporary.replace(response_path)
        if action == "quit":
            app.quit()

    timer.timeout.connect(receive)
    timer.start(50)
    timeout = 900_000 if remote_settings_smoke else 720_000 if dsh_smoke else 120_000
    QTimer.singleShot(timeout, lambda: app.exit(2))


def team_action(controller, action, request):
    plugins = controller.desktopPlugins
    bus = plugins.global_agents
    if action == "team_setup":
        if not plugins.openPage('global-agents') or bus.agents:
            raise ValueError('Team smoke requires a fresh global-agents Widget')
        return {'agents': {name: 'agent:' + bus.handle('create', {
            'name': name, 'instructions': f'Smoke member identity: {name}.'
        })['id'] for name in ('lead', 'api-dev', 'ui-dev', 'tester')}}
    if action == "team_send":
        if not plugins.openPage('global-agents'):
            raise ValueError('Could not open global-agents Widget')
        identifier = request['targetId'].removeprefix('agent:')
        conversation = plugins.selectConversation(identifier)
        if conversation is None:
            raise ValueError('Could not select global-agent conversation')
        sent = conversation.send(request['text'])
        return {'accepted': sent is not False}
    team_id = request.get('teamId', '')
    result = {'queued': len(bus.outbox), 'requests': list(bus.requests.values())}
    result['agents'] = {
        agent['name']: {'busy': bool(record and record.busy), 'pid': record.process.processId() if record and record.process else 0,
                        'sessionId': record.id if record else agent.get('sessionId', ''),
                        'sessionFile': record.file if record else agent.get('sessionFile', ''),
                        'chat': bus.messages(record.messages) if record else [],
                        'approval': bool(record and record.approval)}
        for identifier, agent in bus.agents.items() for record in (bus.records.get(identifier),)
    }
    if team_id:
        result['board'] = bus.handle('team_board', {'teamId': team_id, 'limit': 50})
        result['members'] = bus.handle('team_members', {'teamId': team_id})['members']
    return result
