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
os.environ.setdefault('UMEKO_LANGUAGE','zh')
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
    # Pi extension UI is now exclusively a closeable Widget; recovery stays here.
    assert find("piFold_packages") is None
    capture("53-pi-agent-configuration")
    click("backToAgentButton")
    assert find("openPiSettingsButton").isVisible() and not find("checkKernelButton").isVisible()
    capture("50-agent-pi-overview")
    click("openPiSettingsButton")
    wait_for(lambda: not manager.busy)
    find("piFold_kernel").setProperty("expanded",False)
    find("piFold_management").setProperty("expanded",True)
    find("piFold_recovery").setProperty("expanded",True)
    with patch("app.pi_management.launch_terminal") as launch:
        click("openPiTerminalButton")
        wait_for(lambda: not manager.busy)
        launch.assert_called_once()
        command = launch.call_args.args[0]
        scripts=list((store.directory/"pi-console/launchers").iterdir())
        assert len(scripts)==1
        script=scripts[0].read_text(encoding="utf-8-sig")
        if os.name=="nt":
            assert "-NoExit" in command and "function global:pi" in script
        else:
            assert "pi()" in script
        assert "pi config" in script
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
    assert codemode["info"]["required"] and codemode["enabled"]
    manager.setExtensionEnabled(codemode["id"], False)
    wait_for(lambda: not manager.busy)
    assert next(row for row in manager.extensions if row["path"] == "builtin:codemode")["enabled"]
    assert "基础能力固定启用" in manager.status
    backend.loadCapabilities()
    wait_for(lambda: not backend.busy)
    assert {"read", "bash", "edit", "write", "codemode"}.issubset(set(backend.agentResources["tools"]))
    assert not warnings, "\n".join(warnings)
    print("PI_MANAGEMENT_UI_OK: Agent/Pi navigation, Widget-only extension placement, console plan, task guard, factory recovery")
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
