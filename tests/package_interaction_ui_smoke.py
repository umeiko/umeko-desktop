"""Real offscreen Composer/package-popup/settings interactions (no model calls).

Run with the project's PySide6 environment and prepared bundled Pi runtime:
    python tests/package_interaction_ui_smoke.py
Set UMEKO_UI_SCREENSHOTS to save the four review images. On Windows all test
profiles and temporary files remain under C:/UmekoTests/p373-ui.
Only empty/malformed resource responses are mocked; discovery,
workspace changes and local package install/remove use the real Controller,
PiManagement, worker jobs, bundled CLI and QML. Extension bodies must never run.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEST_ROOT = Path("C:/UmekoTests/p373-ui") if os.name == "nt" else Path(tempfile.gettempdir())
TEST_ROOT.mkdir(parents=True, exist_ok=True)
PROFILE = Path(tempfile.mkdtemp(prefix="package-interaction-", dir=TEST_ROOT))
tempfile.tempdir = str(PROFILE)
os.environ["UMEKO_DATA_DIR"] = str(PROFILE / "data")
os.environ["UMEKO_LANGUAGE"] = "zh"
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QUICK_BACKEND"] = "software"
os.environ["PI_OFFLINE"] = "1"
os.environ["PI_SKIP_VERSION_CHECK"] = "1"
HOME = PROFILE / "home"
HOME.mkdir()
os.environ["HOME"] = str(HOME)
os.environ["USERPROFILE"] = str(HOME)
os.environ["npm_config_userconfig"] = str(HOME / ".npmrc")
(HOME / ".npmrc").write_text("audit=false\nfund=false\n", encoding="utf-8")
SCREENSHOTS = Path(os.environ["UMEKO_UI_SCREENSHOTS"]) if os.environ.get("UMEKO_UI_SCREENSHOTS") else None
if SCREENSHOTS:
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)

# CREATE_NO_WINDOW covers Python's children. The preload also covers children
# spawned inside the actual native Pi CLI; no test launches a visible terminal.
PRELOAD = PROFILE / "hide-node-children.cjs"
PRELOAD.write_text("""
const cp = require('node:child_process');
for (const key of ['spawn', 'spawnSync', 'fork']) {
  const original = cp[key];
  cp[key] = function(file, args, options) {
    if (!Array.isArray(args)) { options = args; args = []; }
    return original.call(this, file, args, {...options, windowsHide: true});
  };
}
for (const key of ['exec', 'execSync']) {
  const original = cp[key];
  cp[key] = function(command, options, callback) {
    if (typeof options === 'function') { callback = options; options = {}; }
    return original.call(this, command, {...options, windowsHide: true}, callback);
  };
}
for (const key of ['execFile', 'execFileSync']) {
  const original = cp[key];
  cp[key] = function(file, args, options, callback) {
    if (!Array.isArray(args)) { callback = options; options = args; args = []; }
    if (typeof options === 'function') { callback = options; options = {}; }
    return original.call(this, file, args, {...options, windowsHide: true}, callback);
  };
}
require('node:module').syncBuiltinESMExports();
""", encoding="utf-8")
ORIGINAL_POPEN = subprocess.Popen


def hidden_popen(args, *positional, **kwargs):
    if isinstance(args, (list, tuple)):
        args = list(args)
        if Path(str(args[0])).stem.lower() == "node":
            args[1:1] = ["--require", str(PRELOAD)]
    if os.name == "nt":
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
        startup = kwargs.get("startupinfo") or subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = startup
    return ORIGINAL_POPEN(args, *positional, **kwargs)


process_patch = patch("subprocess.Popen", hidden_popen)
process_patch.start()
from PySide6.QtCore import QObject, QPoint, QPointF, Qt, QUrl
from PySide6.QtTest import QTest
from app.storage import Store
from main import create_application

seed = Store()
agent = PROFILE / "agent"
project = PROFILE / "project"
other_project = PROFILE / "other-project"
for directory in (agent, project / ".pi/extensions", other_project):
    directory.mkdir(parents=True, exist_ok=True)
seed.data["agent"]["agentDir"] = str(agent)
seed.data["workspace"] = str(project)
seed.save()
app, engine, backend = create_application()
window = engine.rootObjects()[0]
manager = backend.piManagement
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
scan_events = []
popup = window.findChild(QObject, "packagePopup")
assert popup is not None, "Real PackagePopup was not loaded"
backend.jobStarted.connect(lambda name: scan_events.append({"name": name,
    "animating": bool(popup.property("animating")), "desiredOpen": bool(popup.property("desiredOpen"))}))
observations = []


def find(name):
    stack = [window.contentItem()]
    while stack:
        item = stack.pop()
        if item.objectName() == name:
            return item
        stack.extend(item.childItems())
    raise AssertionError("Missing QML item: " + name)


def wait(predicate, label, timeout=15000):
    for _ in range(timeout // 10):
        QTest.qWait(10)
        time.sleep(.01)  # Yield the GIL to the real Python/native worker jobs.
        if predicate():
            return
    raise AssertionError(label + "\n" + manager.status + "\n" + "\n".join(warnings))


def settled():
    wait(lambda: not manager.busy, "Pi management worker did not finish", timeout=60000)


def scan():
    manager.scan()
    settled()


def click(name):
    item = find(name)
    assert item.isVisible() and item.isEnabled(), "Cannot click " + name
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier,
                     item.mapToScene(item.boundingRect().center()).toPoint())


def capture(name):
    if SCREENSHOTS:
        QTest.qWait(80)
        assert window.grabWindow().save(str(SCREENSHOTS / name)), name


def step(label):
    print("PACKAGE_INTERACTION_STEP: " + label, flush=True)


def button_visible(expected):
    wait(lambda: find("packageManagerButton").isVisible() == expected,
         "Composer package button visibility did not become " + str(expected))
    assert bool(manager.hasManageableExtensions) == expected


def open_popup(name="packagePopup", button="packageManagerButton"):
    target = window.findChild(QObject, name)
    click(button)
    wait(lambda: target.property("desiredOpen") and not target.property("animating"), name + " did not settle open")
    assert target.property("contentOpacity") > .98
    assert abs(target.property("width") - target.property("expandedWidth")) < 2
    assert abs(target.property("height") - target.property("expandedHeight")) < 2
    return target


def closed(target):
    wait(lambda: not target.property("visible"), "Popup did not finish closing")
    assert not target.property("desiredOpen") and not target.property("animating")


def check_popup_lifecycle(name, button):
    """Drive the same real anchor clicks/Escape/outside sequence for both popups."""
    target = window.findChild(QObject, name)
    click(button)
    wait(lambda: target.property("animating"), name + " had no opening motion")
    assert target.property("desiredOpen")
    click(button)
    QTest.qWait(20)
    assert not target.property("desiredOpen"), name + " did not reverse on its anchor"
    click(button)
    wait(lambda: target.property("desiredOpen") and not target.property("animating"), name + " rapid reversal failed")
    assert target.property("contentOpacity") > .98
    QTest.keyClick(window, Qt.Key_Escape)
    closed(target)
    assert find("promptInput").hasActiveFocus(), name + " Escape lost typing focus"
    open_popup(name, button)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(400, 90))
    closed(target)
    assert find("promptInput").hasActiveFocus(), name + " outside click lost typing focus"
    observations.append(name + ": rapid anchor reversal, Escape/outside dismissal, typing focus")


def assert_in_viewport(item, viewport, label, top_only=False):
    top = item.mapToScene(QPointF(0, 0))
    bottom = item.mapToScene(QPointF(item.width(), 1 if top_only else item.height()))
    view_top = viewport.mapToScene(QPointF(0, 0))
    view_bottom = viewport.mapToScene(QPointF(viewport.width(), viewport.height()))
    assert top.y() >= view_top.y() - 1 and bottom.y() <= view_bottom.y() + 1, (
        label, top.y(), bottom.y(), view_top.y(), view_bottom.y())
    assert top.x() >= view_top.x() - 1 and bottom.x() <= view_bottom.x() + 1, label


try:
    step("native startup and empty/builtin visibility")
    window.resize(1320, 900)
    # No providers configured: never submit a prompt or start a model session.
    wait(lambda: not manager.busy and len(manager.extensions) >= 1, "Startup did not scan current context", 60000)
    assert all(row.get("path", "").startswith("builtin:") for row in manager.extensions), manager.extensions
    assert manager.manageablePackages == []
    button_visible(False)
    observations.append("native startup scan: builtin-only Composer hides package button")

    # Both builtin markers are authoritative, and a package-shaped empty group
    # without a discovered package root must not create a management entry.
    empty_groups = [
        {"id": "builtin-path", "name": "Builtin path", "path": "builtin:fixture", "source": "local", "scope": "global", "enabled": True},
        {"id": "builtin-source", "name": "Builtin source", "path": str(PROFILE / "builtin-fixture.ts"), "source": "builtin", "scope": "global", "enabled": True},
        {"id": "empty-group", "name": "Empty group", "path": "", "source": "npm:missing-fixture", "scope": "global", "enabled": True, "origin": "package", "resourceKind": "package"},
    ]
    with patch("app.pi_management.resource_command", return_value=empty_groups):
        scan()
    assert manager.manageablePackages == [], manager.manageablePackages
    button_visible(False)

    # Native discovery always returns builtins, so a bounded resource response
    # supplies the genuine empty-list branch without faking Controller or QML.
    with patch("app.pi_management.resource_command", return_value=[]):
        scan()
    assert manager.extensions == [] and manager.manageablePackages == []
    button_visible(False)
    capture("composer-empty-zh.png")

    step("local extension and disabled visibility")
    extension = project / ".pi/extensions/local-fixture.ts"
    executed = PROFILE / "extension-executed.txt"
    extension.write_text("import {writeFileSync} from 'node:fs'; writeFileSync(" + json.dumps(str(executed)) +
                         ", 'unexpected'); export default () => {};", encoding="utf-8")
    scan()
    button_visible(True)
    row = next(row for row in manager.extensions if row["path"] == str(extension))
    assert len(manager.manageablePackages) == 1
    manager.setExtensionEnabled(row["id"], False)
    settled()
    assert not next(row for row in manager.extensions if row["path"] == str(extension))["enabled"]
    button_visible(True)  # Disabled extensions must remain available to reenable.
    backend.setLanguage("en")
    QTest.qWait(100)
    assert backend.language == "en"
    capture("composer-extensions-en.png")
    observations.append("real project extension: visible and remains manageable while disabled")

    step("workspace switch visibility")
    backend.setWorkspace(QUrl.fromLocalFile(str(other_project)).toString())
    wait(lambda: not manager.busy and not manager.hasManageableExtensions, "Workspace switch did not clear old extension visibility", 60000)
    button_visible(False)
    assert not any(row.get("path") == str(extension) for row in manager.extensions)
    backend.setWorkspace(QUrl.fromLocalFile(str(project)).toString())
    wait(lambda: not manager.busy and manager.hasManageableExtensions, "Returning to project did not refresh visibility", 60000)
    button_visible(True)
    extension.unlink()
    scan()
    button_visible(False)
    observations.append("real workspace switch: empty project hides, original project restores button")

    step("native local skills-only package install")
    package = PROFILE / "skills-only-package"
    (package / "skills/demo").mkdir(parents=True)
    (package / "skills/demo/SKILL.md").write_text("---\nname: fixture-skill\ndescription: Isolated UI fixture\n---\nNo execution.\n", encoding="utf-8")
    (package / "package.json").write_text(json.dumps({"name": "@fixture/skills-only", "version": "1.0.0",
        "keywords": ["pi-package"], "pi": {"skills": ["skills"]}}), encoding="utf-8")
    manager.installExtension('pi install "' + str(package) + '" --local', True)
    settled()
    assert manager.installState == "succeeded", manager.installMessage
    button_visible(True)
    package_row = next(row for row in manager.manageablePackages if row.get("resourceKind") == "package")
    assert package_row["extensions"] == [], package_row
    assert package_row["name"] == "@fixture/skills-only"
    observations.append("actual local install: package with skills and no extension rows makes Composer manageable")

    # Record the worker-start signal in the GUI thread. The first popup refresh
    # and its Loader must wait for PID geometry to finish before doing work.
    step("first popup motion defers list and scan")
    settled()
    scan_events.clear()
    assert not popup.property("listReady")
    click("packageManagerButton")
    wait(lambda: popup.property("animating"), "Package popup never animated")
    assert not popup.property("listReady"), "Package list instantiated during opening motion"
    assert not [event for event in scan_events if event["name"] == "pi-admin:scan"], scan_events
    wait(lambda: popup.property("desiredOpen") and not popup.property("animating") and popup.property("listReady"), "Package popup did not load after settling")
    settled()
    assert any(event["name"] == "pi-admin:scan" for event in scan_events), scan_events
    assert not any(event["animating"] for event in scan_events if event["name"] == "pi-admin:scan"), scan_events
    assert popup.property("contentOpacity") > .98
    backend.setLanguage("zh")
    capture("package-popup-zh.png")
    QTest.keyClick(window, Qt.Key_Escape)
    closed(popup)
    step("package popup rapid reversal and dismissals")
    check_popup_lifecycle("packagePopup", "packageManagerButton")
    step("model popup matching lifecycle")
    check_popup_lifecycle("modelPopup", "modelSelector")
    settled()
    assert not any(event["animating"] for event in scan_events if event["name"] == "pi-admin:scan"), scan_events

    # Start from closed parent folds, a stale search, and the alternate tools
    # view. Only the real popup Configure action may perform the settings jump.
    step("actual configure click expands and scrolls settings")
    agent_page = find("agentPage")
    agent_page.setProperty("piOpen", True)
    agent_page.setProperty("toolsOpen", True)
    find("piSettingsSearch").setProperty("text", "unmatched-fixture-query")
    find("piFold_extensions").setProperty("expanded", False)
    find("piFold_packages").setProperty("expanded", False)
    backend.setLanguage("en")
    open_popup()
    settled()
    click("packagePopupConfigureButton")
    wait(lambda: window.property("page") == "settings" and window.property("settingsTab") == 3,
         "Configure did not navigate to Agent settings")
    wait(lambda: agent_page.property("piOpen") and not agent_page.property("toolsOpen") and
         find("piFold_extensions").property("opened") and find("piFold_packages").property("opened"),
         "Configure did not expand the complete extension management path")
    assert find("piSettingsSearch").property("text") == ""
    settled()
    QTest.qWait(150)
    viewport = find("settingsScroll").property("contentItem")
    assert find("agentExtensionsManager").isVisible()
    assert_in_viewport(find("agentExtensionsManager"), viewport, "Extension manager header", top_only=True)
    assert_in_viewport(find("agentExtensionsInstallButton"), viewport, "Install action")
    assert_in_viewport(find("agentExtensionsRefreshButton"), viewport, "Refresh action")
    capture("settings-extensions-en.png")
    observations.append("real Configure click: Agent/Pi/folds/search reset and management header/actions inside viewport")

    # The removal consumes the real installed native row and scans its result.
    step("native local package uninstall")
    manager.uninstallPackage(package_row["id"])
    settled()
    assert not any(row.get("source") == package_row["source"] for row in manager.manageablePackages)
    window.setProperty("page", "chat")
    button_visible(False)
    assert not executed.exists(), "Discovery executed extension code"
    assert not warnings, "\n".join(warnings)
    observations.append("actual local uninstall: Composer immediately hides when only builtins remain")
    print("PACKAGE_INTERACTION_UI_OK: " + "; ".join(observations))
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
    process_patch.stop()
    shutil.rmtree(PROFILE)
