"""Full-window QML checks for readable approvals, the dsh stop line and dsh settings states.

Synthetic events only: no agent process, model or network. Set UMEKO_DSH_UI_CAPTURE_DIR to save PNGs.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
language = sys.argv[1] if len(sys.argv) > 1 else "zh"
theme = sys.argv[2] if len(sys.argv) > 2 else "white"
os.environ.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", QT_QUICK_CONTROLS_STYLE="Basic", UMEKO_LANGUAGE=language)
temporary = tempfile.TemporaryDirectory(prefix="umeko-dsh-approval-ui-")
base = Path(temporary.name)
os.environ["UMEKO_DATA_DIR"] = str(base / "profile")
os.environ["PI_CODING_AGENT_DIR"] = str(base / "agent")

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app.controller import Controller
from app.storage import Store
from app.syntax_highlight import register_text_types
from app.terminal_view import register_terminal_types

zh = language == "zh"
app = QApplication([])
if os.name == "nt":
    for font in ("msyh.ttc", "segoeui.ttf", "consola.ttf"):
        QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / font))
app.setFont(QFont("Microsoft YaHei UI", 10) if os.name == "nt" else QFontDatabase.systemFont(QFontDatabase.GeneralFont))
store = Store()
store.data["ui"].update(language=language, fontScale=1.0, sidebarWidth=244)
store.data.update(theme=theme, dark=theme == "dark", selectedProvider="test", selectedModel="test-model", providers=[{
    "id": "test", "name": "Test provider", "api": "openai", "baseUrl": "", "key": "",
    "models": [{"alias": "test-model", "upstream": "test-model"}]}])
store.data["agent"]["agentDir"] = str(base / "agent")
store.save()
register_text_types()
register_terminal_types()

with patch("app.provider_plugins.BundledProviders.sync", return_value=[]), \
        patch("app.desktop_plugins.DesktopPlugins.start", lambda *args, **kwargs: None), \
        patch.object(Controller, "_command_pi", lambda *args, **kwargs: False), \
        patch.object(Controller, "_command_dsh", lambda *args, **kwargs: True), \
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
    window.resize(1280, 900)

    def find(name):
        # Popup content is reparented into the overlay and is found visually.
        stack = [window.contentItem()]
        while stack:
            item = stack.pop()
            if item.objectName() == name:
                return item
            stack.extend(item.childItems())
        return window.findChild(QObject, name)

    def settle(check, label):
        for _ in range(200):
            app.processEvents()
            if check():
                return
            QTest.qWait(10)
        raise AssertionError(label + ": " + repr(warnings))

    def visible(name):
        item = find(name)
        return item is not None and item.isVisible()

    def capture(name):
        target = os.environ.get("UMEKO_DSH_UI_CAPTURE_DIR")
        if target:
            QTest.qWait(400)  # Settled frame only; no assertion depends on animation.
            app.processEvents()
            assert window.grabWindow().save(str(Path(target) / f"{name}-{theme}-{language}.png"))

    def chat(record, messages):
        record.messages = messages
        record.body_dirty = True
        backend._index_record(record)
        backend.changed.emit()
        backend.chatChanged.emit()

    def dsh_request(identifier, title, raw):
        detail = "\n".join([title, json.dumps(raw, ensure_ascii=False, separators=(",", ":"))])
        backend._handle_pi_event(record, {"type": "ui_request", "backend": "dsh", "id": identifier, "method": "confirm",
            "title": "DeepSeek Harness 请求授权", "message": detail, "detail": detail, "toolTitle": title, "toolKind": "",
            "rawInput": raw, "toolContent": "", "options": []})
        settle(lambda: visible("approvalDetailsScroll"), "dsh approval")

    def close_approval():
        backend.respondApproval(False)
        settle(lambda: not backend.pendingApproval, "approval closed")

    try:
        record = backend._view
        record.id, record.title, record.workspace, record.backend = "dsh-approval-ui", "notes", str(base), "dsh"
        chat(record, [{"role": "user", "text": "把便笺写到上级目录。", "error": False},
                      {"role": "assistant", "text": "需要授权。", "error": False}])
        shell = {"command": "Set-Content ../notes.txt -Value 'x'", "description": "Write text to ../notes.txt",
                 "justification": "../notes.txt is outside the workspace.", "sandbox_permissions": "danger-full-access"}
        dsh_request("shell", "pwsh", shell)
        assert find("approvalAction").property("text") == ("运行命令" if zh else "Run a command")
        assert find("approvalDescription").property("text") == shell["description"]
        assert find("approvalSectionText_0").property("text") == shell["command"]
        assert find("approvalSectionText_1").property("text") == shell["justification"]
        assert find("approvalPermissionText").property("text") == (
            "需要完全访问权限（超出当前工作目录）" if zh else "Needs full access (beyond the current working directory)")
        assert not visible("approvalRawText")
        assert find("denyToolButton").property("text") == ("本次拒绝" if zh else "Reject once")
        assert find("allowToolButton").property("text") == ("本次允许" if zh else "Allow once")
        dialog = find("toolApproval")
        assert dialog.property("height") < 490, dialog.property("height")
        capture("approval-dsh-shell")
        find("approvalRawToggle").clicked.emit()
        settle(lambda: visible("approvalRawText"), "raw arguments")
        assert '"sandbox_permissions":"danger-full-access"' in find("approvalRawText").property("text")
        capture("approval-dsh-shell-raw")
        close_approval()
        dsh_request("write", "write", {"file_path": "../out/summary.txt", "content": "今天整理笔记。\n",
                                        "justification": "Outside the workspace.", "sandbox_permissions": "danger-full-access"})
        assert not visible("approvalRawText"), "raw arguments must start collapsed for each request"
        assert find("approvalAction").property("text") == ("写入文件" if zh else "Write a file")
        assert find("approvalSectionText_0").property("text") == "../out/summary.txt"
        assert find("approvalSectionText_1").property("text") == "今天整理笔记。\n"
        capture("approval-dsh-write")
        close_approval()

        # Pi uses the same dialog: tool approvals gain sections, other confirms keep the raw text box.
        record.backend = "pi"
        reason, command = ("递归删除的目标是 Umeko 数据。", "rm -rf ~/.umeko") if zh else ("Recursive deletion targets Umeko data.", "rm -rf ~/.umeko")
        backend._handle_pi_event(record, {"type": "ui_request", "id": "pi", "method": "confirm", "dangerCategory": 1,
            "title": "批准工具操作" if zh else "Approve tool operation",
            "detail": f"原因：{reason}\n\n原始命令：\n{command}" if zh else f"Reason: {reason}\n\nOriginal command:\n{command}"})
        settle(lambda: visible("approvalDetailsScroll") and find("denyToolButton").hasActiveFocus(), "pi approval")
        assert find("approvalSectionText_0").property("text") == reason
        assert find("approvalSectionText_1").property("text") == command
        assert not visible("approvalRawToggle") and not visible("approvalPermission")
        assert find("denyToolButton").property("text") == ("拒绝" if zh else "Deny")
        assert visible("grantDangerousToolButton")
        capture("approval-pi")
        close_approval()
        backend._handle_pi_event(record, {"type": "ui_request", "id": "pi-other", "method": "confirm",
                                          "title": "Extension", "detail": "Read the clipboard?"})
        settle(lambda: find("denyToolButton").hasActiveFocus(), "pi generic confirm")
        assert not visible("approvalDetailsScroll")
        capture("approval-pi-generic")
        close_approval()
        record.backend = "dsh"

        # Old saved items hold the full model instruction; both render as the short status.
        chat(record, [{"role": "user", "text": "运行一个长命令。", "error": False},
                      {"role": "status", "customType": "umeko-dsh-interruption", "text": "已停止上一条请求", "error": False},
                      {"role": "user", "text": "3+4？", "error": False},
                      {"role": "assistant", "text": "7", "error": False, "stopReason": "stop"},
                      {"role": "status", "customType": "umeko-dsh-interruption", "error": False,
                       "text": "[用户已停止上一条请求；请只处理新消息，除非用户明确要求继续。]"},
                      {"role": "user", "text": "下一题。", "error": False}])
        short = "已停止上一条请求" if zh else "Stopped the previous request"
        settle(lambda: visible("dshInterruptionNotice_1") and visible("dshInterruptionNotice_4"), "stop lines")
        assert find("dshInterruptionNotice_1").property("text") == short
        assert find("dshInterruptionNotice_4").property("text") == short
        capture("stop-line")

        window.setProperty("settingsTab", 3)
        window.setProperty("page", "settings")
        settle(lambda: visible("openDshSettingsButton"), "agent settings")
        capture("settings-agent")
        find("openDshSettingsButton").clicked.emit()
        settle(lambda: visible("dshSettings"), "dsh settings")
        runtime = backend.dshRuntime
        palette = {}
        for name, ready, failed, status, version in (
                ("ready", True, False, "dsh 可用", "0.2.2"),
                ("missing", False, True, "未找到 dsh", ""),
                ("download-failed", False, True, "dsh 下载失败", "")):
            runtime._ready, runtime._failed, runtime._status, runtime._version = ready, failed, status, version
            runtime._hint, runtime._resolved_path = "原有安装已保留。", "C:/dsh/lib/bin.js" if ready else ""
            runtime.changed.emit()
            app.processEvents()
            label = find("dshRuntimeStatus")
            palette[name] = label.property("color").name()
            assert label.property("text") == (status if zh else {"dsh 可用": "dsh is ready", "未找到 dsh": "dsh not found",
                                                                  "dsh 下载失败": "dsh download failed"}[status])
            assert visible("downloadDshRuntimeButton") is not ready
            assert find("dshRuntimeVersion").property("text") == ("v" + version if version else "")
            capture("settings-dsh-" + name)
        assert palette["ready"] != palette["missing"] and palette["missing"] == palette["download-failed"], palette
        relevant = [warning for warning in warnings if any(name in warning for name in
                    ("ApprovalDialog", "ApprovalDetails", "approval-view", "DshSettings", "DshRuntimeStatus", "ConversationPane", "AgentPage"))]
        assert not relevant, relevant
        print(f"DSH_APPROVAL_UI_OK {language} {theme}", flush=True)
    finally:
        backend.close()
        import shiboken6
        shiboken6.delete(engine)
        app.processEvents()
        temporary.cleanup()
