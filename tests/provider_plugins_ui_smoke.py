"""Exercise the real import/account/model UI with an offline SDK package."""
import json
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('UMEKO_LANGUAGE','zh')
os.environ["UMEKO_DATA_DIR"] = tempfile.mkdtemp(prefix="umeko-provider-ui-")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
from PySide6.QtCore import QObject, QMetaObject, Qt, QUrl, QMimeData, QPointF
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QEnterEvent
from PySide6.QtQuick import QQuickItem
from PySide6.QtQml import QQmlExpression
from PySide6.QtTest import QTest
from main import create_application
from umeko_provider_sdk.packages import pack_package

app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
out = ROOT / "artifacts/screenshots"
out.mkdir(parents=True, exist_ok=True)


def item(name):
    stack = [window.contentItem()]
    while stack:
        current = stack.pop()
        if current.objectName() == name: return current
        stack.extend(current.childItems())
    return window.findChild(QQuickItem, name)


def expose(name):
    target = item(name)
    assert target and target.isVisible(), name
    flick = item("settingsScroll").property("contentItem")
    parent = target.parentItem()
    while parent and parent != flick: parent = parent.parentItem()
    if parent:
        point = target.mapToItem(flick, target.boundingRect().center())
        flick.setProperty("contentY", max(0, min(flick.property("contentY") + point.y() - flick.height()/2, flick.property("contentHeight") - flick.height())))
        QTest.qWait(80)
    return target


def click(name):
    target = expose(name)
    point = target.mapToScene(target.boundingRect().center()).toPoint()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.qWait(120)


def hover_description(name, description):
    target = expose(name)
    point = target.mapToScene(target.boundingRect().center()).toPoint()
    app.sendEvent(window, QEnterEvent(QPointF(point), QPointF(point), QPointF(window.mapToGlobal(point))))
    QTest.mouseMove(window, point)
    QTest.qWait(600)
    assert target.property("pinned"), (name, point, target.property("hovered"))
    text = item("helpText_" + name)
    assert text.property("text") == description
    assert QQmlExpression(engine.rootContext(), text, "textFormat === 0").evaluate()[0]
    assert text.property("readOnly") and text.property("selectByMouse")
    assert window.grabWindow().save(str(out / ("provider-description-" + name.split("_")[0] + ".png")))
    QTest.mouseMove(window, window.contentItem().boundingRect().topLeft().toPoint())
    QTest.qWait(500)
    assert not target.property("pinned"), "Description remained open after leaving"


def drop_package(paths):
    area = item("providerPackageDropArea")
    point = area.mapToScene(area.boundingRect().center()).toPoint()
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    app.sendEvent(window, QDragEnterEvent(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
    app.sendEvent(window, QDragMoveEvent(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
    event = QDropEvent(QPointF(point), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    app.sendEvent(window, event)
    QTest.qWait(120)
    return event.isAccepted()


try:
    QTest.qWait(400)
    click("settingsButton")
    assert backend.config["providers"] == []
    assert not item("employeeInput")
    click("importCustomProviderButton")
    popup = window.findChild(QObject, "customProviderImportDialog")
    assert popup.property("opened")
    assert item("exportProviderSdkButton").isVisible()
    assert item("exportProviderSkillButton").isVisible()
    QTest.qWait(200)
    assert window.grabWindow().save(str(out / "70-provider-import.png"))
    archive = Path(os.environ["UMEKO_DATA_DIR"]) / "echo.zip"
    pack_package(ROOT / "provider_dev/examples/echo-provider", archive)
    wrong_file = archive.with_suffix(".txt")
    wrong_file.write_text("fixture", encoding="utf-8")
    assert not drop_package([wrong_file])
    assert not drop_package([archive, wrong_file])
    assert backend.providerPlugins.rows == []
    assert drop_package([archive]), "ZIP drag and drop was rejected"
    assert not popup.property("opened"), "Import popup remained open after a valid drop"
    QTest.qWait(200)
    provider_id = backend.providerPlugins.rows[0]["id"]
    plugin = backend.providerPlugins.packages[0]
    assert plugin["description"] == backend.providerPlugins.rows[0]["description"]
    hover_description("pluginDescription_" + plugin["id"] + "_" + plugin["version"], plugin["description"])
    hover_description("providerDescription_" + provider_id, plugin["description"])
    field = item("pluginAuth_" + provider_id + "_username")
    assert field
    field.setProperty("text", "Fixture User")
    click("loginPlugin_" + provider_id)
    deadline = time.monotonic() + 5
    while provider_id in backend.providerPlugins.busy and time.monotonic() < deadline: QTest.qWait(20)
    QTest.qWait(200)
    assert len(backend.providerPlugins.rows[0]["models"]) == 1
    settings = window.findChild(QObject, "settingsPage")
    assert settings.property("tab") == 0
    assert window.grabWindow().save(str(out / "71-provider-account.png"))
    click("managePluginModels_" + provider_id)
    models_popup = window.findChild(QObject, "pluginModelsDialog")
    assert models_popup.property("opened")
    # The manual API editor is also instantiated; select the visible dialog field.
    fields = []
    stack = [window.contentItem()]
    while stack:
        current = stack.pop()
        if current.objectName() == "providerModelAlias_0": fields.append(current)
        stack.extend(current.childItems())
    field = next(field for field in fields if isinstance(field, QQuickItem) and field.isVisible())
    field.setProperty("text", "offline-alias")
    QMetaObject.invokeMethod(field, "textEdited")
    click("savePluginModelsButton")
    assert backend.providerPlugins.rows[0]["models"][0]["alias"] == "offline-alias"
    assert settings.property("tab") == 0
    assert backend.gateway.complete("offline-alias", [{"role":"user","content":"hello"}]).text == "Echo: hello"
    for kind, expected in (("sdk", "umeko_provider_sdk/__init__.py"), ("skill", "develop-umeko-provider/SKILL.md")):
        destination = archive.with_name(kind + ".zip")
        assert backend.providerPlugins.exportResource(kind, QUrl.fromLocalFile(str(destination)).toString())
        with zipfile.ZipFile(destination) as stream: assert expected in stream.namelist()
    plugin = backend.providerPlugins.packages[0]
    click("removePluginAccount_" + provider_id)
    assert backend.providerPlugins.rows == []
    assert len(backend.providerPlugins.packages) == 1
    click("addPluginAccount_" + plugin["id"] + "_" + plugin["version"])
    assert len(backend.providerPlugins.rows) == 1
    click("uninstallPlugin_" + plugin["id"] + "_" + plugin["version"])
    assert window.findChild(QObject, "uninstallProviderDialog").property("opened")
    click("confirmUninstallProviderButton")
    assert backend.providerPlugins.packages == []
    assert backend.providerPlugins.rows == []
    # Change code but keep the version; explicit uninstall must release the identity.
    with zipfile.ZipFile(archive) as source: entries = {n: source.read(n) for n in source.namelist()}
    with zipfile.ZipFile(archive, "w") as output:
        for name, value in entries.items(): output.writestr(name, value + (b"\n# corrected fixture" if name.endswith(".py") else b""))
    click("importCustomProviderButton")
    assert drop_package([archive])
    assert len(backend.providerPlugins.packages) == 1
    bad = archive.with_name("bad-path.zip")
    with zipfile.ZipFile(bad, "w") as output: output.writestr("./scripts/../outside.py", "fixture")
    click("importCustomProviderButton")
    assert drop_package([bad])
    error_popup = window.findChild(QObject, "providerImportErrorDialog")
    assert error_popup.property("opened")
    error_text = item("providerImportErrorText")
    assert error_text.property("readOnly") and error_text.property("selectByMouse")
    assert "./scripts/../outside.py" in error_text.property("text")
    assert "PARENT_PATH" in error_text.property("text")
    click("closeProviderImportErrorButton")
    assert not warnings, "\n".join(warnings)
    print("Provider UI: ZIP drop, login/models/inference, exports, independent account deletion, plugin uninstall/reinstall and selectable path diagnostics passed")
finally:
    backend.close()
    window.close()
    import shiboken6
    shiboken6.delete(engine)
