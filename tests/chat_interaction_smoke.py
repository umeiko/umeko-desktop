"""Real QML pointer tests, including pixel movement and cross-document selection."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('UMEKO_LANGUAGE','zh')
os.environ["UMEKO_DATA_DIR"] = str(Path(tempfile.mkdtemp(prefix="umeko-interaction-")).resolve())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
from PySide6.QtCore import QPoint, QPointF, Qt, QMetaObject, QEvent, QTimer
from PySide6.QtGui import QWheelEvent, QKeyEvent, QMouseEvent
from PySide6.QtTest import QTest
from main import create_application

app, engine, backend = create_application()
backend.store.data.update(selectedProvider='fixture', selectedModel='fixture', providers=[{'id':'fixture','name':'Fixture','api':'openai','baseUrl':'http://127.0.0.1:1/v1','models':[{'upstream':'fixture','alias':'fixture'}]}])
backend._view.provider = 'fixture'
backend._view.model = 'fixture'
backend.changed.emit()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))


def find(name):
    stack = [window.contentItem()]
    while stack:
        item = stack.pop()
        if item.objectName() == name:
            return item
        stack.extend(item.childItems())
    raise AssertionError(name)


def point(item, x=2, y=4):
    return item.mapToScene(QPointF(x, y)).toPoint()


def wheel(delta=120, pixels=0):
    pos = view.mapToScene(QPointF(view.width() / 2, view.height() / 2))
    event = QWheelEvent(pos, QPointF(window.mapToGlobal(pos.toPoint())), QPoint(0, pixels), QPoint(0, delta), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    app.sendEvent(window, event)


def shortcut(key):
    app.sendEvent(window, QKeyEvent(QEvent.KeyPress, key, Qt.ControlModifier))
    app.sendEvent(window, QKeyEvent(QEvent.KeyRelease, key, Qt.ControlModifier))


def mouse(kind, pos):
    button = Qt.NoButton if kind == QEvent.MouseMove else Qt.LeftButton
    buttons = Qt.NoButton if kind == QEvent.MouseButtonRelease else Qt.LeftButton
    app.sendEvent(window, QMouseEvent(kind, QPointF(pos), QPointF(window.mapToGlobal(pos)), button, buttons, Qt.NoModifier))


def scenario():
    global view
    workspace = Path(os.environ["UMEKO_DATA_DIR"]) / "workspace"
    workspace.mkdir()
    backend._view.workspace = str(workspace)
    backend._view.messages = [
        {"role": "user", "text": "First request", "error": False},
        {"role": "assistant", "text": "SELECT_START alpha 中文𠮷\n\n```python\ncode_01 = 1\ncode_02 = 2\n```\n\nSELECT_END omega", "error": False},
        {"role": "user", "text": "NEXT_USER marker", "error": False},
    ] + [{"role": "user" if i % 2 else "assistant", "text": f"History {i}: " + "A long selectable line of text.\n" * 8, "error": False} for i in range(30)]
    backend.chatChanged.emit(); backend.transcriptChanged.emit()
    yield 250
    view = find("conversation")
    selection = find("chatSelection")
    QMetaObject.invokeMethod(view, "positionViewAtEnd")
    yield 100
    before = view.property("contentY")
    wheel()
    yield 80
    assert view.property("contentY") <= before - 50, "ordinary wheel did not move history"
    before = view.property("contentY")
    wheel(0, 19)
    yield 80
    assert view.property("contentY") <= before - 15, "touchpad pixel wheel did not move history"
    wheel(-120)
    yield 80
    assert view.property("contentY") > before - 19, "downward wheel did not move history"
    QMetaObject.invokeMethod(view, "beginBrowsing")
    QMetaObject.invokeMethod(view, "positionViewAtBeginning")
    yield 100
    start = find("selectText_1_0")
    end = find("selectText_2_0")
    mouse(QEvent.MouseButtonPress, point(start))
    mouse(QEvent.MouseMove, point(end, end.width() - 2, 8))
    mouse(QEvent.MouseButtonRelease, point(end, end.width() - 2, 8))
    shortcut(Qt.Key_C)
    yield 100
    copied = app.clipboard().text()
    for marker in ("SELECT_START", "中文𠮷", "code_01 = 1", "code_02 = 2", "SELECT_END omega", "NEXT_USER marker"):
        assert marker in copied, (marker, copied)
    # The drag starts in one delegate; the fixed overlay keeps its grab when that
    # delegate is virtualized away and the pointer remains near either viewport edge.
    before = view.property("contentY")
    mouse(QEvent.MouseButtonPress, point(start))
    edge = view.mapToScene(QPointF(180, view.height() - 5)).toPoint()
    mouse(QEvent.MouseMove, edge)
    yield 650
    assert selection.property("dragging")
    assert view.property("contentY") > before + 60, ("selection did not autoscroll down", before, view.property("contentY"), selection.property("pointer"), warnings)
    continuing = view.property("contentY")
    yield 650
    assert view.property("contentY") > continuing + 40, "selection autoscroll stopped while held still"
    edge = view.mapToScene(QPointF(180, view.height() + 20)).toPoint()
    mouse(QEvent.MouseMove, edge)
    yield 150
    lower = view.property("contentY")
    edge = view.mapToScene(QPointF(180, -20)).toPoint()
    mouse(QEvent.MouseMove, edge)
    yield 350
    assert view.property("contentY") < lower - 40, "selection did not autoscroll up"
    mouse(QEvent.MouseButtonRelease, edge)
    stopped = view.property("contentY")
    yield 100
    assert abs(view.property("contentY") - stopped) < 2, "selection kept scrolling after release"
    shortcut(Qt.Key_A)
    shortcut(Qt.Key_C)
    yield 100
    assert "History 29:" in app.clipboard().text(), "copy lost virtualized history"
    QMetaObject.invokeMethod(selection, "clear")
    with patch("app.controller.QDesktopServices.openUrl", return_value=True) as opened:
        button = find("openChatDirectoryButton")
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point(button, 15, 15))
        assert Path(opened.call_args.args[0].toLocalFile()) == workspace
        assert backend._view.workspace == str(workspace)
    backend.setTheme("yanami")
    watermark = find("yanamiWatermark")
    assert watermark.width() >= view.width() and watermark.height() >= view.height()
    assert watermark.property("opacity") < 0.1
    out = ROOT / "artifacts/screenshots"
    out.mkdir(parents=True, exist_ok=True)
    window.grabWindow().save(str(out / "32-selection-and-watermark.png"))
    backend._view.messages = [
        {"role": "user", "text": "Inspect and update files", "error": False},
        {"role": "assistant", "text": "Inspecting first file", "tools": [{"id": "one", "name": "read", "path": str(workspace / "first.py"), "state": "done", "arguments": {"path": "first.py"}}]},
        {"role": "assistant", "text": "Updating second file", "tools": [{"id": "two", "name": "write", "path": str(workspace / "second.py"), "state": "done", "arguments": {"path": "second.py"}}]},
        {"role": "assistant", "text": "Checking the result", "tools": [{"id": "three", "name": "bash", "state": "done", "arguments": {"command": "test"}, "result": "passed"}]},
        {"role": "assistant", "text": "The files have been updated.", "error": False},
    ]
    backend.chatChanged.emit(); backend.transcriptChanged.emit(); backend.viewChanged.emit()
    yield 150
    assert view.property("count") == 2, "consecutive tool calls created separate assistant rows"
    window.grabWindow().save(str(out / "33-tool-group-collapsed.png"))
    toggle = find("toggleTools_1_30000")
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point(toggle, 15, 10))
    yield 80
    file = find("toolPath_two")
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point(file, 15, 8))
    assert app.clipboard().text() == str(workspace / "second.py")
    window.grabWindow().save(str(out / "34-tool-group-expanded.png"))
    backend.setTheme("light")
    window.resize(1160, 1000)
    backend._view.messages = [
        {"role": "user", "text": "检查项目，修正问题并验证结果。", "error": False},
        {"role": "assistant", "text": "先运行检查，确认需要修正的位置：", "tools": [
            {"id": "check-a", "name": "bash", "arguments": {"command": "python check_project.py --fixtures local"}, "state": "error", "result": "CHECK_FAILURE_DETAIL: fixture mismatch"},
            {"id": "check-b", "name": "bash", "arguments": {"command": "git diff --check"}, "state": "done", "result": "No whitespace errors"}]},
        {"role": "assistant", "thinking": "THINKING_VISIBLE: Compare the local fixtures, then verify the changed fields. Keep the successful checks intact.", "text": "找到一处配置差异，修正后重新验证：", "tools": [
            {"id": "edit-config", "name": "edit", "path": str(workspace / "config.py"), "arguments": {"path": "config.py"}, "state": "running"}]},
        {"role": "assistant", "text": "检查完成，修改后的内容如下。\n\n```python\nverified = True\n```", "error": False},
    ]
    backend.chatChanged.emit(); backend.transcriptChanged.emit(); backend.viewChanged.emit()
    yield 150
    assert view.property("count") == 2
    batch = find("toggleTools_1_10000")
    assert batch.parentItem().parentItem().property("summary") == "运行了 2 条命令（1 失败）"
    thinking = find("toggleThinking_1_20000")
    assert not thinking.parentItem().parentItem().property("expanded")
    window.grabWindow().save(str(out / "35-process-collapsed.png"))
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point(batch, 15, 10))
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point(thinking, 40, 10))
    yield 80
    detail = find("toggleToolDetail_check-a")
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point(detail, 180, 10))
    yield 80
    assert find("toolDetail_check-a").isVisible()
    assert find("thinkingText_1_20000").isVisible()
    window.grabWindow().save(str(out / "36-process-expanded.png"))
    # Data changes must keep both batch expansion and individual result folds.
    backend._view.messages[1]["tools"][0]["result"] += "\nMore streamed output."
    backend._view.messages[2]["tools"][0]["state"] = "done"
    backend._view.messages[-1]["text"] += "\n\nSTREAMED_FINAL_MARKER"
    backend.chatChanged.emit(); backend.transcriptChanged.emit()
    yield 100
    assert find("toolDetail_check-a").isVisible(), "streaming collapsed tool details"
    assert find("thinkingText_1_20000").isVisible(), "streaming collapsed reasoning"
    assert "More streamed output" in find("toolDetail_check-a").property("text")
    backend._view.messages[1]["tools"].append({"id": "check-c", "name": "bash", "arguments": {"command": "python verify.py"}, "state": "running"})
    backend.chatChanged.emit(); backend.transcriptChanged.emit()
    yield 60
    assert find("toolDetail_check-a").isVisible(), "adding a tool collapsed an existing result"
    backend._view.messages.append({"role": "assistant", "thinking": "Next verification step", "text": "继续验证下一项。"})
    backend.chatChanged.emit(); backend.transcriptChanged.emit()
    yield 60
    assert find("toolDetail_check-a").isVisible(), "adding a process step collapsed existing results"
    assert find("thinkingText_1_20000").isVisible(), "adding a process step collapsed existing reasoning"
    selection.forceActiveFocus()
    shortcut(Qt.Key_A); shortcut(Qt.Key_C)
    yield 50
    copied = app.clipboard().text()
    assert copied.index("CHECK_FAILURE_DETAIL") < copied.index("THINKING_VISIBLE") < copied.index("找到一处配置差异") < copied.index("STREAMED_FINAL_MARKER"), copied
    QMetaObject.invokeMethod(selection, "clear")
    batch = find("toggleTools_1_10000")
    thinking = find("toggleThinking_1_20000")
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point(batch, 15, 10))
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point(thinking, 40, 10))
    yield 80
    selection.forceActiveFocus()
    shortcut(Qt.Key_A); shortcut(Qt.Key_C)
    yield 50
    copied = app.clipboard().text()
    assert "CHECK_FAILURE_DETAIL" not in copied and "THINKING_VISIBLE" not in copied, "collapsed details leaked into visible-text copy"
    assert "先运行检查" in copied and "找到一处配置差异" in copied and "verified = True" in copied
    QMetaObject.invokeMethod(selection, "clear")
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point(thinking, 40, 10))
    yield 40
    assert find("thinkingText_1_20000").isVisible()
    backend.viewChanged.emit()
    yield 40
    assert not find("thinkingText_1_20000").isVisible(), "a different conversation inherited expanded reasoning"
    indicator = find("contextUsageIndicator")
    assert not indicator.property("known")
    usage = {"model": backend._view.model, "tokens": 33000, "contextWindow": 128000, "percent": 25.78125}
    backend._handle_pi_event(backend._view, {"type": "context_usage", "usage": usage})
    yield 50
    assert indicator.property("known") and abs(indicator.property("fraction") - 0.2578125) < 0.001
    assert "25.8%" in indicator.property("description")
    assert "Pi" not in indicator.property("description") and indicator.property("description").count("\n") == 1
    QTest.mouseMove(window, point(indicator, 12, 15))
    yield 400
    tooltip = window.findChild(type(indicator), "contextUsageTooltip")
    # Popup is a QObject rather than a QQuickItem on some Qt releases.
    if tooltip is None:
        from PySide6.QtCore import QObject
        tooltip = window.findChild(QObject, "contextUsageTooltip")
    assert tooltip and tooltip.property("visible"), "context usage tooltip did not open"
    window.grabWindow().save(str(out / "37-context-usage.png"))
    QTest.mouseMove(window, QPoint(250, 70))
    yield 120
    assert not tooltip.property("visible"), "context usage tooltip stayed open after leaving"
    backend._handle_pi_event(backend._view, {"type": "context_usage", "usage": {**usage, "tokens": None, "percent": None}})
    yield 50
    assert not indicator.property("known") and "待更新" in indicator.property("description")
    backend._handle_pi_event(backend._view, {"type": "context_usage", "usage": {**usage, "tokens": 140800, "percent": 110}})
    yield 50
    assert indicator.property("fraction") == 1, "context ring exceeded one revolution"
    backend.store.data["selectedModel"] = "new-model-alias"
    backend.changed.emit()
    yield 40
    assert not indicator.property("known"), "edited model mapping retained another model's usage"
    backend.selectModel(backend._view.provider, backend._view.model)
    backend.newSession()
    yield 50
    assert not indicator.property("known"), "new conversation inherited context usage"
    from PySide6.QtCore import QObject
    from app.syntax_highlight import tokenize as real_tokenize, Tokens, MAX_CHARS
    code = 'def greet(name):\n    label = "中文𠮷 <tag> & value"\n    return f"Hello, {name}!"  # Keep the original text\n'
    backend._view.messages = [
        {"role": "user", "text": "给我一个带中文输出的 Python 示例。", "error": False},
        {"role": "assistant", "text": "下面是示例：\n\n```python\n" + code + "```", "error": False},
    ]
    backend.chatChanged.emit(); backend.transcriptChanged.emit(); backend.viewChanged.emit()
    yield 650
    bubble = find("messageBubble_0")
    assert bubble.x() > 0 and abs(bubble.x() + bubble.width() - bubble.parentItem().width()) < 1
    assert bubble.width() <= bubble.parentItem().width() * 0.82 + 1
    assert not find("selectText_0_-100000").isVisible(), "user avatar/name row remains visible"
    syntax = find("codeBlock_1").property("syntaxColors")
    assert syntax and syntax.property("status") == "highlighted", ("syntax colors unavailable", syntax.property("status") if syntax else None)
    document = syntax.property("document").textDocument()
    assert document.toPlainText() == code.rstrip("\n")
    assert len(document.begin().layout().formats()) > 1, "native syntax color ranges missing"
    mascot = find("replyEndMascot_1")
    assert mascot.isVisible() and mascot.property("loaded"), "closing mascot did not load"
    assert mascot.width() == 56 and mascot.height() == 56 and not mascot.property("smooth")
    assert not find("replyEndMascot_0").isVisible(), "user message inherited the closing mascot"
    reply_bubble = find("messageBubble_1")
    assert mascot.x() == reply_bubble.x() and 34 <= mascot.y() - reply_bubble.y() - reply_bubble.height() <= 42
    backend._view.phase = "running"
    backend.chatChanged.emit()
    yield 40
    assert not mascot.isVisible(), "closing mascot appeared before generation ended"
    backend._view.phase = "idle"
    backend.chatChanged.emit()
    yield 80
    assert mascot.isVisible(), "closing mascot did not return on completion"
    window.grabWindow().save(str(out / "42-pixel-reply-mascot.png"))
    window.grabWindow().save(str(out / "38-user-bubble-and-syntax.png"))
    copy = find("copyCode_1")
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point(copy, 20, 12))
    assert app.clipboard().text() == code.rstrip("\n"), "syntax colors changed copied code"
    selection.forceActiveFocus(); shortcut(Qt.Key_A); shortcut(Qt.Key_C)
    yield 50
    assert app.clipboard().text().startswith("给我一个") and "中文𠮷 <tag> & value" in app.clipboard().text()
    QMetaObject.invokeMethod(selection, "clear")
    with patch("app.syntax_highlight.tokenize", wraps=real_tokenize) as lexed:
        backend._view.messages[1]["text"] = "继续补充说明：\n\n```python\n" + code + "```"
        backend.chatChanged.emit(); backend.transcriptChanged.emit()
        yield 250
        assert find("codeBlock_1").property("syntaxColors") is syntax, "prose streaming recreated the code highlighter"
        assert lexed.call_count == 0, "unchanged code was tokenized again"
        before_formats = document.begin().layout().formats()
        old_color = before_formats[0].format.foreground().color().name()
        backend.setDark(True)
        yield 150
        after_formats = document.begin().layout().formats()
        assert after_formats[0].format.foreground().color().name() != old_color
        assert lexed.call_count == 0, "theme switch re-tokenized code"
        window.grabWindow().save(str(out / "39-syntax-dark.png"))
        backend.setDark(False)
        for number in range(6):
            backend._view.messages[1]["text"] = "流式示例：\n\n```python\nvalue = " + str(number) + "\n```"
            backend.chatChanged.emit(); backend.transcriptChanged.emit()
            yield 35
        syntax.accept(syntax._generation - 1, Tokens({}))
        yield 450
        assert lexed.call_count == 1, ("code stream was not debounced", lexed.call_count)
        assert syntax.property("status") == "highlighted" and document.toPlainText() == "value = 5"
        big_code = "x = 1; " * (MAX_CHARS // 7 + 1)
        backend._view.messages[1]["text"] = "超大代码保持纯文本：\n\n```python\n" + big_code + "\n```"
        backend.chatChanged.emit(); backend.transcriptChanged.emit()
        yield 400
        assert syntax.property("status") == "plain" and document.toPlainText() == big_code
        assert lexed.call_count == 1, "oversized code reached the lexer"
    assert not warnings, "\n".join(warnings)
    print("Chat interactions passed: scrolling/selection, process folds, context ring, right-aligned user bubbles, native code colors, Unicode copy, stable streaming documents, debounce, cached theme colors and large-block fallback.")

steps = scenario()
failed = []
def advance():
    try:
        QTimer.singleShot(next(steps), advance)
    except StopIteration:
        app.quit()
    except BaseException:
        import traceback
        failed.append(traceback.format_exc())
        app.quit()
QTimer.singleShot(0, advance)
app.exec()
backend.close()
import shiboken6
shiboken6.delete(engine)
if failed:
    raise AssertionError(failed[0])
