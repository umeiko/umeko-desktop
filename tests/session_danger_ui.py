"""Real full-window QML checks with synthetic approval events, no agent process."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
language = sys.argv[1]
os.environ.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", QT_QUICK_CONTROLS_STYLE="Basic", UMEKO_LANGUAGE=language)
temporary = tempfile.TemporaryDirectory(prefix="umeko-danger-ui-")
base = Path(temporary.name)
os.environ["UMEKO_DATA_DIR"] = str(base / "profile")

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, QUrl
from PySide6.QtGui import QFont, QFontDatabase, QKeyEvent
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app.controller import Controller
from app.storage import Store
from app.syntax_highlight import register_text_types
from app.terminal_view import register_terminal_types

app = QApplication([])
if os.name == "nt":
    for font in ("msyh.ttc", "segoeui.ttf", "consola.ttf"):
        QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / font))
app.setFont(QFont("Microsoft YaHei UI", 10) if os.name == "nt" else QFontDatabase.systemFont(QFontDatabase.GeneralFont))
store = Store()
store.data["ui"].update(language=language, fontScale=1.0, sidebarWidth=280)
store.data.update(selectedProvider="test", selectedModel="test-model", providers=[{
    "id": "test", "name": "Test", "api": "openai", "baseUrl": "", "key": "",
    "models": [{"alias": "test-model", "upstream": "test-model"}]}])
store.data["agent"]["agentDir"] = str(base / "agent")
store.save()
register_text_types()
register_terminal_types()
with patch("app.provider_plugins.BundledProviders.sync", return_value=[]), \
        patch("app.desktop_plugins.DesktopPlugins.start", lambda *args, **kwargs: None), \
        patch.object(Controller, "_command_pi", lambda *args, **kwargs: False), \
        patch("app.controller.LocalServer") as server:
    server.return_value.port = 0
    backend = Controller(ROOT)
    backend._pool.write = Mock()
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(ROOT / "app/qml/Main.qml")))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    window.resize(1440, 960)

    def find(name):
        # Popup content is reparented into the overlay and is found visually.
        stack = [window.contentItem()]
        while stack:
            item = stack.pop()
            if item.objectName() == name:
                return item
            stack.extend(item.childItems())
        return window.findChild(QObject, name)

    def settle(check):
        for _ in range(200):
            app.processEvents()
            if check():
                return
            QTest.qWait(10)
        raise AssertionError("UI state did not arrive: " + repr(warnings))

    def evaluate(obj, code):
        expression = QQmlExpression(engine.rootContext(), obj, code)
        value = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        return value

    def capture(name):
        target = os.environ.get("UMEKO_DANGER_CAPTURE_DIR")
        if target:
            output = Path(target)
            output.mkdir(parents=True, exist_ok=True)
            QTest.qWait(400)  # Capture a settled frame; no assertion depends on animation.
            app.processEvents()
            assert window.grabWindow().save(str(output / f"{language}-{name}.png"))

    def approval(category=1):
        backend._handle_pi_event(backend._view, {"type": "ui_request", "id": "demo-approval", "method": "confirm",
            "dangerCategory": category, "title": "批准工具操作" if language == "zh" else "Approve tool operation",
            "detail": ("原因：递归删除的目标是 Umeko 数据。\n\n原始命令：\nrm -rf ~/.umeko" if language == "zh" else
                       "Reason: Recursive deletion targets Umeko data.\n\nOriginal command:\nrm -rf ~/.umeko")})
        settle(lambda: find("denyToolButton") is not None and find("denyToolButton").hasActiveFocus())

    try:
        record = backend._view
        record.id, record.title = "danger-demo", "会话授权" if language == "zh" else "Chat approvals"
        record.messages = [{"role": "user", "text": "清理项目中的旧数据。" if language == "zh" else "Clean up old project data."},
                           {"role": "assistant", "text": "此操作需要确认。" if language == "zh" else "This operation needs approval."}]
        backend._index_record(record)
        backend.changed.emit()
        backend.chatChanged.emit()
        approval()
        button = find("grantDangerousToolButton")
        assert button.isVisible() and not button.hasActiveFocus()
        assert button.property("text") == ("确认，并且本会话不再询问危险操作" if language == "zh" else
                                           "Confirm and don't ask again for dangerous operations in this chat")
        label = button.property("contentItem")
        assert label.property("paintedWidth") <= label.width() + 1
        assert label.property("paintedHeight") <= label.height() + 1
        capture("dialog")
        # Deliver Qt events only inside this offscreen window, never OS input.
        for key in (Qt.Key_Return, Qt.Key_Enter):
            target = window.activeFocusItem()
            QCoreApplication.sendEvent(target, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))
            QCoreApplication.sendEvent(target, QKeyEvent(QEvent.KeyRelease, key, Qt.NoModifier))
            assert not backend.dangerousAllowed
            if not backend.pendingApproval:
                approval()
        button.forceActiveFocus()
        QCoreApplication.sendEvent(button, QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))
        QCoreApplication.sendEvent(button, QKeyEvent(QEvent.KeyRelease, Qt.Key_Return, Qt.NoModifier))
        assert not backend.dangerousAllowed
        button.clicked.emit()
        settle(lambda: backend.dangerousAllowed and not backend.pendingApproval)
        assert find("composerPermissionStatus") is None
        assert find("composerPermissionMenu") is None
        capture("grants")
        backend.revokeDangerousApproval()
        settle(lambda: not backend.dangerousAllowed)
        # Removing the composer controls must not alter chat-scoped grants.
        backend.store.data["sessionMeta"][record.id]["dangerousAllowed"] = True
        backend._sync_dangerous_approval(record)
        backend.newSession()
        assert not backend.dangerousAllowed
        backend.openSession(record.id)
        assert backend.dangerousAllowed
        assert find("composerPermissionStatus") is None
        backend.revokeDangerousApproval()
        assert not backend.dangerousAllowed
        relevant = [warning for warning in warnings if "dangerous" in warning.lower() or "Composer.qml" in warning or "ApprovalDialog.qml" in warning]
        assert not relevant, relevant
        print(f"SESSION_DANGER_UI_OK {language}: safe focus, Enter, explicit grant, no composer permission controls, revoke, chat switch", flush=True)
    finally:
        backend.close()
        import shiboken6
        shiboken6.delete(engine)
        app.processEvents()
        temporary.cleanup()
