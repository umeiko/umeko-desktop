"""Settings navigation and real native/MCP/extension provenance, with local fixtures."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('UMEKO_LANGUAGE','zh')
os.environ["UMEKO_DATA_DIR"] = tempfile.mkdtemp(prefix="umeko-tool-catalog-")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
from PySide6.QtCore import QObject, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from app.storage import Store
from app.pi_runtime import node_executable
from main import create_application

store = Store()
agent = store.directory / "agent"
project = store.directory / "project"
(agent / "extensions").mkdir(parents=True)
(agent / "skills/catalog-fixture").mkdir(parents=True)
(agent / "prompts").mkdir()
project.mkdir()
(agent / "extensions/catalog.js").write_text('''export default pi => {
  pi.registerTool({name:"catalog_fixture",label:"Catalog fixture",description:"Local extension fixture",
    parameters:{type:"object",properties:{}}, exposure:"deferred",
    execute:async()=>({content:[{type:"text",text:"fixture"}]})});
  pi.registerCommand("catalog-fixture", {description:"Local command fixture",handler:async()=>{}});
};''', encoding="utf-8")
(agent / "skills/catalog-fixture/SKILL.md").write_text("---\nname: catalog-fixture\ndescription: Local skill fixture\n---\nFixture only.", encoding="utf-8")
(agent / "prompts/catalog-fixture.md").write_text("---\ndescription: Local template fixture\n---\nFixture only.", encoding="utf-8")
server = store.directory / "mcp-fixture.mjs"
server.write_text('''import {createInterface} from "node:readline";
createInterface({input:process.stdin}).on("line", line => {
  const r = JSON.parse(line); if (r.id === undefined) return;
  let result = {};
  if (r.method === "initialize") result = {protocolVersion:r.params.protocolVersion,capabilities:{tools:{}},serverInfo:{name:"catalog",version:"1"}};
  if (r.method === "tools/list") result = {tools:[{name:"lookup",description:"Local MCP fixture",inputSchema:{type:"object",properties:{query:{type:"string"}}}}]};
  process.stdout.write(JSON.stringify({jsonrpc:"2.0",id:r.id,result})+"\\n");
});''', encoding="utf-8")
mcp_path = agent / "mcp.json"
mcp_path.write_text(json.dumps({"mcpServers": {"catalog-fixture": {"command": node_executable(), "args": [str(server)], "exposure": "deferred"}}}), encoding="utf-8")
saved_mcp = mcp_path.read_bytes()
store.data["workspace"] = str(project)
store.data["agent"]["agentDir"] = str(agent)
store.data.update(providers=[{"id":"fixture", "name":"Fixture", "api":"openai", "baseUrl":"http://127.0.0.1:9/v1", "key":"fixture", "models":[{"upstream":"fixture", "alias":"fixture"}]}], selectedProvider="fixture", selectedModel="fixture")
store.save()
app, engine, backend = create_application()
window = engine.rootObjects()[0]
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
    for _ in range(1800):
        QTest.qWait(10)
        time.sleep(0.01)
        if predicate(): return
    raise AssertionError(("Timed out", backend.piManagement.status, backend.agentResources))


def click(name):
    QTest.qWait(80)  # Let async registry updates settle their row geometry first.
    item = find(name)
    assert item and item.isVisible() and item.isEnabled(), name
    flick = find("settingsScroll").property("contentItem")
    ancestor = item.parentItem()
    while ancestor is not None and ancestor != flick: ancestor = ancestor.parentItem()
    if ancestor is not None:
        y = item.mapToItem(flick, QPointF(0, 0)).y()
        if y < 0 or y + item.height() > flick.height():
            target = flick.property("contentY") + y - flick.height() / 2
            flick.setProperty("contentY", max(0, min(target, flick.property("contentHeight") - flick.height())))
    QTest.qWait(30)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, item.mapToScene(item.boundingRect().center()).toPoint())
    QTest.qWait(30)


def count():
    return find("toolCatalogList").property("count")


def capture(name):
    QTest.qWait(100)
    out = ROOT / "artifacts/screenshots"
    out.mkdir(parents=True, exist_ok=True)
    assert window.grabWindow().save(str(out / (name + ".png")))


try:
    window.setProperty("page", "settings")
    window.setProperty("settingsTab", 3)
    QTest.qWait(100)
    click("openPiSettingsButton")
    wait_for(lambda: not backend.piManagement.busy and bool(backend.piManagement.extensions))
    for name in ("piFold_kernel",): find(name).setProperty("expanded", False)
    for name in ("piFold_extensions", "piFold_mcp", "piFold_tools"): find(name).setProperty("expanded", True)
    QTest.qWait(100)
    wait_for(lambda: not backend.piManagement.busy and not backend.busy)
    assert find("showPiCapabilitiesButton") is None
    assert window.findChild(QObject, "piCapabilities") is None
    card = find("mcpSettingsCard")
    assert card.property("mcpEnabled") and find("configureMcpButton").isEnabled()
    click("configureMcpButton")
    assert card.property("expanded"), "MCP card did not expand"
    wait_for(lambda: not backend.busy and bool(backend.agentResources.get("mcp")))
    editor = find("mcpJsonEditor")
    draft = '{"mcpServers":{},"draft":"unsaved local fixture"}'
    editor.setProperty("text", draft)
    mcp = next(row for row in backend.piManagement.extensions if row["path"] == "builtin:mcp")
    backend.piManagement.setExtensionEnabled(mcp["id"], False)
    wait_for(lambda: not backend.piManagement.busy)
    assert not card.property("mcpEnabled")
    for name in ("configureMcpButton", "mcpSaveButton", "mcpJsonEditor", "mcpGlobalTab", "mcpProjectTab"):
        assert not find(name).isEnabled(), name
    assert "builtin:mcp" in find("mcpDisabledReason").property("text")
    assert editor.property("text") == draft and mcp_path.read_bytes() == saved_mcp
    capture("61-mcp-disabled")
    click("openToolCatalogButton")
    wait_for(lambda: not backend.busy and bool(backend.agentResources.get("allTools")))
    click("toolCategory_mcp")
    assert count() == 0, backend.agentResources
    click("backToPiButton")
    wait_for(lambda: not backend.piManagement.busy)
    backend.piManagement.setExtensionEnabled(mcp["id"], True)
    wait_for(lambda: not backend.piManagement.busy)
    assert card.property("mcpEnabled") and editor.isEnabled()
    assert editor.property("text") == draft and mcp_path.read_bytes() == saved_mcp
    click("openToolCatalogButton")
    wait_for(lambda: not backend.busy and any(t["name"].startswith("mcp__catalog_fixture__") for t in backend.agentResources.get("allTools", [])))
    page = find("toolCatalogPage")
    assert find("toolCategory_native").width() <= 160
    click("toolCategory_native")
    assert count() == 8, backend.agentResources
    tool_list = find("toolCatalogList")
    assert tool_list.width() > 300 and tool_list.height() > 100, "Registry count exists but the list viewport is empty"
    read = find("toolEntry_read")
    position = read.mapToItem(tool_list, QPointF(read.width()/2, read.height()/2))
    assert read.isVisible() and read.width() > 100 and read.height() > 20 and 0 <= position.y() <= tool_list.height(), "The read row is outside the visible viewport"
    click("toolEntry_read")
    assert page.property("expandedName") == "read"
    capture("62-native-tool-details")
    click("toolCategory_mcp")
    assert count() == 1
    tool = next(t for t in backend.agentResources["allTools"] if t["name"].startswith("mcp__catalog_fixture__"))
    assert tool["source"] == "builtin:mcp" and tool["exposure"] == "deferred" and not tool["active"]
    click("toolEntry_" + tool["name"])
    capture("63-mcp-tools")
    click("toolCategory_extensions")
    assert count() >= 3
    assert {"codemode", "tool_search", "catalog_fixture"}.issubset({row['name'] for row in backend.agentResources['allTools']})
    find("toolCatalogSearch").setProperty("text", "local extension")
    QTest.qWait(30)
    assert count() == 1
    click("toolEntry_catalog_fixture")
    capture("64-extension-tool-search")
    find("toolCatalogSearch").setProperty("text", "no-such-fixture")
    QTest.qWait(30)
    assert count() == 0
    for section in ("skills", "prompts", "commands"):
        click("toolCategory_" + section)
        assert not find("toolCatalogSearch").property("text")
        assert count() >= 1, section
    backend._pool.retire(backend._view)  # Keep later synthetic list fixtures stable during polling.
    # An extension overriding a core name must retain its actual provenance.
    backend._view.resources = {**backend._view.resources, "allTools": [{"name":"read", "source":"fixture-extension.js", "description":"overridden", "active":True}]}
    backend.changed.emit()
    click("toolCategory_native"); assert count() == 0
    click("toolCategory_extensions"); assert count() == 1
    # Category navigation stays visible while the virtualized list scrolls.
    backend._view.resources = {**backend._view.resources, "allTools": [{"name":f"fixture_{i}","source":"fixture-extension.js","description":"Fixture " + str(i),"active":True} for i in range(250)]}
    backend.changed.emit(); QTest.qWait(40)
    assert count() == 250
    tool_list = find("toolCatalogList")
    nav_y = find("toolCategory_native").mapToScene(QPointF(0, 0)).y()
    tool_list.setProperty("contentY", 2000); QTest.qWait(100)
    wheel_before = tool_list.property("contentY") - tool_list.property("originY")
    pos = tool_list.mapToScene(QPointF(tool_list.width() / 2, tool_list.height() / 2))
    QTest.mouseMove(window, pos.toPoint()); QTest.qWait(30)
    app.sendEvent(window, QWheelEvent(pos, QPointF(window.mapToGlobal(pos.toPoint())), QPoint(), QPoint(0, 360), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
    QTest.qWait(350)
    wheel_after = tool_list.property("contentY") - tool_list.property("originY")
    assert wheel_after < wheel_before - 20, ("wheel did not scroll the tool list", wheel_before, wheel_after)
    assert find("toolCategory_native").mapToScene(QPointF(0, 0)).y() == nav_y
    stack, buttons = [tool_list], []
    while stack:
        item = stack.pop()
        if item.objectName().startswith("toolEntry_"): buttons.append(item)
        stack.extend(item.childItems())
    assert 0 < len(buttons) < 80, len(buttons)
    stable_button = buttons[0]
    stable_y = tool_list.property("contentY")
    backend.changed.emit(); QTest.qWait(30)
    assert find(stable_button.objectName()) == stable_button
    assert tool_list.property("contentY") == stable_y, "unchanged metadata reset list position"
    for theme in ("yanami", "dark", "light"):
        backend.setTheme(theme); window.resize(1060, 700); QTest.qWait(100)
        assert find("toolCategory_native").mapToScene(QPointF(0, 0)).x() >= 0
        assert tool_list.width() > 300 and tool_list.height() > 100
    capture("65-tool-catalog-compact")
    click("backToPiButton")
    assert not page.isVisible()
    click("backToAgentButton")
    assert find("openPiSettingsButton").isVisible()
    assert not warnings, "\n".join(warnings)
    print("TOOL_CATALOG_OK: native registry provenance, MCP/extension/Skills/templates/commands, search/details, disabled MCP/draft preservation, navigation, virtualized lists, themes/resize")
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
