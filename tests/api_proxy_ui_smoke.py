"""Real QML administration: one-time credentials, table actions and shared drafts."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('UMEKO_LANGUAGE','zh')
os.environ["UMEKO_DATA_DIR"] = tempfile.mkdtemp(prefix="umeko-proxy-ui-")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
from PySide6.QtCore import QObject, QPointF, Qt, QMetaObject
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from app.storage import Store
from main import create_application

store = Store()
store.data["agent"]["agentDir"] = str(store.directory / "agent")
store.data["providers"] = [{"id":"fixture", "name":"Fixture", "api":"openai", "baseUrl":"http://127.0.0.1:18181/v1", "key":"synthetic", "models":[{"upstream":"fixture", "alias":"fixture"}]}]
store.data["providers"].append({"id":"other", "name":"Second supplier", "api":"openai", "baseUrl":"http://127.0.0.1:18182/v1", "key":"synthetic", "models":[{"upstream":"other-model", "alias":"other-model"}]})
store.save()
app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))


def item(name):
    stack = [window.contentItem()]
    while stack:
        current = stack.pop()
        if current.objectName() == name: return current
        stack.extend(current.childItems())
    return window.findChild(QQuickItem, name)


def reveal(target):
    flick = item("settingsScroll").property("contentItem")
    ancestor = target.parentItem()
    while ancestor is not None and ancestor != flick:
        ancestor = ancestor.parentItem()
    if ancestor is not None:
        position = target.mapToItem(flick, QPointF(0, 0))
        value = flick.property("contentY") + position.y() - flick.height() / 2
        flick.setProperty("contentY", max(0, min(value, flick.property("contentHeight") - flick.height())))
        QTest.qWait(100)


def click(name):
    target = item(name)
    assert target, name
    reveal(target)
    target = item(name)  # Key usage updates can recreate delegates during the reveal wait.
    assert target, name
    point = target.mapToScene(target.boundingRect().center()).toPoint()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.qWait(160)


def popup(name):
    return window.findChild(QObject, name)


def capture(name):
    QTest.qWait(120)
    path = ROOT / "artifacts/screenshots" / (name + ".png")
    path.parent.mkdir(parents=True, exist_ok=True)
    assert window.grabWindow().save(str(path))


try:
    window.resize(1440, 900)
    window.setProperty("page", "settings")
    window.setProperty("settingsTab", 1)
    QTest.qWait(200)
    assert item("settingsTab_2") is None, "standalone mapping tab remains"
    assert item("settingsTab_1").property("text") == "API 代理服务"
    assert item("proxyAddressPicker") is None, "Address configuration should be automatic"
    assert item("proxyOpenaiBaseUrl").property("text") == "http://127.0.0.1:8787/v1"
    assert item("mappingModelId_0") is None and item("mappingModelId_1") is None
    reveal(item("mappingProvider_fixture"))
    capture("proxy-provider-groups")
    # An unsaved service edit and model mapping edit survive key administration.
    item("portInput").setProperty("text", "18999")
    click("mappingProvider_fixture")
    mapping = item("mappingContext_0_input")
    mapping.setProperty("text", "256K")
    QMetaObject.invokeMethod(mapping, "textEdited")
    assert item("mappingModelId_0").isVisible() and item("mappingModelId_1") is None
    click("backToMappingProviders"); click("mappingProvider_other")
    assert item("mappingModelId_0") is None and item("mappingModelId_1").isVisible()
    alias = item("mappingAlias_1"); alias.setProperty("text", "second-alias"); QMetaObject.invokeMethod(alias, "textEdited")
    click("backToMappingProviders"); click("mappingProvider_fixture")
    mapping = item("mappingContext_0_input")
    assert mapping.property("text") == "256K", "Switching suppliers lost an unsaved mapping"
    capture("proxy-provider-aliases")
    keys = []
    for name in ("Laptop", "Local tools", "Build client"):
        click("addProxyKeyButton")
        assert popup("proxyKeyEditor").property("visible")
        item("proxyKeyNameInput").setProperty("text", name)
        click("saveProxyKeyButton")
        assert popup("createdProxyKeyDialog").property("visible"), "missing one-time key"
        key = item("createdProxyKeyValue").property("text")
        assert key.startswith("umeko-")
        key_id = backend.proxyKeys[-1]["id"]
        keys.append((key_id, key))
        if len(keys) == 1:
            capture("42-proxy-key-created")
            click("copyCreatedProxyKeyButton")
            assert app.clipboard().text() == key
        click("closeCreatedProxyKeyButton")
        assert item("createdProxyKeyValue").property("text") == ""
        assert item("proxyKeyValueInput").property("text") == ""
        assert item("proxyKeyDisplay_" + key_id).property("text").endswith(key[-4:])
        assert key not in json.dumps(backend.config)
    assert item("portInput").property("text") == "18999", "key edit overwrote service draft"
    assert mapping.property("text") == "256K", "key edit overwrote mapping draft"
    key_id, original = keys[0]
    click("editProxyKey_" + key_id)
    assert item("proxyKeyValueInput").property("text") == ""
    item("proxyKeyNameInput").setProperty("text", "Renamed laptop")
    click("saveProxyKeyButton")
    assert not popup("createdProxyKeyDialog").property("visible"), "rename exposed secret"
    assert backend._proxy_keys.authorized(original)
    click("editProxyKey_" + key_id)
    click("generateProxyKeyButton")
    fresh = item("proxyKeyValueInput").property("text")
    click("saveProxyKeyButton")
    assert item("createdProxyKeyValue").property("text") == fresh
    assert not backend._proxy_keys.authorized(original)
    assert backend._proxy_keys.authorized(fresh)
    click("closeCreatedProxyKeyButton")
    click("enableProxyKey_" + keys[1][0])
    assert not backend.proxyKeys[1]["enabled"]
    backend._sync_proxy_usage()
    QTest.qWait(100)
    assert item("proxyKeyLastUsed_" + key_id).property("text") == "刚刚"
    table = item("proxyKeysTable")
    reveal(table)
    capture("43-proxy-key-table")
    window.resize(1060, 740)
    QTest.qWait(100)
    reveal(table)
    assert table.width() <= 720
    assert table.property("contentWidth") >= 940
    capture("44-proxy-key-table-compact")
    window.resize(1440, 900)
    QTest.qWait(100)
    click("revokeProxyKey_" + keys[2][0])
    assert popup("revokeProxyKeyDialog").property("visible")
    click("confirmRevokeProxyKeyButton")
    assert len(backend.proxyKeys) == 2
    assert not backend._proxy_keys.authorized(keys[2][1])
    # Save changes through QML; LAN remains opt-in and model mappings are here.
    click("saveProxyServerButton")
    assert backend.config["server"]["port"] == 18999
    assert not backend.config["server"]["lan"]
    click("saveMappingsButton")
    assert backend.config["providers"][0]["models"][0]["contextWindow"] == 262144
    assert backend.config["providers"][1]["models"][0]["alias"] == "second-alias"
    with patch("app.controller.lan_addresses", return_value=["192.168.15.8"]):
        assert backend.saveServer(18999, True, True, True); QTest.qWait(100)
        assert item("proxyOpenaiBaseUrl").property("text") == "http://192.168.15.8:18999/v1"
        assert item("proxyAnthropicBaseUrl").property("text") == "http://192.168.15.8:18999"
        click("copyProxyOpenaiBaseUrl"); assert app.clipboard().text() == "http://192.168.15.8:18999/v1"
        capture("proxy-lan-base-url")
    with patch("app.controller.lan_addresses", return_value=[]):
        backend.refreshProxyAddresses(); QTest.qWait(100)
        assert item("proxyOpenaiBaseUrl").property("text") == ""
        assert not item("copyProxyOpenaiBaseUrl").isEnabled()
    assert backend.saveServer(18999, True, True, False); QTest.qWait(100)
    assert item("proxyOpenaiBaseUrl").property("text") == "http://127.0.0.1:18999/v1"
    window.setProperty("settingsTab", 0)
    QTest.qWait(100)
    assert item("manageInternalModelsButton") is None
    assert item("importCustomProviderButton") is not None
    assert not warnings, "\n".join(warnings)
    print("API_PROXY_UI_OK: table, one-time copy, rename, rotation, disable, revoke, compact layout, draft preservation")
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
