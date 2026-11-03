"""Exercise real chat QML offscreen; every external action is a recorder.

Run normally with unittest.  ``--screenshots DIR`` additionally writes bilingual
PNG examples after the suite; it never starts the application or a provider.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class ConversationLinkActionsTests(unittest.TestCase):
    def test_real_qml_and_controller_actions_offscreen(self):
        with tempfile.TemporaryDirectory(prefix="conversation-links-") as temporary:
            env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                       QSG_RHI_BACKEND="software", QT_QUICK_CONTROLS_STYLE="Basic",
                       TMP=temporary, TEMP=temporary,
                       UMEKO_DATA_DIR=str(Path(temporary) / "profile"),
                       PI_CODING_AGENT_DIR=str(Path(temporary) / "agent"), PYTHONUTF8="1")
            command = [sys.executable, str(Path(__file__).resolve()), "--offscreen-child"]
            screenshots = os.environ.get("UMEKO_CONVERSATION_SCREENSHOTS")
            if screenshots:
                command.extend(["--screenshots", screenshots])
            child = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                                   text=True, encoding="utf-8", timeout=90,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(child.returncode, 0, child.stdout + child.stderr)


def offscreen_suite(screenshots=None):
    # Set these before importing Qt, even if this file is invoked directly.
    os.environ.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                      QSG_RHI_BACKEND="software", QT_QUICK_CONTROLS_STYLE="Basic")
    from PySide6.QtCore import (QObject, Property, Signal, Slot, QMetaObject, Q_ARG,
                                Q_RETURN_ARG, Qt, QUrl, QEventLoop, QTimer)
    from PySide6.QtGui import QFont, QFontDatabase, QTextCursor
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickWindow  # Register the window Python wrapper.
    from PySide6.QtWidgets import QApplication
    from app.syntax_highlight import register_text_types
    import shiboken6

    application = QApplication.instance() or QApplication([])
    if os.name == "nt":
        for filename in ("msyh.ttc", "segoeui.ttf"):
            QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / filename))
    application.setFont(QFont("Microsoft YaHei UI" if os.name == "nt" else "sans-serif", 10))
    register_text_types()

    def settle():
        # Let QML bindings, zero-delay selection refreshes and popup layout run.
        # There are no elapsed-time or frame-rate assertions.
        loop = QEventLoop()
        QTimer.singleShot(60, loop.quit)
        loop.exec()

    def qml_call(obj, name, *args):
        result = QMetaObject.invokeMethod(
            obj, name, Qt.DirectConnection, Q_RETURN_ARG("QVariant"),
            *(Q_ARG("QVariant", arg) for arg in args))
        return result.toVariant() if hasattr(result, "toVariant") else result

    class Backend(QObject):
        changed = Signal()
        viewChanged = Signal()

        def __init__(self, workspace):
            super().__init__()
            self.values = {"language": "en", "busy": False,
                           "conversationWorkspace": str(workspace), "fontScale": 1.0,
                           "themeStyle": {"base": "light", "colors": {}},
                           "config": {"theme": "light"}, "lineSpacing": "standard",
                           "messageText": "", "tools": []}
            self.calls = []

        language = Property(str, lambda self: self.values["language"], notify=changed)
        busy = Property(bool, lambda self: self.values["busy"], notify=changed)
        conversationWorkspace = Property(str, lambda self: self.values["conversationWorkspace"], notify=changed)
        fontScale = Property(float, lambda self: self.values["fontScale"], notify=changed)
        themeStyle = Property("QVariantMap", lambda self: self.values["themeStyle"], notify=changed)
        config = Property("QVariantMap", lambda self: self.values["config"], notify=changed)
        lineSpacing = Property(str, lambda self: self.values["lineSpacing"], notify=changed)
        messageText = Property(str, lambda self: self.values["messageText"], notify=changed)
        tools = Property("QVariantList", lambda self: self.values["tools"], notify=changed)
        messageCount = Property(int, lambda self: 1, constant=True)
        messageModel = Property("QVariantMap", lambda self: {"paged": False}, constant=True)

        def update(self, **values):
            self.values.update(values)
            self.changed.emit()
            settle()

        @Slot(str, bool)
        def openConversationPath(self, path, reveal):
            self.calls.append(("path", path, reveal))

        @Slot(str)
        def openConversationUrl(self, url):
            self.calls.append(("url", url))

        @Slot(str)
        def copy(self, value):
            self.calls.append(("copy", value))

        @Slot(int, result="QVariantMap")
        def displayMessage(self, index):
            return {"role": "assistant", "text": self.values["messageText"]}

    source = '''import QtQuick
import QtQuick.Controls
import "QML_DIRECTORY" as Umeko
ApplicationWindow {
    width: 900; height: 680; visible: true; color: Umeko.Theme.bg
    title: "Conversation link fixture"
    function linkAtOffset(editor, offset) {
        const r = editor.positionToRectangle(offset)
        return editor.conversationLinkAt(r.x + 1, r.y + r.height / 2)
    }
    function selectionPoint(editor, offset) {
        const r = editor.positionToRectangle(offset)
        return editor.mapToItem(selection, r.x + 1, r.y + r.height / 2)
    }
    Column {
        id: content; x: 42; y: 30; width: 800; spacing: 20
        Text { text: backend.language === "zh" ? "对话中的文件和网址" : "Files and URLs in conversation"
               color: Umeko.Theme.ink; font.pixelSize: 21; font.family: Umeko.Theme.fontFamily }
        Text { text: backend.language === "zh" ? "测试对话 · 项目文件" : "Test conversation · project files"
               color: Umeko.Theme.muted; font.pixelSize: 12; font.family: Umeko.Theme.fontFamily }
        Umeko.MessageBody {
            objectName: "assistantBody"; width: parent.width; messageIndex: 0
            selectionController: selection; text: backend.messageText
        }
        Umeko.ToolHistory {
            objectName: "history"; width: parent.width; messageIndex: 1
            selectionController: selection; tools: backend.tools
            expansionState: ({expanded: true, details: ({"tool-1": true})})
        }
    }
    Umeko.ChatSelection {
        id: selection; anchors.fill: parent; z: 10
        view: QtObject { property real contentY: 0; function beginBrowsing() {} function scrollBy(delta) {} }
    }
}'''.replace("QML_DIRECTORY", QUrl.fromLocalFile(str(ROOT / "app/qml")).toString())

    class Harness:
        def __init__(self):
            self.temporary = tempfile.TemporaryDirectory(prefix="chat-link-fixture-")
            self.workspace = Path(self.temporary.name)
            for filename in ("guide.txt", "notes.md", "sample.cpp", "run.cmd", "payload.exe", "image.png"):
                (self.workspace / filename).write_text("fixture only\n", encoding="utf-8")
            (self.workspace / "folder").mkdir()
            self.backend = Backend(self.workspace)
            self.engine = QQmlApplicationEngine()
            self.warnings = []
            self.engine.warnings.connect(lambda errors: self.warnings.extend(e.toString() for e in errors))
            self.engine.rootContext().setContextProperty("backend", self.backend)
            self.engine.loadData(source.encode("utf-8"))
            if not self.engine.rootObjects():
                raise AssertionError("\n".join(self.warnings))
            self.window = self.engine.rootObjects()[0]
            settle()

        def find(self, name, parent=None):
            # Repeater delegates belong to a visual parent without necessarily
            # being children of it in QObject's ownership tree. Menus also keep
            # nonvisual action objects, so traverse both kinds of relationship.
            pending, visited = [parent or self.window], set()
            while pending:
                item = pending.pop()
                identity = shiboken6.getCppPointer(item)[0]
                if identity in visited:
                    continue
                visited.add(identity)
                if item.objectName() == name:
                    return item
                pending.extend(item.children())
                if hasattr(item, "childItems"):
                    pending.extend(item.childItems())
                if callable(getattr(item, "contentItem", None)):
                    content_item = item.contentItem()
                    if content_item is not None:
                        pending.append(content_item)
            raise AssertionError("Missing QML object: " + name)

        def prose(self):
            return self.find("selectText_0_0")

        @staticmethod
        def document(editor):
            return editor.property("textDocument").textDocument()

        @staticmethod
        def fragments(document):
            block = document.begin()
            while block.isValid():
                iterator = block.begin()
                while not iterator.atEnd():
                    fragment = iterator.fragment()
                    if fragment.isValid():
                        yield fragment
                    iterator += 1
                block = block.next()

        def anchors(self, editor):
            decorator = self.find("conversationLinks", editor)
            rows = []
            for fragment in self.fragments(self.document(editor)):
                style = fragment.charFormat()
                href = style.anchorHref()
                if href:
                    info = decorator.linkInfo(href)
                    rows.append({"text": fragment.text(), "href": href, "info": info,
                                 "position": fragment.position(), "color": style.foreground().color().name(),
                                 "underline": style.fontUnderline()})
            return rows

        def activate(self, editor, row, button):
            qml_call(editor, "activateConversationLink", row["href"], button, 28, 20)
            settle()

        def close(self):
            self.window.hide()
            shiboken6.delete(self.engine)
            self.temporary.cleanup()

    class RealQmlActions(unittest.TestCase):
        def setUp(self):
            self.h = Harness()
            self.addCleanup(self.h.close)

        def tearDown(self):
            self.assertEqual(self.h.warnings, [], "\n".join(self.h.warnings))

        def test_assistant_prose_inline_code_and_fenced_code(self):
            h = self.h
            h.backend.update(messageText="Open guide.txt and `guide.txt:12`; visit https://example.com/guide.\n\n```text\nguide.txt https://example.com/fenced\n```")
            anchors = h.anchors(h.prose())
            self.assertEqual([r["info"]["kind"] for r in anchors], ["path", "path", "url"])
            self.assertEqual(anchors[1]["info"]["line"], 12)
            self.assertEqual(anchors[1]["info"]["target"], str(h.workspace / "guide.txt"))
            self.assertTrue(all(r["underline"] for r in anchors))
            self.assertTrue(all(r["href"].startswith("umeko-conversation:") for r in anchors))
            code = h.find("codeBlock_1")
            self.assertEqual(h.anchors(code), [])
            self.assertEqual(h.document(code).toPlainText().strip(), "guide.txt https://example.com/fenced")

        def test_left_and_context_actions_use_recorders(self):
            h = self.h
            h.backend.update(messageText="Open guide.txt:12 or https://example.com/guide")
            editor = h.prose()
            path, url = h.anchors(editor)
            self.assertEqual(qml_call(h.window, "linkAtOffset", editor, path["position"] + 2), path["href"])
            selection = h.find("chatSelection")

            def route(row, button, moved=False, modifiers=0):
                point = qml_call(h.window, "selectionPoint", editor, row["position"] + 2)
                self.assertTrue(qml_call(selection, "rememberLink", point.x(), point.y()))
                selection.setProperty("pointerMoved", moved)
                activated = qml_call(selection, "activateLink", point.x(), point.y(), button, modifiers)
                settle()
                return activated

            self.assertFalse(route(path, 1, moved=True))
            self.assertFalse(route(path, 1, modifiers=Qt.ShiftModifier.value))
            self.assertEqual(h.backend.calls, [])
            self.assertTrue(route(path, 1))
            self.assertTrue(route(url, 1))
            self.assertEqual(h.backend.calls, [("path", str(h.workspace / "guide.txt"), False),
                                                ("url", "https://example.com/guide")])
            self.assertTrue(route(path, 2))
            menu = h.find("conversationLinkMenu", editor)
            self.assertTrue(menu.property("visible"))
            self.assertTrue(h.find("copyConversationPath", menu).property("visible"))
            self.assertFalse(h.find("copyConversationUrl", menu).property("visible"))
            QMetaObject.invokeMethod(h.find("copyConversationPath", menu), "triggered", Qt.DirectConnection)
            QMetaObject.invokeMethod(h.find("revealConversationPath", menu), "triggered", Qt.DirectConnection)
            self.assertEqual(h.backend.calls[-2:], [("copy", str(h.workspace / "guide.txt")),
                                                   ("path", str(h.workspace / "guide.txt"), True)])
            self.assertTrue(route(url, 2))
            self.assertFalse(h.find("copyConversationPath", menu).property("visible"))
            self.assertTrue(h.find("copyConversationUrl", menu).property("visible"))
            QMetaObject.invokeMethod(h.find("copyConversationUrl", menu), "triggered", Qt.DirectConnection)
            self.assertEqual(h.backend.calls[-1], ("copy", "https://example.com/guide"))

        def test_tool_detail_links_leave_plain_text_and_fences_intact(self):
            h = self.h
            result = "Created guide.txt:12\nhttps://example.com/guide\n```text\nguide.txt https://example.com/fenced\n```"
            h.backend.update(tools=[{"id": "tool-1", "name": "read", "state": "done", "arguments": {}, "result": result}])
            editor = h.find("toolDetail_tool-1")
            self.assertEqual(h.document(editor).toPlainText(), "{}\n\n" + result)
            anchors = h.anchors(editor)
            self.assertEqual([r["info"]["kind"] for r in anchors], ["path", "url"])
            self.assertEqual(anchors[0]["info"]["line"], 12)
            h.activate(editor, anchors[0], 1)
            self.assertEqual(h.backend.calls, [("path", str(h.workspace / "guide.txt"), False)])

        def test_restored_history_rechecks_missing_local_paths(self):
            h = self.h
            h.backend.update(messageText="guide.txt missing.txt https://example.com/guide")
            self.assertEqual([r["info"]["kind"] for r in h.anchors(h.prose())], ["path", "url"])
            (h.workspace / "guide.txt").unlink()
            h.backend.update(messageText="")
            h.backend.update(messageText="guide.txt missing.txt https://example.com/guide")
            anchors = h.anchors(h.prose())
            self.assertEqual([r["info"]["kind"] for r in anchors], ["url"])
            self.assertIn("guide.txt missing.txt", h.document(h.prose()).toPlainText())

        def test_streaming_completion_preserves_text_font_and_blocks(self):
            h = self.h
            h.backend.update(busy=True, messageText="Open guide.txt and `guide.txt:12` https://example.com/guide")
            editor = h.prose()
            document = h.document(editor)
            def appearance():
                fonts = []
                for position in range(document.characterCount() - 1):
                    cursor = QTextCursor(document)
                    cursor.setPosition(position)
                    cursor.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor)
                    font = cursor.charFormat().font()
                    fonts.append((font.families(), font.pointSizeF(), font.pixelSize(), font.weight(), font.italic()))
                return document.toPlainText(), document.blockCount(), fonts
            before = appearance()
            # Qt's Markdown importer may already expose native HTTP anchors.
            # Streaming suppresses the conversation decorator, preserving that
            # existing importer behavior and the original rendered document.
            streaming_anchors = h.anchors(editor)
            self.assertTrue(all(not row["info"] for row in streaming_anchors))
            self.assertFalse(any(row["href"].startswith("umeko-conversation:")
                                 for row in streaming_anchors))
            self.assertFalse(any(row["info"].get("kind") == "path"
                                 for row in streaming_anchors))
            h.backend.update(busy=False)
            self.assertEqual(len(h.anchors(editor)), 3)
            self.assertEqual(appearance(), before)

        def test_theme_updates_link_accent_without_font_size_change(self):
            h = self.h
            h.backend.update(messageText="guide.txt https://example.com/guide")
            editor = h.prose()
            font_before = editor.property("font").pixelSize()
            h.backend.update(themeStyle={"base": "dark", "colors": {"accent": "#d5a34c"}})
            self.assertEqual({r["color"] for r in h.anchors(editor)}, {"#d5a34c"})
            self.assertEqual(editor.property("font").pixelSize(), font_before)

        def test_selection_keeps_original_text_and_code_copy(self):
            h = self.h
            h.backend.update(messageText="guide.txt https://example.com/guide\n\n```text\nguide.txt\n```")
            editor = h.prose()
            plain = h.document(editor).toPlainText()
            selection = h.find("chatSelection")
            selection.setProperty("anchor", {"row": 0, "block": 0, "offset": 0})
            selection.setProperty("cursor", {"row": 0, "block": 0, "offset": len(plain)})
            qml_call(selection, "refresh")
            self.assertEqual(editor.property("selectedText"), plain)
            QMetaObject.invokeMethod(h.find("copyCode_1"), "clicked", Qt.DirectConnection)
            self.assertEqual(h.backend.calls[-1][0], "copy")
            self.assertEqual(h.backend.calls[-1][1].strip(), "guide.txt")

    class ControllerActions(unittest.TestCase):
        def test_routes_safe_text_to_viewer_and_other_items_to_existing_opener(self):
            from app.controller import Controller
            from app.document_preview import document_kind
            with tempfile.TemporaryDirectory(prefix="controller-links-") as temporary:
                workspace = Path(temporary)
                opened, documents, toasts = [], [], []
                fake = SimpleNamespace(documentRequested=SimpleNamespace(emit=lambda *args: documents.append(args)),
                                       toast=SimpleNamespace(emit=lambda *args: toasts.append(args)),
                                       openChatboxPath=lambda *args: opened.append(args))
                for filename in ("guide.txt", "notes.md", "sample.cpp"):
                    path = workspace / filename
                    path.write_text("fixture\n", encoding="utf-8")
                    Controller.openConversationPath(fake, str(path), False)
                    self.assertEqual(documents[-1], (str(path), filename, document_kind(path)))
                expected_documents = list(documents)
                for filename in ("run.cmd", "sample.py", "payload.exe", "image.png"):
                    path = workspace / filename
                    path.write_text("fixture\n", encoding="utf-8")
                    Controller.openConversationPath(fake, str(path), False)
                    self.assertEqual(opened[-1], (str(path), filename in ("run.cmd", "sample.py", "payload.exe")))
                folder = workspace / "folder"
                folder.mkdir()
                Controller.openConversationPath(fake, str(folder), False)
                self.assertEqual(opened[-1], (str(folder), False))
                bundle = workspace / "Demo.app"
                bundle.mkdir()
                Controller.openConversationPath(fake, str(bundle), False)
                self.assertEqual(opened[-1], (str(workspace), False))
                Controller.openConversationPath(fake, str(workspace / "guide.txt"), True)
                self.assertEqual(opened[-1], (str(workspace / "guide.txt"), True))
                self.assertEqual(documents, expected_documents)
                before_opened = list(opened)
                Controller.openConversationPath(fake, str(workspace / "missing.txt"), False)
                self.assertEqual(opened, before_opened)
                self.assertEqual(len(toasts), 1)

        def test_url_only_allows_web_and_never_uses_real_desktop_services(self):
            from app.controller import Controller
            with patch("app.controller.QDesktopServices.openUrl", return_value=True) as opener:
                fake = SimpleNamespace()
                Controller.openConversationUrl(fake, "https://example.com/guide")
                opener.assert_called_once()
                self.assertEqual(opener.call_args.args[0].toString(), "https://example.com/guide")
                for value in ("file:///tmp/run.exe", "javascript:alert(1)", "data:text/plain,hello"):
                    Controller.openConversationUrl(fake, value)
                self.assertEqual(opener.call_count, 1)

    suite = unittest.TestSuite((unittest.defaultTestLoader.loadTestsFromTestCase(RealQmlActions),
                               unittest.defaultTestLoader.loadTestsFromTestCase(ControllerActions)))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful() and screenshots:
        output = Path(screenshots).resolve()
        output.mkdir(parents=True, exist_ok=True)
        h = Harness()
        try:
            for language in ("zh", "en"):
                text = ("请打开 guide.txt，并查看 `guide.txt:12`。\n\n参考网址：https://example.com/guide" if language == "zh"
                        else "Open guide.txt, then review `guide.txt:12`.\n\nReference: https://example.com/guide")
                h.backend.update(language=language, messageText=text,
                                 tools=[{"id": "tool-1", "name": "read", "state": "done", "arguments": {},
                                         "result": "guide.txt:12\nhttps://example.com/guide"}])
                path = next(row for row in h.anchors(h.prose()) if row["info"]["kind"] == "path")
                h.activate(h.prose(), path, 2)
                if not h.find("conversationLinkMenu", h.prose()).property("visible"):
                    raise AssertionError("Screenshot requires the real path context menu")
                # Let the real menu's existing enter animation reach its endpoint.
                loop = QEventLoop()
                QTimer.singleShot(350, loop.quit)
                loop.exec()
                image = h.window.grabWindow()
                target = output / (language + "-conversation-links.png")
                if image.isNull() or not image.save(str(target)):
                    raise AssertionError("Cannot save screenshot: " + str(target))
                QMetaObject.invokeMethod(h.find("conversationLinkMenu", h.prose()), "close", Qt.DirectConnection)
        finally:
            h.close()
    return result.wasSuccessful()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--offscreen-child", action="store_true")
    parser.add_argument("--screenshots")
    arguments, remaining = parser.parse_known_args()
    if arguments.offscreen_child:
        raise SystemExit(0 if offscreen_suite(arguments.screenshots) else 1)
    if arguments.screenshots:
        os.environ["UMEKO_CONVERSATION_SCREENSHOTS"] = str(Path(arguments.screenshots).resolve())
    unittest.main(argv=[sys.argv[0], *remaining])
