"""Real editors publish their caret on focus, without input events or sleeps."""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sandbox = tempfile.TemporaryDirectory(prefix="umeko-input-method-")
os.environ["UMEKO_DATA_DIR"] = str(Path(sandbox.name) / "profile")
os.environ["UMEKO_LANGUAGE"] = "zh"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QObject, QCoreApplication, QMetaObject, Qt, Signal, Slot, Property, QUrl
from PySide6.QtQml import QQmlEngine, QQmlExpression, QQmlComponent
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QSignalSpy
from app.storage import Store
from main import create_application


class QuietTray(QObject):
    quitRequested = Signal()
    notificationRequested = Signal(str)

    def __init__(self, window, icon, parent):
        super().__init__(parent)
        self.tray = None

    def set_language(self, language):
        pass


class QuietNotifications(QObject):
    activated = Signal(str)

    def __init__(self, window, tray, root, parent):
        super().__init__(parent)

    @Slot(str, str, bool, bool)
    def task_finished(self, *args):
        pass


class EditorSdk(QObject):
    """A Widget's appearance data, with no worker or host operations."""
    hostResponse = Signal(str, "QVariantMap")
    activeChanged = Signal()
    languageChanged = Signal()

    @Property(bool, notify=activeChanged)
    def active(self):
        return False

    @Property(float, constant=True)
    def scale(self):
        return 1.0

    @Property(str, notify=languageChanged)
    def language(self):
        return "en"

    @Property("QVariantMap", constant=True)
    def hostCapabilities(self):
        return {"operations": {}}

    @Property("QVariantMap", constant=True)
    def colors(self):
        return dict(surface="#202521", bg="#181d19", ink="#e4e9e3", muted="#929e94",
                    accent="#9cc69f", accentBg="#334636", hover="#29362b", line="#465148")


def descendants(item):
    yield item
    for child in item.childItems():
        yield from descendants(child)


def find(name, root):
    return next(item for item in descendants(root) if item.objectName() == name)


def evaluate(root, source):
    expression = QQmlExpression(QQmlEngine.contextForObject(root), root, source)
    result = expression.evaluate()
    assert not expression.hasError(), expression.error().toString()
    return result[0]


def settle(root):
    # Flush layout and queued work explicitly; no frame count or elapsed-time gate.
    for item in descendants(root):
        item.ensurePolished()
    QCoreApplication.sendPostedEvents()
    app.processEvents()
    # processEvents handles the events pending at entry. Focus-window delivery
    # can queue the editor refresh, so dispatch that next event-loop turn too.
    QCoreApplication.sendPostedEvents()
    app.processEvents()


def values(rect):
    return [rect.x(), rect.y(), rect.width(), rect.height()]


def check_caret(item, label):
    assert app.focusObject() == item and item.hasActiveFocus(), label
    query = item.inputMethodQuery(Qt.ImCursorRectangle)
    mapped = item.mapRectToScene(query)
    caret = item.mapRectToScene(item.property("cursorRectangle"))
    actual = im.cursorRectangle()
    for expected in (mapped, caret):
        assert all(abs(a - b) <= 1 for a, b in zip(values(actual), values(expected))), (
            label, values(actual), values(expected))
    assert actual.width() > 0 and actual.height() > 0, label
    return values(actual)


def check_focus(item, focus, root, label):
    item.setFocus(False)
    settle(root)
    assert not item.hasActiveFocus(), label
    before = cursor_spy.count()
    before_anchor = anchor_spy.count()
    with patch.object(im, "update", wraps=im.update) as update:
        focus()
        settle(root)
        rectangle = check_caret(item, label)
        assert cursor_spy.count() > before, label + ": caret was not published"
        assert anchor_spy.count() > before_anchor, label + ": anchor was not published"
        assert update.called, label + ": no input-method update after focus"
        queries = update.call_args.args[0]
        required = Qt.ImCursorRectangle | Qt.ImAnchorRectangle | Qt.ImEnabled
        assert queries & required == required, (label, queries)
    assert item.property("text") == "", label + ": focus test must precede typing"
    print(label, rectangle, "update and rectangle signals received")


seed = Store()
seed.data["agent"]["agentDir"] = str(Path(sandbox.name) / "agent")
seed.save()

with ExitStack() as mocks:
    mocks.enter_context(patch("app.tray.TrayController", QuietTray))
    mocks.enter_context(patch("app.notifications.TaskNotifications", QuietNotifications))
    mocks.enter_context(patch("app.controller.Controller.loadNativeIndex", lambda self: None))
    mocks.enter_context(patch("app.desktop_plugins.DesktopPlugins.start", lambda self, identifier: None))
    app, engine, backend = create_application()
    window = engine.rootObjects()[0]
    im = app.inputMethod()
    cursor_spy = QSignalSpy(im.cursorRectangleChanged)
    anchor_spy = QSignalSpy(im.anchorRectangleChanged)
    widget = None
    composer_window = None
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
    try:
        window.requestActivate()
        settle(window.contentItem())
        # Give the real composer a fixed host: Main's unrelated PID sidebar
        # motion must not supply incidental geometry notifications to this test.
        composer_window = QQuickView()
        composer_window.engine().rootContext().setContextProperty("backend", backend)
        composer_window.setResizeMode(QQuickView.SizeRootObjectToView)
        host_url = QUrl.fromLocalFile(str(ROOT / "tests/fixtures/input-method.qml"))
        component = QQmlComponent(composer_window.engine())
        component.setData(b'''import QtQuick
import "../../app/qml" as Umeko
Item {
    Umeko.Composer {
        objectName: "composer"; x: 20; width: parent.width - 40
        anchors.bottom: parent.bottom; anchors.bottomMargin: 20
    }
}''', host_url)
        assert component.isReady(), [error.toString() for error in component.errors()]
        composer_window.setContent(host_url, component, component.create())
        composer_window.resize(840, 400)
        composer_window.show()
        composer_window.requestActivate()
        composer_root = composer_window.rootObject()
        settle(composer_root)
        prompt = find("promptInput", composer_root)
        composer = find("composer", composer_root)
        evaluate(composer, "focusInput()")
        settle(composer_root)
        # Exercise the same focus forwarding as the application's chat actions.
        check_focus(prompt, lambda: evaluate(composer, "focusInput()"), composer_root, "empty composer")

        before = cursor_spy.count()
        with patch.object(im, "update", wraps=im.update) as update:
            composer_window.resize(740, 520)
            settle(composer_root)
            print("resized composer", check_caret(prompt, "resized composer"))
            assert update.called, "resize did not update the input method"
        assert cursor_spy.count() > before, "resize did not publish the caret"

        before = cursor_spy.count()
        prompt.setProperty("text", "中")
        prompt.setProperty("cursorPosition", 1)
        settle(composer_root)
        check_caret(prompt, "first character")
        assert cursor_spy.count() > before, "first character did not publish the caret"

        prompt.setProperty("text", "\n".join("line " + str(i) for i in range(30)))
        prompt.setProperty("cursorPosition", 20)
        settle(composer_root)
        scroll = prompt.parentItem()
        while scroll.property("contentY") is None:
            scroll = scroll.parentItem()
        before = cursor_spy.count()
        with patch.object(im, "update", wraps=im.update) as update:
            scroll.setProperty("contentY", float(scroll.property("contentY")) + 12)
            settle(composer_root)
            print("scrolled composer", check_caret(prompt, "scrolled composer"))
            assert update.called, "scroll did not update the input method"
        assert cursor_spy.count() > before, "scroll did not publish the caret"
        prompt.setProperty("text", "")

        window.requestActivate()
        settle(window.contentItem())
        evaluate(window, "searchVisible = true; searchPane.focusSearch()")
        settle(window.contentItem())
        search = find("conversationSearchInput", window.contentItem())
        check_focus(search, lambda: evaluate(window, "searchPane.focusSearch()"), window.contentItem(), "empty search")

        evaluate(window, 'searchVisible = false; sidebarMenus.target = {kind:"session", id:"fixture", title:""}; sidebarMenus.rename()')
        settle(window.contentItem())
        rename = find("renameInput", window.contentItem())
        # onOpened uses this same editor focus call; reopening an already open
        # popup would not execute that handler a second time.
        check_focus(rename, rename.forceActiveFocus, window.contentItem(), "empty rename")
        window.findChild(QObject, "renamePopup").close()

        window.setProperty("page", "settings")
        window.setProperty("settingsTab", 3)
        settle(window.contentItem())
        instructions = find("agentInstructions", window.contentItem())
        settings_scroll = find("settingsScroll", window.contentItem()).property("contentItem")
        settings_scroll.setProperty("contentY", max(0, instructions.mapToItem(settings_scroll, instructions.boundingRect().topLeft()).y()))
        check_focus(instructions, instructions.forceActiveFocus, window.contentItem(), "empty settings")

        # Changing from an editor to a button must not make the temporary
        # editor wrapper own (and invalidate) the application's window.
        window.setProperty("settingsTab", 0)
        settle(window.contentItem())
        QMetaObject.invokeMethod(find("addProviderButton", window.contentItem()), "clicked")
        settle(window.contentItem())
        assert app.focusObject().objectName() == "providerName"
        find("saveProviderButton", window.contentItem()).forceActiveFocus()
        settle(window.contentItem())
        from shiboken6 import isValid
        assert isValid(window) and isValid(window.contentItem()), "editor blur invalidated the window"
        window.findChild(QObject, "providerEditorPopup").close()

        # Load the real Widget QML without starting a plugin worker.
        sdk = EditorSdk()
        widget = QQuickView()
        widget.engine().rootContext().setContextProperty("backend", backend)
        widget.setResizeMode(QQuickView.SizeRootObjectToView)
        widget.setInitialProperties({"sdk": sdk})
        widget.setSource(QUrl.fromLocalFile(str(ROOT / "umeko-plugins/skill-manager/qml/Main.qml")))
        assert widget.status() == QQuickView.Ready, [error.toString() for error in widget.errors()]
        widget.resize(500, 800)
        widget.show()
        widget.requestActivate()
        settle(widget.rootObject())
        field = find("skillManagerSearch", widget.rootObject())
        check_focus(field, field.forceActiveFocus, widget.rootObject(), "empty Widget search")

        # A focus-window change must also refresh the unchanged caret.
        before = cursor_spy.count()
        with patch.object(im, "update", wraps=im.update) as update:
            evaluate(composer, "focusInput()")
            composer_window.requestActivate()
            settle(composer_root)
            check_caret(prompt, "reactivated composer")
            assert update.called, "activation did not update the input method"
        assert cursor_spy.count() > before
        assert not warnings, warnings
        print("input_method_ui_smoke: PASS (focus, resize, scroll, activation; no input events or sleeps)")
    finally:
        backend.close()
        from shiboken6 import delete
        if widget is not None:
            widget.close()
            delete(widget)
        if composer_window is not None:
            composer_window.close()
            delete(composer_window)
        delete(window)
        delete(engine)
        app.processEvents()
        sandbox.cleanup()
