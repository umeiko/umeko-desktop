"""Native extension UI and factory recovery with isolated local fixtures."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["UMEKO_DATA_DIR"] = tempfile.mkdtemp(prefix="umeko-pi-management-ui-")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from app.storage import Store
from main import create_application

store = Store()
agent = store.directory / "fixture-agent"
project = store.directory / "fixture-project"
(agent / "extensions").mkdir(parents=True)
(project / ".pi/extensions").mkdir(parents=True)
executed = store.directory / "extension-executed.txt"
extension = agent / "extensions/example.ts"
extension.write_text("import {writeFileSync} from 'node:fs'; writeFileSync(" + json.dumps(str(executed)) + ", 'unexpected'); export default () => {};", encoding="utf-8")
(project / ".pi/extensions/project.ts").write_text("throw new Error('Recovery must not execute this extension');")
store.data["workspace"] = str(project)
store.data["agent"]["agentDir"] = str(agent)
store.data.update(providers=[{"id":"fixture", "name":"Fixture", "api":"openai", "baseUrl":"http://127.0.0.1:1/v1", "key":"fixture", "models":[{"upstream":"fixture", "alias":"fixture"}]}], selectedProvider="fixture", selectedModel="fixture")
store.save()
app, engine, backend = create_application()
window = engine.rootObjects()[0]
manager = backend.piManagement
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))


def find(name):
    stack = [window.contentItem()]
    while stack:
        item = stack.pop()
        if item.objectName() == name: return item
        stack.extend(item.childItems())
    return window.findChild(QQuickItem, name)


def wait_for(predicate):
    for _ in range(4500):
        QTest.qWait(10)
        time.sleep(0.01)  # Let the Python copy/backup worker run between Qt events.
        if predicate(): return
    raise AssertionError("Pi management did not finish: " + manager.status)


def click(name):
    target = find(name)
    assert target, name
    flick = find("settingsScroll").property("contentItem")
    ancestor = target.parentItem()
    while ancestor is not None and ancestor != flick: ancestor = ancestor.parentItem()
    if ancestor is not None:
        y = target.mapToItem(flick, QPointF(0, 0)).y() + flick.property("contentY") - flick.height() / 2
        flick.setProperty("contentY", max(0, min(y, flick.property("contentHeight") - flick.height())))
        QTest.qWait(100)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, target.mapToScene(target.boundingRect().center()).toPoint())
    QTest.qWait(100)


def capture(name):
    path = ROOT / "artifacts/screenshots" / (name + ".png")
    path.parent.mkdir(parents=True, exist_ok=True)
    assert window.grabWindow().save(str(path))


try:
    window.setProperty("page", "settings")
    window.setProperty("settingsTab", 3)
    assert find("settingsTab_4") is None, "Pi remains a top-level settings tab"
    assert find("openPiSettingsButton").isVisible()
    assert not find("checkKernelButton").isVisible()
    click("openPiSettingsButton")
    wait_for(lambda: not manager.busy and len(manager.extensions) >= 5)
    assert not executed.exists(), "scanning executed extension code"
    row = next(row for row in manager.extensions if row["path"] == str(extension))
    click("agentExtensionsToggle_" + row["id"])
    wait_for(lambda: not manager.busy)
    assert not next(row for row in manager.extensions if row["path"] == str(extension))["enabled"]
    click("agentExtensionsRefreshButton")
    wait_for(lambda: not manager.busy)
    row = next(row for row in manager.extensions if row["path"] == str(extension))
    assert not row["enabled"]
    click("agentExtensionsToggle_" + row["id"])
    wait_for(lambda: not manager.busy)
    assert next(row for row in manager.extensions if row["path"] == str(extension))["enabled"]
    with patch("app.pi_management.QDesktopServices.openUrl", return_value=True) as open_url:
        assert find("agentExtensionsCatalogButton").property("text") == "查看在线扩展"
        click("agentExtensionsCatalogButton")
        assert open_url.call_args.args[0].toString() == "https://pi.dev/packages"
    # Install via the real native CLI and actual QML dialog, never public npm.
    local_package = store.directory / "ui fixture package"
    (local_package / "extensions").mkdir(parents=True)
    installed_extension = local_package / "extensions/installed.ts"
    installed_extension.write_text("export default () => {};", encoding="utf-8")
    click("agentExtensionsInstallButton")
    assert window.findChild(QObject, "piExtensionInstaller").property("visible")
    find("piInstallCommand").setProperty("text", "pi install npm:a && whoami")
    click("confirmPiInstallButton")
    assert manager.installState == "failed" and not manager.busy
    capture("51-pi-extension-install-validation")
    find("piInstallCommand").setProperty("text", 'pi install "' + str(store.directory / "missing package") + '"')
    click("confirmPiInstallButton")
    wait_for(lambda: not manager.busy)
    assert manager.installState == "failed" and "Pi 安装失败" in manager.installMessage
    find("piInstallCommand").setProperty("text", 'pi install "' + str(local_package) + '" --local')
    assert find("piInstallScope").property("currentIndex") == 1
    assert not find("piInstallScope").isEnabled(), "command scope must agree with the scope selector"
    click("confirmPiInstallButton")
    wait_for(lambda: not manager.busy)
    assert manager.installState == "succeeded", manager.installMessage
    assert local_package.resolve() in {(project / ".pi" / path).resolve() for path in json.loads((project / ".pi/settings.json").read_text())["packages"]}
    assert any(row["path"] == str(installed_extension) and row["scope"] == "project" for row in manager.extensions)
    capture("52-pi-extension-installed")
    click("closePiInstallButton")
    capture("53-pi-agent-configuration")
    click("backToAgentButton")
    assert find("openPiSettingsButton").isVisible() and not find("checkKernelButton").isVisible()
    capture("50-agent-pi-overview")
    click("openPiSettingsButton")
    wait_for(lambda: not manager.busy)
    with patch("app.pi_management.launch_terminal") as launch:
        click("openPiTerminalButton")
        wait_for(lambda: not manager.busy)
        launch.assert_called_once()
        command = launch.call_args.args[0]
        assert "-NoExit" in command
        script = Path(command[-1]).read_text(encoding="utf-8-sig")
        assert "function global:pi" in script and "pi config" in script
        assert "pi-console" in script
    capture("47-pi-native-extension-manager")
    backend._view.phase = "running"
    click("factoryResetPiButton")
    click("confirmFactoryResetPiButton")
    assert not manager.busy and not backend.kernelBusy, "reset started during an active task"
    backend._view.phase = "idle"
    config = project / ".pi/settings.json"
    config.write_text("corrupt project configuration")
    click("factoryResetPiButton")
    assert window.findChild(QObject, "factoryResetPiDialog").property("visible")
    capture("48-pi-factory-reset-confirmation")
    click("confirmFactoryResetPiButton")
    wait_for(lambda: not manager.busy and not backend.kernelBusy)
    assert backend.config["agent"]["safeMode"], manager.status
    assert Path(manager.backupPath).is_dir()
    assert config.read_text() == "corrupt project configuration"
    assert extension.exists() and not executed.exists()
    assert backend.config["agent"]["agentDir"] != str(agent)
    assert find("openPiBackupButton").isVisible()
    backend.loadCapabilities()
    wait_for(lambda: not backend.busy)
    assert {"read", "bash", "edit", "write", "codemode", "tool_search"}.issubset(set(backend.agentResources["tools"])), backend.agentResources
    assert not executed.exists()
    capture("49-pi-factory-restored")
    # Verify a switch changes the next actual native session, not just its label.
    clean_project = store.directory / "clean-project"
    clean_project.mkdir()
    clean_info = backend._ensure_project(clean_project, reopen=True)
    backend.openProject(clean_info["id"])
    manager.setRecoveryMode(False)
    wait_for(lambda: not manager.busy)
    codemode = next(row for row in manager.extensions if row["path"] == "builtin:codemode")
    manager.setExtensionEnabled(codemode["id"], False)
    wait_for(lambda: not manager.busy)
    backend.loadCapabilities()
    wait_for(lambda: not backend.busy)
    assert "codemode" not in backend.agentResources["tools"], backend.agentResources
    assert {"read", "bash", "edit", "write"}.issubset(set(backend.agentResources["tools"]))
    codemode = next(row for row in manager.extensions if row["path"] == "builtin:codemode")
    manager.setExtensionEnabled(codemode["id"], True)
    wait_for(lambda: not manager.busy)
    backend.loadCapabilities()
    wait_for(lambda: not backend.busy)
    assert "codemode" in backend.agentResources["tools"], backend.agentResources
    assert not warnings, "\n".join(warnings)
    print("PI_MANAGEMENT_UI_OK: Agent/Pi navigation, in-app native install, scopes, validation, extension switches, catalog, console plan, task guard, factory recovery")
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
