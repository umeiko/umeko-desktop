"""Exercise the actual QML UI and Pi bridge against an in-process fake adapter."""
import os
import sys
import json
import threading
import time
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["CODEAGENT_DATA_DIR"] = tempfile.mkdtemp(prefix="codeagent-ui-test-")
os.environ["UMEKO_DATA_DIR"] = os.environ["CODEAGENT_DATA_DIR"]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QObject, QPoint, QPointF, Qt, QMetaObject, QUrl, QMimeData
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QImage, QWheelEvent
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from app.integration import Completion
from app.storage import Store
from main import create_application

fixture_store = Store()
fixture_store.data["agent"]["agentDir"] = str(fixture_store.directory / "agent")
fixture_store.save()
app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
out = ROOT / "artifacts/screenshots"
out.mkdir(parents=True, exist_ok=True)

def capture(name):
    QTest.qWait(350)
    image = window.grabWindow()
    assert not image.isNull(), name
    assert image.save(str(out / (name + ".png")))

def find_item(name):
    stack = [window.contentItem()]
    while stack:
        item = stack.pop()
        if item.objectName() == name:
            return item
        stack.extend(item.childItems())
    return window.findChild(QQuickItem, name)

def click(name):
    QTest.qWait(80)
    item = find_item(name)
    assert item, name
    reveal_setting(item)
    p = item.mapToScene(item.boundingRect().center()).toPoint()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, p)
    QTest.qWait(100)

def reveal_setting(item):
    ancestor=item.parentItem()
    while ancestor is not None:
        if ancestor.objectName().startswith('piFold_'): ancestor.setProperty('expanded',True)
        ancestor=ancestor.parentItem()
    QTest.qWait(80)
    scroll = find_item("settingsScroll")
    if scroll is None: return
    flick = scroll.property("contentItem")
    ancestor = item.parentItem()
    while ancestor is not None and ancestor != flick:
        ancestor = ancestor.parentItem()
    if ancestor is None: return
    y = item.mapToItem(flick, QPointF(0, 0)).y()
    if y < 0 or y + item.height() > flick.height():
        target = flick.property("contentY") + y - flick.height() / 2
        flick.setProperty("contentY", max(0, min(target, flick.property("contentHeight") - flick.height())))
        QTest.qWait(80)

def right_click(name):
    QTest.qWait(80)
    item = find_item(name)
    assert item, name
    point = item.mapToScene(QPointF(75, item.height() / 2)).toPoint()
    QTest.mouseClick(window, Qt.RightButton, Qt.NoModifier, point)
    QTest.qWait(150)

def wait_idle():
    for _ in range(400):
        QTest.qWait(50)
        time.sleep(0.005)
        if not backend.busy: return
    assert False, "Pi did not finish"

def wait_for(predicate, message):
    for _ in range(200):
        QTest.qWait(50)
        time.sleep(0.005)  # Background native-resource jobs need the Python GIL.
        time.sleep(0.005)
        if predicate(): return
    assert False, message

def drop_urls(name, paths):
    QTest.qWait(100)
    area = find_item(name)
    assert area, name
    point = area.mapToScene(area.boundingRect().center()).toPoint()
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    enter = QDragEnterEvent(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    app.sendEvent(window, enter)
    move = QDragMoveEvent(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    app.sendEvent(window, move)
    QTest.qWait(50)
    drop = QDropEvent(QPointF(point), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    app.sendEvent(window, drop)
    QTest.qWait(150)
    assert drop.isAccepted(), name

try:
    capture("01-chat-light")
    click("settingsButton")
    assert window.property("page") == "settings"
    assert find_item("importCustomProviderButton")
    window.setProperty("notification", "")
    capture("02-settings-account")
    click("addProviderButton")
    capture("03-add-provider")
    for name, value in {"providerName":"Local Gateway", "providerUrl":"http://127.0.0.1:18181/v1", "providerKey":"synthetic-key-only"}.items():
        window.findChild(QObject, name).setProperty("text", value)
    settings_page = window.findChild(QObject, "settingsPage")
    settings_flick = next(c for c in settings_page.findChildren(QObject) if c.metaObject().className() == "QQuickFlickable")
    settings_flick.setProperty("contentY", 350)
    QTest.qWait(100)
    click("addProviderModelButton")
    for name, value in {"providerModelId_0":"team-fast", "providerModelAlias_0":"fast", "providerModelId_1":"team-reason", "providerModelAlias_1":"reason"}.items():
        field = find_item(name)
        assert field is not None, name
        field.setProperty("text", value)
        QMetaObject.invokeMethod(field, "textEdited")
    def edit_context_field(name, text):
        field = find_item(name)
        assert field, name
        field.setProperty("text", text)
        QMetaObject.invokeMethod(field, "textEdited")
        QTest.qWait(25)
    def toggle_vision(name):
        item = find_item(name)
        reveal_setting(item)
        item.forceActiveFocus()
        QTest.keyClick(window, Qt.Key_Space)
        QTest.qWait(25)
    # Automatic defaults follow upstream IDs, then stop following on user input.
    edit_context_field("providerModelId_0", "kimi-k3")
    assert find_item("providerContext_0_input").property("text") == "1048576"
    assert find_item("providerVision_0_checkbox").property("checked")
    toggle_vision("providerVision_0_checkbox")
    assert not find_item("providerVision_0_checkbox").property("checked")
    edit_context_field("providerContext_0_input", "256K")
    edit_context_field("providerModelId_0", "gpt-4o")
    assert find_item("providerContext_0_input").property("text") == "256K"
    assert not find_item("providerVision_0_checkbox").property("checked"), "custom vision opt-out followed model name"
    QMetaObject.invokeMethod(find_item("providerVision_0_reset"), "clicked")
    assert find_item("providerVision_0_checkbox").property("checked")
    assert find_item("providerContext_0_reset").property("text") == "恢复自动"
    QMetaObject.invokeMethod(find_item("providerContext_0_reset"), "clicked")
    assert find_item("providerContext_0_input").property("text") == "128000"
    edit_context_field("providerModelId_1", "kimi-k3-256")
    assert find_item("providerContext_1_input").property("text") == "262144"
    assert find_item("providerVision_1_checkbox").property("checked")
    toggle_vision("providerVision_1_checkbox")
    toggle_vision("providerVision_1_checkbox")
    assert find_item("providerVision_1_reset").property("text") == "恢复自动"
    # Real keystrokes must keep a partial custom value rather than resetting it
    # to the automatic suggestion while the user is still typing.
    context_input = find_item("providerContext_1_input")
    context_input.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_A, Qt.ControlModifier)
    QTest.keyClick(window, Qt.Key_1)
    QTest.keyClick(window, Qt.Key_6)
    assert context_input.property("text") == "16"
    edit_context_field("providerContext_1_input", "200000")
    edit_context_field("providerModelId_0", "team-fast")
    edit_context_field("providerModelId_1", "team-reason")
    assert find_item("providerVision_1_checkbox").property("checked"), "custom vision flag followed unknown model name"
    assert find_item("providerModelId_0").width() > 120, "context column squeezed model ID"
    assert find_item("providerModelAlias_0").width() > 120, "context column squeezed alias"
    assert 180 <= find_item("providerContext_0").width() <= 200
    capture("03b-multiple-models")
    settings_flick.setProperty("contentY", max(0, settings_flick.property("contentHeight") - settings_flick.height()))
    click("saveProviderButton")
    assert len(backend.config["providers"]) == 1
    assert backend.config["providers"][-1]["hasKey"]
    assert "key" not in backend.config["providers"][-1]
    assert len(backend.config["providers"][-1]["models"]) == 2
    saved_models = backend.config["providers"][-1]["models"]
    assert saved_models[0]["contextWindowAuto"] and saved_models[0]["contextWindow"] == 128000
    assert not saved_models[1]["contextWindowAuto"] and saved_models[1]["contextWindow"] == 200000
    assert saved_models[0]["visionAuto"] and not saved_models[0]["vision"]
    assert not saved_models[1]["visionAuto"] and saved_models[1]["vision"]
    settings_flick.setProperty("contentY", 0)
    capture("03c-provider-list")
    click("editProvider_" + backend.config["providers"][-1]["id"])
    assert find_item("providerContext_1_input").property("text") == "200000"
    assert find_item("providerContext_1_reset").property("text") == "恢复自动"
    assert find_item("providerVision_1_checkbox").property("checked")
    assert find_item("providerVision_1_reset").property("text") == "恢复自动"
    settings_flick.setProperty("contentY", max(0, settings_flick.property("contentHeight") - settings_flick.height()))
    click("saveProviderButton")
    for tab, name in [(1,"04-api-proxy"),(3,"06-agent-settings"),(4,"06b-pi-kernel"),(5,"07-appearance")]:
        window.setProperty("settingsTab", tab)
        capture(name)
    window.setProperty("settingsTab", 1)
    QTest.qWait(50)
    assert find_item("mappingContext_1_input").property("text") == "200000"
    # Manual mode also survives mapping saves.
    edit_context_field("mappingContext_0_input", "0.5M")
    if not find_item("mappingVision_0_checkbox").property("checked"):
        toggle_vision("mappingVision_0_checkbox")
    click("saveMappingsButton")
    assert backend.config["providers"][0]["models"][0]["contextWindow"] == 524288
    assert backend.config["providers"][-1]["models"][1]["contextWindow"] == 200000
    assert backend.config["providers"][0]["models"][0]["vision"]
    capture("40-model-context-mapping")
    assert find_item("mappingModelId_0").width() > 120
    assert 180 <= find_item("mappingContext_0").width() <= 200
    window.resize(1060, 700)
    QTest.qWait(100)
    assert find_item("mappingModelId_0").width() > 110, "compact mapping ID is not editable"
    assert find_item("mappingContext_0_input").width() > 85
    assert find_item("mappingVision_0_checkbox").property("checked")
    assert find_item("mappingVision_0_checkbox").mapToScene(QPointF(60, 0)).x() < window.width()
    capture("41-model-context-compact")
    window.resize(1320, 860)
    QMetaObject.invokeMethod(find_item("mappingContext_0_reset"), "clicked")
    click("saveMappingsButton")
    assert backend.config["providers"][0]["models"][0]["contextWindow"] == 128000
    click("mappingHelp")
    capture("05b-context-help")
    help_button = find_item("mappingHelp")
    tooltip = window.findChild(QObject, "helpTooltip_mappingHelp")
    assert tooltip, "help popup"
    # Leave delay lets the pointer enter/select the explanation.
    QTest.mouseMove(window, QPoint(400, 90)); QTest.qWait(250)
    assert tooltip.property("visible"), "help closed before its 3-second grace period"
    QTest.qWait(3000)
    assert not tooltip.property("visible"), "help persisted after its grace period"
    point = help_button.mapToScene(help_button.boundingRect().center()).toPoint()
    QTest.mouseMove(window, point); QTest.qWait(500)
    assert tooltip.property("visible"), "hover help did not open"
    bubble_item = tooltip.property("contentItem")
    scene = bubble_item.mapToScene(QPointF(0, 0))
    assert abs(scene.x() - point.x()) < 340 and abs(scene.y() - point.y()) < 160, (scene, point)
    click("mappingHelp")
    assert not tooltip.property("visible"), "click did not close help"
    window.setProperty("settingsTab", 3)
    click("openPiSettingsButton")
    wait_for(lambda: not backend.piManagement.busy, "Initial extension scan did not finish")
    click("reloadPiButton")
    wait_idle()
    assert backend.agentResources["tools"], backend.agentResources
    click("openToolCatalogButton"); wait_idle()
    capture("20-native-capabilities")
    assert find_item("toolCatalogPage").isVisible()
    assert {"read", "bash", "powershell", "edit", "write", "grep", "find", "ls", "codemode", "tool_search"}.issubset(set(backend.agentResources["tools"]))
    click("backToPiButton"); QTest.qWait(150)
    wait_for(lambda: not backend.piManagement.busy, "Extension scan did not finish")
    click("configureMcpButton"); wait_idle()
    editor = find_item("mcpJsonEditor")
    editor.setProperty("text", '{"mcpServers":{}}')
    click("mcpSaveButton"); wait_idle()
    assert json.loads(backend.readMcp("global")) == {"mcpServers": {}}
    capture("21-mcp-json")
    backend.setDark(True)
    window.setProperty("page", "chat")
    capture("08-chat-dark")
    backend.setDark(False)
    click("modelSelector")
    model_anchor = find_item("modelSelector")
    model_search = find_item("modelSearch")
    model_popup = window.findChild(QObject, "modelPopup")
    def check_model_popup_anchor():
        padding = model_popup.property("padding")
        top_left = model_search.mapToScene(QPointF(-padding, -padding))
        button_position = model_anchor.mapToScene(QPointF(0, 0))
        assert abs(top_left.x() - button_position.x()) < 2, "model menu is detached horizontally"
        assert abs(top_left.y() + model_popup.property("height") + 8 - button_position.y()) < 2, "model menu is detached vertically"
        assert top_left.x() >= 0 and top_left.y() >= 0
    check_model_popup_anchor()
    previous_size = window.size()
    window.resize(1060, 700)
    QTest.qWait(150)
    check_model_popup_anchor()
    window.resize(previous_size)
    QTest.qWait(150)
    for parent in (model_anchor, model_popup.property("contentItem")):
        assert not any(item.property("name") == "cpu" for item in parent.findChildren(QObject)), "model chip icon remains"
    capture("09-model-picker")
    popup = window.findChild(QObject, "modelPopup")
    provider_id = backend.config["providers"][-1]["id"]
    click("modelOption_" + provider_id + "_reason")
    assert backend.config["selectedModel"] == "reason"
    backend.store.data["providers"].append({"id":"internal", "name":"Fixture", "api":"internal", "baseUrl":"", "key":"", "models":[{"upstream":"default", "alias":"umeko-default", "vision":True, "visionAuto":False}]})
    backend.selectModel("internal", "umeko-default")
    class FixtureAdapter:
        def complete(self, model, messages, tools, max_tokens):
            return Completion('这是一次本机测试。**Pi Agent 已成功连接独立网关。**\n\n```python\ndef hello():\n    return "hello"\n```\n\n第二段代码：\n\n```sh\nprintf hello\n```', input_tokens=12, output_tokens=24)
    backend.gateway.adapter = FixtureAdapter()
    backend.adapter = backend.gateway.adapter
    backend._restart_pi()
    prompt = window.findChild(QObject, "promptInput")
    prompt.setProperty("text", "帮我说明这个工作空间可以做什么。")
    prompt.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_Return)
    for _ in range(100):
        QTest.qWait(100)
        if not backend.busy:
            break
    assert not backend.busy, "Pi did not finish"
    assert len(backend.messages) == 2 and "Pi Agent" in backend.messages[-1]["text"], backend.messages
    assert not backend.messages[-1]["error"], backend.messages
    assert find_item("compactSessionButton") is None, "manual compaction remains in chat footer"
    capture("10-chat-response")
    conversation = find_item("conversation")
    assert conversation.property("acceptedButtons") == Qt.NoButton, "chat mouse dragging still enabled"
    click("copyCode_1")
    assert app.clipboard().text() == 'def hello():\n    return "hello"'
    click("copyCode_3")
    assert app.clipboard().text() == "printf hello"
    workspace = Path(os.environ["CODEAGENT_DATA_DIR"]) / "workspace"
    workspace.mkdir(exist_ok=True)
    backend.setWorkspace(QUrl.fromLocalFile(str(workspace)).toString())
    for _ in range(150):
        QTest.qWait(50)
        if not backend.busy: break
    class WriterFixture:
        def complete(self, model, messages, tools, max_tokens):
            assert "Your name is umeko" in messages[0]["content"]
            assert "You have no shell or file write tool" not in messages[0]["content"]
            if messages[-1]["role"] != "tool":
                return Completion(tool_calls=[{"id":"write-test","name":"write","arguments":{"path":"hello.txt","content":"hello world"}}])
            return Completion("已创建 hello.txt。")
    backend.gateway.adapter = WriterFixture()
    prompt.setProperty("text", "在工作目录创建 hello.txt，内容为 hello world。")
    prompt.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_Return)
    for _ in range(100):
        QTest.qWait(50)
        if not backend.busy:
            break
    assert not backend.busy and (workspace / "hello.txt").read_text() == "hello world"
    capture("15-file-created")
    click("toggleTools_1_0")
    click("toolPath_write-test")
    assert app.clipboard().text() == str((workspace / "hello.txt").resolve())
    first_session = backend.activeSession
    project_id = backend.config["activeProject"]
    click("sidebarRow_" + project_id)
    assert not backend.busy and not backend.messages and not backend.activeSession
    assert prompt.property("placeholderText") == "在 workspace 项目下开展工作"
    assert find_item("welcomeMascot").property("loaded")
    right_click("sidebarRow_" + first_session)
    assert not backend.activeSession, "right click opened session"
    capture("22-session-menu")
    click("contextCopyId")
    assert app.clipboard().text() == first_session
    right_click("sidebarRow_" + first_session)
    click("contextPinSession")
    assert backend.store.data["sessionMeta"][first_session]["pinned"]
    right_click("sidebarRow_" + project_id)
    capture("23-project-menu")
    click("contextRenameProject")
    find_item("renameInput").setProperty("text", "Fixture Project")
    click("confirmRenameButton")
    assert backend.workspaceName == "Fixture Project"
    assert prompt.property("placeholderText") == "在 Fixture Project 项目下开展工作"
    right_click("sidebarRow_" + first_session)
    click("contextRenameSession")
    find_item("renameInput").setProperty("text", "Native renamed")
    click("confirmRenameButton"); wait_idle()
    assert next(s for s in backend.sessions if s["id"] == first_session)["title"] == "Native renamed"
    right_click("sidebarRow_" + first_session)
    click("contextArchiveSession")
    assert not any(r["id"] == first_session for r in backend.projectRows)
    click("archivedViewButton")
    right_click("sidebarRow_" + first_session)
    click("contextArchiveSession")
    click("archivedViewButton")
    assert any(r["id"] == first_session for r in backend.projectRows)
    second = Path(os.environ["CODEAGENT_DATA_DIR"]) / "second-project"
    second.mkdir()
    drop_urls("projectDropArea", [second])
    assert backend.config["workspace"] == str(second.resolve())
    assert not backend.messages
    capture("24-project-empty-entry")
    dropped = second / "context.txt"
    dropped.write_text("local attachment", encoding="utf-8")
    drop_urls("composerDropArea", [dropped, second])
    assert [a["kind"] for a in backend.attachments] == ["file", "folder"]
    image = QImage(20, 20, QImage.Format_RGB32)
    image.fill(0x668877)
    app.clipboard().setImage(image)
    prompt.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_V, Qt.ControlModifier)
    QTest.qWait(150)
    assert any(a["kind"] == "image" for a in backend.attachments), backend.attachments
    app.clipboard().setText("clipboard text")
    QTest.keyClick(window, Qt.Key_V, Qt.ControlModifier)
    assert "clipboard text" in prompt.property("text")
    capture("18-projects-and-attachments")
    class VisionFixture:
        def complete(self, model, messages, tools, max_tokens):
            content = messages[-1]["content"]
            assert isinstance(content, list) and any(block.get("type") == "image_url" for block in content), messages
            return Completion("附件已由当前配置的模型收到。")
    backend.gateway.adapter = VisionFixture()
    backend.send("查看附件")
    for _ in range(150):
        QTest.qWait(50)
        if not backend.busy: break
    assert not backend.busy and not backend.messages[-1]["error"], backend.messages
    assert not backend.attachments
    backend.openSession(first_session)
    for _ in range(150):
        QTest.qWait(50)
        if not backend.busy: break
    assert backend.activeSession == first_session
    assert len([r for r in backend.projectRows if r["kind"] == "project"]) >= 2
    capture("19-project-history")
    click("newChatButton")
    for _ in range(100):
        QTest.qWait(50)
        if not backend.busy: break
    assert not backend.messages
    class ConcurrentFixture:
        def __init__(self):
            self.gates = {name: threading.Event() for name in ("async A", "async B")}
            self.started = {name: threading.Event() for name in self.gates}
        def complete(self, model, messages, tools, max_tokens):
            content = next(m["content"] for m in reversed(messages) if m["role"] == "user")
            if isinstance(content, list): content = " ".join(b.get("text", "") for b in content)
            if content in self.gates:
                self.started[content].set()
                assert self.gates[content].wait(15), "local fixture not released"
            return Completion("已处理：" + content)
    concurrent = ConcurrentFixture()
    backend.gateway.adapter = concurrent
    try:
        assert backend.send("async A")
        a = backend._view
        assert backend.loading and not backend.running
        assert find_item("sendButton").property("disabled")
        assert find_item("sendGlyph").property("name") != "stop"
        wait_for(lambda: concurrent.started["async A"].is_set(), "first asynchronous task did not start")
        a_id, a_pid = a.id, a.process.processId()
        assert find_item("sessionSpinner_" + a_id).isVisible()
        capture("26-task-running")
        click("newChatButton")
        assert not backend.busy and not backend.messages
        assert backend.send("async B")
        b = backend._view
        wait_for(lambda: concurrent.started["async B"].is_set(), "second asynchronous task did not start")
        b_id = b.id
        click("sidebarRow_" + backend.config["activeProject"])
        assert not backend.busy and not backend.messages
        concurrent.gates["async B"].set()
        wait_for(lambda: not b.busy, "background task did not complete")
        assert find_item("sessionUnread_" + b_id).isVisible()
        capture("27-background-complete")
        click("sidebarRow_" + a_id)
        assert a.process.processId() == a_pid and backend.running
        prompt.setProperty("text", "排队补充")
        prompt.forceActiveFocus()
        QTest.keyClick(window, Qt.Key_Return)
        wait_for(lambda: len(backend.queuedMessages) == 1, "Enter did not queue the follow-up")
        assert backend.running and not a.cancelled
        click("editQueued_0")
        wait_for(lambda: not backend.queuedMessages and prompt.property("text") == "排队补充", "queued message did not return to editor")
        prompt.setProperty("text", "排队补充（已编辑）")
        QTest.keyClick(window, Qt.Key_Return)
        wait_for(lambda: len(backend.queuedMessages) == 1, "edited message did not requeue")
        prompt.setProperty("text", "待删除的排队消息")
        QTest.keyClick(window, Qt.Key_Return)
        wait_for(lambda: len(backend.queuedMessages) == 2, "second queued row did not appear")
        capture("28-compact-queue-list")
        click("removeQueued_1")
        wait_for(lambda: len(backend.queuedMessages) == 1, "row deletion did not clear queue item")
        prompt.forceActiveFocus()
        QTest.keyClick(window, Qt.Key_S, Qt.ControlModifier)
        wait_for(lambda: any(m["role"] == "user" and "排队补充（已编辑）" in m["text"] for m in backend.messages), "Ctrl+S did not immediately insert the message")
        assert not backend.queuedMessages, "interrupted message remained as a queue chip"
        capture("28-native-interrupt")
        concurrent.gates["async A"].set()
        wait_idle()
        assert not a.cancelled
        assert not backend.queuedMessages, "consumed steering chip remained above the editor"
        assert any(m["role"] == "user" and "排队补充" in m["text"] for m in backend.messages)
        click("sidebarRow_" + b_id)
        assert not backend.store.data["sessionMeta"][b_id]["unread"]
    finally:
        for gate in concurrent.gates.values(): gate.set()
    click("settingsButton")
    window.setProperty("settingsTab", 5)
    click("theme_yanami")
    assert backend.config["theme"] == "yanami" and not backend.config["dark"]
    capture("29-yanami-theme-settings")
    click("newChatButton")
    greeting, portrait = backend.greeting, backend.portrait
    assert find_item("welcomeGreeting").property("text") == greeting
    assert find_item("welcomeMascot").property("loaded")
    backend.changed.emit()
    assert (backend.greeting, backend.portrait) == (greeting, portrait)
    capture("30-yanami-theme-chat")
    for index in range(1, 13):
        asset = QImage(str(ROOT / f"app/icons/portraits/{index:02d}.png"))
        assert not asset.isNull() and asset.hasAlphaChannel(), index
        assert asset.pixelColor(0, 0).alpha() == 0, index
    class StreamingFixture:
        def __init__(self): self.advance = threading.Event()
        def events(self, model, messages, tools, max_tokens, parameters):
            text = "\n\n".join(f"第 {index} 条历史内容：" + "这是一段用于滚动验证的本地内容。" * 5 for index in range(45))
            yield {"choices":[{"index":0,"delta":{"role":"assistant","content":text},"finish_reason":None}]}
            assert self.advance.wait(15), "stream fixture not released"
            for index in range(20):
                yield {"choices":[{"index":0,"delta":{"content":f"\n\n新增第 {index} 段内容。"},"finish_reason":None}]}
                time.sleep(0.025)
            yield {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}
    stream = StreamingFixture()
    backend.gateway.adapter = stream
    try:
        assert backend.send("验证流式浏览")
        wait_for(lambda: conversation.property("contentHeight") > conversation.height() * 2, "stream history did not render")
        QTest.qWait(200)
        QMetaObject.invokeMethod(conversation, "positionViewAtEnd")
        QTest.qWait(100)
        before_wheel = conversation.property("contentY")
        point = conversation.mapToScene(QPointF(conversation.width()/2, conversation.height()/2))
        global_point = window.mapToGlobal(point.toPoint())
        event = QWheelEvent(point, QPointF(global_point), QPoint(0, 0), QPoint(0, 720), Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False)
        app.sendEvent(window, event)
        QTest.qWait(350)
        assert not conversation.property("followTail"), "wheel browsing did not pause follow"
        position = conversation.property("contentY")
        assert position < before_wheel - 20, ("wheel changed follow mode but did not scroll", before_wheel, position)
        offset = position - conversation.property("originY")
        assert position < conversation.property("contentHeight") - conversation.height() - 30
        stream_id = backend.activeSession
        stream.advance.set()
        wait_idle()
        assert abs(conversation.property("contentY") - position) < 2, (position, conversation.property("contentY"))
        anchor, inner_offset = backend.scrollAnchor, backend.scrollPosition
        capture("31-stream-reading-stable")
        click("newChatButton")
        backend.openSession(stream_id)
        QTest.qWait(200)
        assert backend.scrollAnchor == anchor and abs(backend.scrollPosition - inner_offset) < 2, ("switching lost visible message anchor", anchor, inner_offset, backend.scrollAnchor, backend.scrollPosition)
        assert not conversation.property("followTail")
        QMetaObject.invokeMethod(conversation, "positionViewAtEnd")
        QTest.qWait(100)
        assert conversation.property("followTail"), "reaching bottom did not resume follow"
    finally:
        stream.advance.set()
    click("newChatButton")
    window.resize(1060, 700)
    capture("11-compact")
    assert not warnings, "\n".join(warnings)
    print("UI passed: parallel task switching, loading/send states, activity and unread indicators, native follow-up/steering, stable stream browsing and restored message anchor, tool-path clipboard, 12 transparent portraits, Yanami theme, context menus, providers, MCP JSON and native Pi tools.")
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
