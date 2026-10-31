"""Offscreen appearance controls and real chat layout; no model, PTY or input injection."""
import os
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Honor the caller's test sandbox, including Windows paths outside the checkout.
temp_root = os.environ.get("TMP") or os.environ.get("TEMP")
if temp_root:
    Path(temp_root).mkdir(parents=True, exist_ok=True)
sandbox = tempfile.TemporaryDirectory(prefix="umeko-appearance-", dir=temp_root)
os.environ["UMEKO_DATA_DIR"] = str(Path(sandbox.name) / "profile")
os.environ["UMEKO_LANGUAGE"] = "zh"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import Q_ARG, QMetaObject, QObject, QPointF, Qt, Signal, Slot
from PySide6.QtGui import QTextBlockFormat, QTextTable
from PySide6.QtTest import QTest
from app.storage import Store
from app.terminal_view import TerminalView
from main import create_application

seed = Store()
seed.data["agent"]["agentDir"] = str(Path(sandbox.name) / "agent")
seed.save()


class QuietTray(QObject):
    """Keep application's Qt signal connections without constructing a native tray."""
    quitRequested = Signal()
    notificationRequested = Signal(str)

    def __init__(self, window, icon, parent):
        super().__init__(parent)
        self.tray = None

    def set_language(self, language):
        pass

    def restore(self):
        pass


class QuietNotifications(QObject):
    activated = Signal(str)

    def __init__(self, window, tray, root, parent):
        super().__init__(parent)
        self.language = "zh"

    @Slot(str, str, bool, bool)
    def task_finished(self, session, title, success, active):
        pass


def settle():
    QTest.qWait(100)


def descendants(root):
    pending = [root]
    while pending:
        item = pending.pop()
        yield item
        pending.extend(item.childItems())


def find(name, root=None):
    matches = []
    for item in descendants(root or window.contentItem()):
        if item.objectName() == name:
            matches.append(item)
    # UserMessageBody and MessageBody coexist in each row; their hidden empty
    # SelectableText delegates deliberately share the selection identity.
    if matches:
        return next((item for item in matches if item.isVisible()), matches[0])
    raise AssertionError("Missing QML item: " + name)


def signal(item, name, *args):
    if isinstance(item, str):
        item = find(item)
    assert QMetaObject.invokeMethod(item, name, Qt.DirectConnection, *args), name
    settle()


def document(item):
    return item.property("textDocument").textDocument()


def blocks(doc):
    block = doc.begin()
    while block.isValid():
        yield block
        block = block.next()


def assert_spacing(item, percent):
    nonempty = [block for block in blocks(document(item)) if block.text().strip()]
    assert nonempty, item.objectName()
    for block in nonempty:
        fmt = block.blockFormat()
        assert fmt.lineHeightType() == QTextBlockFormat.ProportionalHeight.value, block.text()
        assert abs(fmt.lineHeight() - percent) < .01, (block.text(), fmt.lineHeight(), percent)


def show_message(index):
    window.setProperty("page", "chat")
    signal("conversation", "jumpToMessage", Q_ARG("QVariant", index))
    return find("messageBubble_" + str(index))


def text_items(root):
    return [item for item in descendants(root)
            if item.isVisible() and item.property("text") and item.property("font") is not None]


def assert_font(item, family):
    actual = item.property("font").family()
    assert actual == family, (item.objectName(), actual, family)


def assert_inside(item, container, tolerance=2):
    origin = item.mapToItem(container, QPointF(0, 0))
    assert item.width() > 0 and item.height() > 0, item.objectName()
    assert origin.x() >= -tolerance and origin.y() >= -tolerance, item.objectName()
    assert origin.x() + item.width() <= container.width() + tolerance, item.objectName()
    assert origin.y() + item.height() <= container.height() + tolerance, item.objectName()


def assert_row(names):
    controls = [find(name) for name in names]
    row = controls[0].parentItem()
    rects = []
    for control in controls:
        assert_inside(control, row)
        point = control.mapToItem(row, QPointF(0, 0))
        rects.append((point.x(), point.x() + control.width()))
    for left, right in zip(rects, rects[1:]):
        assert left[1] <= right[0] + 1, (names, rects)


def assert_text_fits(item):
    assert item.property("contentHeight") <= item.height() + 2, item.objectName()
    assert document(item).documentLayout().documentSize().width() <= item.width() + 2, item.objectName()


USER = "User long wrapped text with punctuation and readable lines. " * 16
PROSE = ("Paragraph with **bold**, 中文 and a wrapped sentence. " * 10 +
         "\n\n- List entry alpha\n- List entry beta\n\n" +
         "| Item | Value |\n|---|---|\n| alpha | 42 |\n| beta | 84 |\n\n" +
         "```python\nfor i in range(3):\n    print(i)\n```\n\nFinal paragraph.")
THINKING = "Thinking through a long wrapped example step by step. " * 8

with ExitStack() as mocks:
    # Preserve real QObject/signal types; MagicMock on a QObject class can disturb
    # PySide's dynamic metaobject before the QML window is constructed.
    mocks.enter_context(patch("app.tray.TrayController", QuietTray))
    mocks.enter_context(patch("app.notifications.TaskNotifications", QuietNotifications))
    mocks.enter_context(patch("app.controller.Controller.loadNativeIndex", lambda self: None))
    mocks.enter_context(patch("app.desktop_plugins.DesktopPlugins.start", lambda self, identifier: None))
    app, engine, backend = create_application()
    window = engine.rootObjects()[0]
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
    terminal = None
    try:
        window.setWidth(1280)
        window.setHeight(1000)
        default_family = app.font().family()
        assert backend.fontScale == 1 and backend.lineSpacing == "standard"
        window.setProperty("page", "settings")
        window.setProperty("settingsTab", 5)
        settle()

        # Invoke QML controls/signals directly; never synthesize mouse or key events.
        for percentage in (75, 100, 125):
            signal("fontPreset_" + str(percentage), "clicked")
            assert abs(backend.fontScale - percentage / 100) < .001
            assert abs(find("fontScaleSlider").property("value") - percentage / 100) < .001
            assert find("fontScaleValue").property("value") == percentage
            assert find("fontScaleLabel").property("text") == str(percentage) + "%"
            assert [find("fontPreset_" + str(p)).property("checked") for p in (75, 100, 125)] == [p == percentage for p in (75, 100, 125)]
        slider = find("fontScaleSlider")
        slider.setProperty("value", 1.13)
        signal(slider, "moved")
        assert abs(backend.fontScale - 1.13) < .001
        assert not any(find("fontPreset_" + str(p)).property("checked") for p in (75, 100, 125))
        spin = find("fontScaleValue")
        assert spin.property("editable")
        editor = spin.property("contentItem")
        editor.forceActiveFocus()
        editor.setProperty("text", "117%")
        find("fontPreset_100").forceActiveFocus()
        settle()
        assert spin.property("value") == 117 and abs(backend.fontScale - 1.17) < .001, (spin.property("value"), backend.fontScale, editor.property("text"))
        assert abs(slider.property("value") - 1.17) < .001
        assert find("fontScaleLabel").property("text") == "117%"

        backend.setFontScale(1)
        record = backend._view
        record.messages = [
            {"role": "user", "text": USER},
            {"role": "assistant", "text": PROSE, "error": False},
            {"role": "assistant", "text": "", "error": False, "thinking": THINKING},
        ]
        backend.chatChanged.emit()
        backend.transcriptChanged.emit()
        settle()
        terminal = TerminalView(window.contentItem())
        terminal.setVisible(False)
        terminal_metrics = (terminal._ch, terminal._cw, terminal.fontFamily)
        heights = {}
        for setting, percent in (("standard", 120), ("compact", 100), ("relaxed", 150)):
            window.setProperty("page", "settings")
            signal("lineSpacing_" + setting, "clicked")
            assert backend.lineSpacing == setting
            assert find("lineSpacing_" + setting).property("checked")
            user_bubble = show_message(0)
            user = find("selectText_0_0", user_bubble)
            assert_spacing(user, percent)
            show_message(1)
            prose = find("selectText_1_0")
            assert_spacing(prose, percent)
            doc = document(prose)
            assert any(block.textList() is not None for block in blocks(doc)), "List fixture missing"
            tables = [frame for frame in doc.rootFrame().childFrames() if isinstance(frame, QTextTable)]
            assert len(tables) == 1 and tables[0].rows() == 3
            assert tables[0].cellAt(1, 0).firstCursorPosition().block().blockFormat().lineHeight() == percent
            heights[setting] = (user.property("contentHeight"), prose.property("contentHeight"))
            code = find("codeBlock_1")
            code_shape = [(block.blockFormat().lineHeightType(), block.blockFormat().lineHeight()) for block in blocks(document(code))]
            if setting == "standard":
                original_code_shape = code_shape
                code_height = code.property("contentHeight")
            else:
                assert code_shape == original_code_shape
                assert code.property("contentHeight") == code_height
            show_message(2)
            thinking = find("thinkingText_2_0")
            thinking.parentItem().parentItem().setProperty("expanded", True)
            settle()
            assert_spacing(thinking, percent)
            assert (terminal._ch, terminal._cw, terminal.fontFamily) == terminal_metrics
        assert all(compact < standard < relaxed for compact, standard, relaxed in zip(heights["compact"], heights["standard"], heights["relaxed"])), heights

        # Real controller streaming projection must apply formatting to new blocks.
        record.messages = [{"role": "assistant", "text": "", "error": False}]
        record.phase = "running"
        backend.chatChanged.emit()
        for chunk in ("Streaming paragraph.\n\n", "- Streaming list\n\n", "| A | B |\n|---|---|\n| streamed-cell | 7 |"):
            backend._handle_pi_event(record, {"type": "delta", "text": chunk})
            settle()
        show_message(0)
        streamed = find("selectText_0_0")
        assert "streamed-cell" in document(streamed).toPlainText()
        assert_spacing(streamed, 150)
        backend._handle_pi_event(record, {"type": "done"})
        settle()

        # Font changes reach four visible UI regions, then restore system default.
        picker = find("interfaceFontFamily")
        family = "serif"
        picker.setProperty("currentIndex", backend.availableFonts.index(family))
        signal(picker, "activated", Q_ARG(int, backend.availableFonts.index(family)))
        for chosen in (family, default_family):
            if chosen == default_family:
                picker.setProperty("currentIndex", 0)
                signal(picker, "activated", Q_ARG(int, 0))
                assert backend.config["fontFamily"] == ""
            show_message(0)
            assert_font(find("selectText_0_0"), chosen)
            assert_font(find("promptInput"), chosen)
            assert_font(find("taskStatusText", find("composerTaskStatus")), chosen)
            sidebar_labels = text_items(find("settingsButton"))
            assert sidebar_labels
            for label in sidebar_labels:
                assert_font(label, chosen)
            window.setProperty("page", "settings")
            settle()
            assert_font(find("fontScaleLabel"), chosen)

        # Exercise extreme requested presets on full long-chat and settings layouts.
        record.messages = [{"role": "user", "text": USER}, {"role": "assistant", "text": PROSE, "error": False}]
        backend.chatChanged.emit()
        backend.transcriptChanged.emit()
        for scale in (.75, 1.25):
            backend.setFontScale(scale)
            settle()
            assert_inside(find("settingsButton"), find("sidebar"))
            assert_inside(find("searchChatsButton"), find("sidebar"))
            assert find("projectList").y() + find("projectList").height() <= find("settingsButton").y()
            for index in (0, 1):
                bubble = show_message(index)
                assert_inside(bubble, bubble.parentItem())
                for item in descendants(bubble):
                    if item.isVisible() and item.property("textDocument") is not None and item.property("text"):
                        assert_text_fits(item)
                        assert_inside(item, bubble)
                if index == 1:
                    prose = find("selectText_1_0")
                    doc = document(prose)
                    table = next(frame for frame in doc.rootFrame().childFrames() if isinstance(frame, QTextTable))
                    assert doc.documentLayout().frameBoundingRect(table).right() <= prose.width() + 2
            conversation, composer = find("conversation"), find("composer")
            assert conversation.y() + conversation.height() <= composer.y()
            assert_inside(composer, find("chatPage"))
            window.setProperty("page", "settings")
            settle()
            assert_row(["fontPreset_75", "fontPreset_100", "fontPreset_125", "fontScaleSlider", "fontScaleValue"])
            assert_row(["lineSpacing_compact", "lineSpacing_standard", "lineSpacing_relaxed"])
            appearance = find("appearanceSettings")
            scroll = find("settingsScroll")
            assert appearance.width() <= scroll.width() + 2
            for name in ("fontScaleValue", "fontScaleLabel", "interfaceFontFamily"):
                control = find(name)
                assert_inside(control, control.parentItem())
        assert not warnings, "\n".join(warnings)
        print("APPEARANCE_UI_OK: controls, editable percent, all prose spacing, streaming, font propagation/reset and 75%/125% layouts")
    finally:
        if terminal is not None:
            terminal.timer.stop()
        backend.close()
        import shiboken6
        shiboken6.delete(engine)
        sandbox.cleanup()
