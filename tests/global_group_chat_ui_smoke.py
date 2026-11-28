"""Real Qt and SQLite coverage for group chat and its native delivery boundary."""
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run(directory):
    profile = directory / "profile"
    os.environ.update(UMEKO_DATA_DIR=str(profile), PI_CODING_AGENT_DIR=str(profile / "pi"),
                      UMEKO_LANGUAGE="zh", QT_QUICK_BACKEND="software")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication, QMimeData, QObject, QPointF, Qt, QUrl
    from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QImage, QInputMethodEvent
    from PySide6.QtQml import QQmlEngine, QQmlExpression
    from PySide6.QtTest import QSignalSpy, QTest
    from app.integration import Completion
    from app.pi_runtime import RELEASE_NAME, verify_runtime
    from app.storage import Store
    from main import create_application

    store = Store(profile)
    store.data.update(selectedProvider="internal", selectedModel="fixture", providers=[{
        "id": "internal", "name": "Local fixture", "api": "internal", "baseUrl": "", "key": "",
        "models": [{"upstream": "fixture", "alias": "fixture"}],
    }])
    store.data["agent"]["agentDir"] = str(profile / "pi")
    store.data["desktop"]["teamCollaborationEnabled"] = True
    store.save()
    settings = profile / "desktop-plugins/settings.json"
    settings.parent.mkdir(exist_ok=True)
    settings.write_text(json.dumps({"config": {"desktop-pet": {"visible": False}}}), encoding="utf-8")
    app, engine, backend = create_application()
    class NoModel:
        ready = True

        def complete(self, *args, **kwargs):
            raise AssertionError("UI fixture must not call a model")

    backend.adapter = backend.gateway.adapter = NoModel()
    window = engine.rootObjects()[0]
    warnings = []
    engine.warnings.connect(lambda values: warnings.extend(value.toString() for value in values))
    window.resize(1320, 950)
    service = backend.desktopPlugins.global_agents
    service.timer.stop()
    identifiers = [service.handle("create", {"name": name})["id"] for name in ("研发甲", "复核乙", "资料丙")]
    direct, relay, third = ["agent:" + identifier for identifier in identifiers]

    def find(name):
        pending = [window.contentItem()]
        while pending:
            item = pending.pop()
            if item.objectName() == name:
                return item
            if item.objectName() not in ("webSurfaceLoader", "htmlPreviewBrowser"):
                pending.extend(item.childItems())
        return window.findChild(QObject, name)

    def wait(check, label):
        deadline = monotonic() + 8
        while monotonic() < deadline:
            QTest.qWait(20)
            if check():
                return
        raise AssertionError(label + "\n" + "\n".join(warnings))

    def click(name, button=Qt.LeftButton):
        wait(lambda: (item := find(name)) and item.isVisible() and item.isEnabled(), "Unavailable: " + name)
        item = find(name)
        QTest.mouseClick(window, button, Qt.NoModifier, item.mapToScene(item.boundingRect().center()).toPoint())

    def evaluate(name, code):
        item = find(name)
        expression = QQmlExpression(QQmlEngine.contextForObject(item), item, code)
        value, _ = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        return value

    def wait_menu(name):
        wait(lambda: find(name).property("opened") and not find(name).property("animating"),
             "Context menu did not open: " + name)

    def deliver(item):
        record = service.record(item["target"])
        service.observe(record, {"type": "widget_delivery", "id": item["id"], "status": "delivered"})
        return record

    try:
        assert backend.desktopPlugins.openPage("global-agents")
        wait(lambda: find("webPane") and find("webPane").property("live"), "Widget did not settle")
        click("groupChatTabButton")
        wait(lambda: (item := find("groupChat")) and item.property("active"), "Group did not load")
        wait(lambda: evaluate("groupChat", "mentionChoices.length") == 4, "Group members did not load")
        tree = find("agentBusProjectTree")
        assert tree.property("count") == 0, "Group snapshots populated the hidden Agent Bus"
        click("agentBusTabButton")
        wait(lambda: tree.property("count") > 0, "Agent Bus did not load when opened")
        click("groupChatTabButton")
        wait(lambda: find("groupChat").property("active"), "Returning from Agent Bus did not reopen the group")
        config_changed = QSignalSpy(backend.changed)
        for result in ({'ok': True, 'value': {'messages': []}}, {'ok': False, 'value': 'fixture error'}):
            replies = []
            task = 'group-chat:polling-fixture'
            service.group_chat.jobs[task] = replies.append
            backend.jobDone.emit(task, result)
            assert replies == [result] and task not in service.group_chat.jobs
        assert config_changed.count() == 0, "Group results invalidated desktop configuration"
        original_theme = backend.config['theme']
        original_color = find("groupChat").property("color")
        selected_theme = 'dark' if original_theme != 'dark' else 'white'
        backend.setTheme(selected_theme)
        assert config_changed.count() == 1
        wait(lambda: find("groupChat").property("color") != original_color, "Theme change did not reach the group UI")
        backend.setTheme(original_theme)
        assert find("agentBusRequestsTabButton") is None
        assert find("groupChatPicker") is None
        composer = find("groupChatComposer")
        assert composer.property("text") == ""
        assert evaluate("groupChat", "selectedMention.id") == "all"
        composer.setProperty("text", "hello")
        assert find("groupChatSend").isEnabled()
        click("groupChatClearMention")
        assert composer.property("text") == "hello"
        assert not find("groupChatSend").isEnabled()
        click("groupChatComposer")
        composer.setProperty("text", "@")
        composer.setProperty("cursorPosition", 1)
        wait(lambda: find("groupChatMentionPopup").property("opened"), "Mention suggestions did not open")
        assert evaluate("groupChat", "suggestions.length") == 4
        wait(composer.hasActiveFocus, "Mention popup took focus from the composer")
        QTest.keyClick(window, Qt.Key_Down)
        wait(lambda: evaluate("groupChat", "mentionIndex") == 1, "Down did not change the highlighted member")
        evaluate("groupChat", "showSuggestions()")
        assert evaluate("groupChat", "mentionIndex") == 1, "Refreshing members reset the highlighted member"
        QTest.keyClick(window, Qt.Key_Return)
        wait(lambda: evaluate("groupChat", "selectedMention?.id") == direct, "Keyboard selection did not set mention")
        assert composer.property("text") == ""
        click("groupChatMentionChip")
        QTest.keyClick(window, Qt.Key_Home)
        QTest.keyClick(window, Qt.Key_Left)
        assert composer.property("cursorPosition") == 0
        QCoreApplication.sendEvent(window, QInputMethodEvent("d", []))
        assert composer.property("inputMethodComposing")
        assert evaluate("groupChat", "selectedMention.id") == direct
        assert not find("groupChatMentionPopup").property("opened")
        commit = QInputMethodEvent()
        commit.setCommitString("的")
        QCoreApplication.sendEvent(window, commit)
        assert composer.property("text") == "的"
        QTest.keyClick(window, Qt.Key_Home)
        QTest.keyClick(window, Qt.Key_Backspace)
        assert not find("groupChatMentionChip").isVisible()
        assert composer.property("text") == "的"
        assert not find("groupChatSend").isEnabled()
        composer.setProperty("text", "Please @研 review")
        composer.setProperty("cursorPosition", len("Please @研"))
        wait(lambda: find("groupChatMentionPopup").property("opened"), "Filtered suggestions did not open")
        QTest.keyClick(window, Qt.Key_Return)
        assert evaluate("groupChat", "selectedMention.id") == direct
        assert composer.property("text") == "Please  review"
        source = directory / "notes.txt"
        source.write_text("group-chat attachment", encoding="utf-8")
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(source))])
        point = composer.mapToScene(composer.boundingRect().center()).toPoint()
        app.sendEvent(window, QDragEnterEvent(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
        app.sendEvent(window, QDragMoveEvent(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
        assert find("groupChatDropOverlay").isVisible()
        event = QDropEvent(QPointF(point), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        app.sendEvent(window, event)
        assert event.isAccepted() and not find("groupChatDropOverlay").isVisible()
        assert evaluate("groupChat", "files[0].name") == source.name
        assert not service.outbox and not backend.attachments

        image = QImage(20, 12, QImage.Format_RGB32)
        image.fill(0x4682B4)
        app.clipboard().setImage(image)
        QTest.keyClick(window, Qt.Key_V, Qt.ControlModifier)
        wait(lambda: evaluate("groupChat", "files.length") == 2, "Image paste did not add an attachment")
        assert evaluate("groupChat", "files[1].kind") == "image"
        assert not backend.attachments
        composer.setProperty("text", "")
        app.clipboard().setText("native text paste")
        QTest.keyClick(window, Qt.Key_V, Qt.ControlModifier)
        assert composer.property("text") == "native text paste"
        composer.setProperty("text", "Please review")
        click("groupChatSend")
        wait(lambda: len(service.outbox) == 1, "Direct group send did not queue")
        item = next(iter(service.outbox.values()))
        assert item["target"] == direct and "(from group chat)" in item["message"]
        attachment = Path(item["data"]["files"][0]["path"])
        assert attachment != source and attachment.read_text() == source.read_text()
        assert not QImage(item["data"]["files"][1]["path"]).isNull()
        record = deliver(item)
        try:
            service.execute("agent_bus.reply_to_groupchat", {"text": "invalid", "recipient": "all"}, record)
        except ValueError:
            pass
        else:
            raise AssertionError("An agent could reply to everyone")
        assert service.execute("agent_bus.reply_to_groupchat", {"text": "handoff", "recipient": relay}, record)["forwarded"]
        record_b = deliver(next(iter(service.outbox.values())))
        assert not service.execute("agent_bus.reply_to_groupchat", {"text": "no cascade", "recipient": third}, record_b)["forwarded"]
        assert not service.outbox
        wait(lambda: find("groupChatMessages").property("count") == 3, "Visible replies did not render")
        wait(lambda: (image := find("groupChatSentImage")) and image.isVisible()
             and evaluate("groupChatSentImage", "status === 1"), "Sent attachment image did not render")
        assert evaluate("groupChat", "selectedMention.id") == "all"
        group_history = service.handle("groupChatHistory", {})["messages"]
        original = group_history[1]
        original_bubble = f'groupChatBubble_{original["id"]}'
        composer.setProperty("text", "draft")
        click(original_bubble, Qt.RightButton)
        wait_menu("groupChatMessageMenu")
        click("groupChatCopyMessage")
        assert app.clipboard().text() == "handoff"
        click(original_bubble, Qt.RightButton)
        wait_menu("groupChatMessageMenu")
        click("groupChatQuoteMessage")
        assert evaluate("groupChat", "selectedMention.id") == direct
        assert find("groupChatDraftQuote").isVisible()
        assert composer.property("text") == "draft"
        assert composer.hasActiveFocus()
        click("groupChatClearQuote")
        assert not find("groupChatDraftQuote").isVisible()
        assert composer.property("text") == "draft"
        click(original_bubble, Qt.RightButton)
        wait_menu("groupChatMessageMenu")
        click("groupChatQuoteMessage")
        composer.setProperty("text", "I saw that")
        click("groupChatSend")
        wait(lambda: len(service.outbox) == 1, "Quoted reply did not reach the agent inbox")
        quoted = next(iter(service.outbox.values()))
        assert quoted["target"] == direct and "data.quote" in quoted["message"]
        assert quoted["data"]["quote"] == {
            "messageId": original["id"], "author": direct, "authorName": "研发甲",
            "text": "handoff", "files": [],
        }
        deliver(quoted)
        quote_key = f'groupChatQuote_{quoted["data"]["sequence"]}'
        wait(lambda: (item := find(quote_key)) and item.isVisible(), "Sent quote did not render under the bubble")
        assert find(quote_key).property("summary") == "研发甲: handoff"
        assert find(quote_key).property("trailingRule")
        assert not find("groupChatDraftQuote").isVisible()

        click("groupChatDetailsButton")
        wait(lambda: find("groupChatDetails").property("opened"), "Group details did not open")
        click("groupChatStartSearch")
        search = find("groupChatSearchField")
        wait(search.hasActiveFocus, "Search did not receive keyboard focus")
        search.setProperty("text", " HANDOFF ")
        wait(lambda: find("groupChatMessages").property("count") == 1
             and find(original_bubble) and find(original_bubble).isVisible(), "Group search did not find the original message")
        QTest.keyClick(window, Qt.Key_Escape)
        wait(lambda: find("groupChatMessages").property("count") == 4, "Closing search did not restore history")
        composer.setProperty("text", "draft")
        click("groupChatAvatar_" + direct, Qt.RightButton)
        wait_menu("groupChatAvatarMenu")
        mention_action = find("groupChatMentionAgent")
        poke_action = find("groupChatPokeAgent")
        assert mention_action.isVisible() and mention_action.property("text") == "@研发甲"
        assert poke_action.isVisible() and poke_action.property("text") == "拍一拍"
        assert mention_action.width() >= 150 and poke_action.width() == mention_action.width()
        assert window.contentItem().boundingRect().contains(poke_action.mapRectToScene(poke_action.boundingRect()))
        click("groupChatMentionAgent")
        assert evaluate("groupChat", "selectedMention.id") == direct
        assert composer.property("text") == "draft"
        click("groupChatAvatar_" + direct, Qt.RightButton)
        QTest.keyClick(window, Qt.Key_Escape)
        wait(lambda: not find("groupChatAvatarMenu").property("opened"), "Escape did not dismiss the shared menu")
        click("groupChatAvatar_" + direct)
        wait(lambda: find("globalAgentsPage").property("selected") == identifiers[0], "Avatar did not open direct chat")
        evaluate("globalAgentsPage", 'openAgent("")')
        wait(lambda: find("groupChat").isVisible(), "Returning from direct chat did not restore group chat")
        backend.setTheme("dark")
        window.setProperty("webPreferredWidth", 320)
        evaluate("webPane", "snapWidth()")
        wait(lambda: 270 <= find("groupChat").width() <= 320, "Narrow group layout did not fit")
        assert find("groupChatComposer").isVisible() and find("groupChatSend").isVisible()

        record.busy = record.ready = True
        service.handle("groupChatSend", {"recipient": direct, "text": "queue while busy"})
        service.handle("groupChatPoke", {"recipient": direct})
        with patch.object(backend._pool, "write") as write:
            service.tick()
            write.assert_called_once()
            _, command = write.call_args.args
            assert command["type"] == "widget-notify" and command["notification"]["data"]["text"] == "queue while busy"
            deliver(next(item for item in service.outbox.values() if item["sent"]))
            service.tick()
            assert write.call_count == 2
            _, command = write.call_args.args
            assert command["type"] == "widget-notify" and command["notification"]["data"]["poke"]
            assert command["notification"]["data"]["text"] == "user 拍了拍你"
        history = service.handle("groupChatHistory", {})
        assert [row["text"] for row in history["messages"]] == [
            "Please review", "handoff", "no cascade", "I saw that", "queue while busy", "user 拍了拍你"]
        assert history["messages"][3]["quote"] == quoted["data"]["quote"]
        record.busy = False

        click("groupChatDetailsButton")
        click("groupChatClearHistory")
        wait(lambda: find("groupChatClearConfirmation").property("opened"), "Clear confirmation did not open")
        click("groupChatCancelClear")
        assert service.handle("groupChatHistory", {}) == history
        click("groupChatDetailsButton")
        click("groupChatClearHistory")
        wait(lambda: not evaluate("groupChat", "reading"), "Initial history request did not settle")
        chat = service.group_chat
        chat.append(service.team_board.storage(), "user", "all", "Stale before clear")
        started, release = Event(), Event()
        original_history = chat.history

        def held_history(*args):
            snapshot = original_history(*args)
            if not started.is_set():
                started.set()
                assert release.wait(15)
            return snapshot

        with patch.object(chat, "history", side_effect=held_history):
            try:
                evaluate("groupChat", "refresh()")
                wait(started.is_set, "The history request did not start")
                click("groupChatConfirmClear")
                wait(lambda: find("groupChatMessages").property("count") == 0, "Cleared messages are still visible")
                assert evaluate("groupChat", "reading")
            finally:
                release.set()
            wait(lambda: not evaluate("groupChat", "reading || refreshQueued"), "Refresh after clear did not settle")
            assert find("groupChatMessages").property("count") == 0, "A stale history response restored cleared messages"
        assert not service.handle("groupChatHistory", {})["messages"]
        assert not service.group_chat.active
        assert attachment.is_file()

        # Exercise the tool schema, the native reply call, and the persisted cards.
        verify_runtime(ROOT / "runtime" / "releases" / RELEASE_NAME, ROOT / "runtime" / "bridge.mjs")
        generated = Path(record.workspace) / "交付 包.zip"
        with ZipFile(generated, "w") as archive:
            archive.writestr("readme.txt", "group delivery")
        generated_image = generated.with_name("截图.png")
        assert image.save(str(generated_image))
        escaped = directory / "outside.txt"
        escaped.write_text("not in the agent workspace", encoding="utf-8")
        calls = []
        model_tools = []
        private_tool_names = []

        class FileModel:
            ready = True

            def complete(self, _model, messages, tools, _max_tokens):
                last = messages[-1]
                tool_names = {tool.get("name", tool.get("function", {}).get("name")) for tool in tools}
                model_tools.append(tool_names)
                content = last.get("content", "")
                if isinstance(content, list):
                    content = "\n".join(block.get("text", "") for block in content if block.get("type") == "text")
                if last["role"] == "user" and content == "Private check":
                    private_tool_names.append(tool_names)
                    return Completion("Private turn")
                if last["role"] != "tool":
                    assert "reply_to_groupchat" in tool_names
                    return Completion(tool_calls=[{"id": "outside", "name": "reply_to_groupchat",
                        "arguments": {"items": [{"path": str(escaped)}]}}])
                calls.append(last["content"])
                if last.get("tool_call_id") == "outside":
                    return Completion(tool_calls=[{"id": "artifact", "name": "reply_to_groupchat",
                        "arguments": {"items": [{"path": generated.name}, {"path": generated_image.as_uri()}]}}])
                return Completion("Delivered")

        backend.adapter = backend.gateway.adapter = FileModel()
        fresh = service.handle("groupChatSend", {"recipient": direct, "text": "after clear"})["message"]
        assert fresh["id"] > history["messages"][-1]["id"]
        service.tick()
        wait(lambda: find("groupChatMessages").property("count") == 2 or record.failed,
             "The native tool's attachments did not arrive")
        assert not record.failed, (model_tools, record.messages[-2:])
        wait(lambda: len(calls) == 2, "Pi did not receive both tool results")
        assert "必须来自当前工作目录" in str(calls[0]) and "forwarded" in str(calls[1])
        delivery = service.handle("groupChatHistory", {})["messages"][-1]
        assert delivery["author"] == direct and delivery["text"] == ""
        saved_zip, saved_image = delivery["files"]
        assert saved_zip["name"] == generated.name and saved_zip["bytes"] == generated.stat().st_size
        assert saved_image["pixelWidth"] == image.width() and saved_image["pixelHeight"] == image.height()
        assert Path(saved_zip["path"]).read_bytes() == generated.read_bytes()
        wait(lambda: not record.busy, "Group turn did not finish")
        service.handle("send", {"id": identifiers[0], "text": "Private check"})
        wait(lambda: bool(private_tool_names) or record.failed, "Private turn did not reach the model")
        assert not record.failed, (model_tools, record.messages[-2:])
        assert "umeko_desktop" in private_tool_names[0] and "reply_to_groupchat" not in private_tool_names[0]
        wait(lambda: not record.busy, "Private turn did not finish")
        file_card = f'groupChatFile_{delivery["id"]}_0'

        with patch("app.group_chat.open_attachment", return_value=True) as open_file:
            click(file_card)
            wait(lambda: open_file.called, "Attachment left click did not open the archive")
            open_file.assert_called_once_with(Path(saved_zip["path"]))
        click(file_card, Qt.RightButton)
        wait_menu("groupChatFileMenu")
        click("groupChatCopyFile")
        wait(lambda: [Path(url.toLocalFile()) for url in app.clipboard().mimeData().urls()] == [Path(saved_zip["path"])],
             "Copy did not put the file on the system clipboard")
        with patch.object(backend, "openChatboxPath") as reveal:
            click(file_card, Qt.RightButton)
            wait_menu("groupChatFileMenu")
            click("groupChatRevealFile")
            wait(lambda: reveal.called, "Reveal did not invoke the file manager")
            reveal.assert_called_once_with(saved_zip["path"], True)
        click(file_card, Qt.RightButton)
        wait_menu("groupChatFileMenu")
        click("groupChatSaveFile")
        picker = find("groupChatSaveDialog")
        assert picker.property("selectedFile").fileName() == generated.name
        target = directory / "saved-copy.zip"
        picker.setProperty("selectedFile", QUrl.fromLocalFile(str(target)))
        picker.accepted.emit()
        evaluate("groupChatSaveDialog", "close()")
        wait(target.is_file, "Save as did not create a copy")
        assert target.read_bytes() == generated.read_bytes()

        click(file_card, Qt.RightButton)
        wait_menu("groupChatFileMenu")
        click("groupChatQuoteFile")
        assert evaluate("groupChat", "selectedMention.id") == direct
        assert evaluate("groupChat", "quotedMessage.files[0].name") == generated.name
        composer.setProperty("text", "Received")
        click("groupChatSend")
        wait(lambda: find("groupChatMessages").property("count") == 3, "Quoted file reply was not saved")
        quote = service.handle("groupChatHistory", {})["messages"][-1]["quote"]
        assert quote["files"] == [{"name": generated.name}] and quote["fileIndex"] == 0
        assert not [warning for warning in warnings if "GroupChat.qml" in warning], warnings
        print("GLOBAL_GROUP_CHAT_UI_OK: mentions, attachment tools, file actions, quote, search, clear, and steering")
    finally:
        app.clipboard().clear()
        backend.close()
        window.close()
        app.processEvents()


if __name__ == "__main__":
    with TemporaryDirectory(prefix="umeko-group-chat-") as directory:
        run(Path(directory))
