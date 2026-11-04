"""Isolated real-QML login settings: fake OS state, no app/Node or login writes.

Run with QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software, as in docs/ci.md.
Only Qt receives synthetic control signals; no desktop input is injected.
"""
import json
import os
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QUICK_BACKEND"] = "software"
os.environ["QT_QUICK_CONTROLS_STYLE"] = "Basic"

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest


ROOT = Path(__file__).resolve().parents[1]


class FakeLoginStartup(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.system = {"available": True, "reason": "", "umeko": False, "proxy": False}
        self._state = dict(self.system)
        self.requests = []
        self.refreshes = 0
        self.reject_next = False

    @Property("QVariantMap", notify=changed)
    def state(self):
        return dict(self._state)

    @Slot()
    def refresh(self):
        self.refreshes += 1
        self._state = dict(self.system)
        self.changed.emit()

    @Slot(bool, bool)
    def setEnabled(self, umeko, proxy):
        self.requests.append((umeko, proxy))
        if not self.reject_next:
            self.system.update(umeko=umeko, proxy=proxy)
        self.reject_next = False
        self.refresh()


class FakeBackend(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.startup = FakeLoginStartup()
        self._language = "zh"
        self._config = {
            "theme": "light", "fontFamily": "",
            "desktop": {"chatWidthHints": True, "autoOpenSubmissions": True, "webDisplay": "embedded"},
        }

    @Property(QObject, constant=True)
    def loginStartup(self):
        return self.startup

    @Property("QVariantMap", notify=changed)
    def config(self):
        return self._config

    @Property(str, notify=changed)
    def language(self):
        return self._language

    @Property(float, constant=True)
    def fontScale(self):
        return 1.0

    @Property(str, constant=True)
    def lineSpacing(self):
        return "standard"

    @Property("QVariantMap", constant=True)
    def themeStyle(self):
        return {"base": "light", "colors": {}}

    @Slot(str)
    def saveDesktopSettings(self, payload):
        self._config["desktop"].update(json.loads(payload))
        self.changed.emit()

    def set_language(self, language):
        self._language = language
        self.changed.emit()


HARNESS = rb'''
import QtQuick
import QtQuick.Controls
import "."

Window {
    id: window
    width: 1100; height: 800; visible: true; color: Theme.bg
    title: "Umeko Desktop settings - isolated fixture"
    property bool desktopActive: true
    Rectangle {
        width: 230; height: parent.height; color: Theme.sidebar
        Rectangle { width: 1; anchors.right: parent.right; height: parent.height; color: Theme.line }
        Column {
            x: 24; y: 32; width: parent.width - 48; spacing: 28
            Text { text: "Umeko"; color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: 24; font.weight: Font.DemiBold }
            Text { text: I18n.t("\u8bbe\u7f6e"); color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: 13 }
            Rectangle {
                width: parent.width; height: 40; radius: 8; color: Theme.accentBg
                Text { anchors.verticalCenter: parent.verticalCenter; x: 12; text: "Agent"; color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: 14 }
            }
        }
    }
    Column {
        x: 266; y: 35; width: parent.width - x - 36; spacing: 23
        Text { text: I18n.t("\u8bbe\u7f6e") + " / Agent"; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: 13 }
        Text { text: "Umeko Desktop"; color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: 25; font.weight: Font.DemiBold }
        DesktopSettings {
            width: parent.width; visible: window.desktopActive
        }
    }
}
'''


def main():
    app = QGuiApplication([])
    if os.name == "nt":
        # Match main.py: the Windows offscreen plugin may discover no fonts.
        if not QFontDatabase.families():
            for name in ("msyh.ttc", "segoeui.ttf", "consola.ttf"):
                QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / name))
        app.setFont(QFont("Microsoft YaHei UI", 10))
    backend = FakeBackend()
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda values: warnings.extend(value.toString() for value in values))
    engine.rootContext().setContextProperty("backend", backend)
    engine.loadData(HARNESS, QUrl.fromLocalFile(str(ROOT / "app/qml/login-startup-fixture.qml")))
    assert engine.rootObjects(), "\n".join(warnings)
    window = engine.rootObjects()[0]
    assert isinstance(window, QQuickWindow), "The isolated QML root must be a Quick window"

    def settle():
        QTest.qWait(200)  # Complete layout and the existing Toggle visual transition.

    def find(name):
        pending = [window.contentItem()]
        while pending:
            item = pending.pop()
            if item.objectName() == name:
                return item
            pending.extend(item.childItems())
        raise AssertionError("Missing control: " + name)

    def checked():
        return tuple(bool(find(name).property("checked")) for name in ("desktopLoginUmeko", "desktopLoginProxy"))

    def click(name):
        control = find(name)
        assert control.isEnabled()
        expression = QQmlExpression(engine.rootContext(), control, "toggle(); clicked()")
        expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        settle()

    try:
        settle()
        assert backend.startup.refreshes == 1, "Opening the page must query system state"
        assert checked() == (False, False)
        click("desktopLoginUmeko")
        assert checked() == (True, False) and backend.startup.requests[-1] == (True, False)
        click("desktopLoginProxy")
        assert checked() == (True, True) and backend.startup.requests[-1] == (True, True)
        click("desktopLoginUmeko")
        assert checked() == (False, True) and backend.startup.requests[-1] == (False, True)
        click("desktopLoginProxy")
        assert checked() == (False, False) and backend.startup.requests[-1] == (False, False)

        # A rejected write must leave the UI bound to the actual system result.
        backend.startup.reject_next = True
        click("desktopLoginUmeko")
        assert checked() == (False, False)
        backend.startup.system.update(umeko=True, proxy=True)
        backend.startup.refresh()
        settle()
        assert checked() == (True, True), "Switches must follow a subsequent system refresh"

        # Reopening the page queries external changes, instead of retaining a saved bool.
        originalSwitch = find("desktopLoginUmeko")
        window.setProperty("desktopActive", False)
        settle()
        backend.startup.system.update(umeko=False, proxy=True)
        refreshes = backend.startup.refreshes
        window.setProperty("desktopActive", True)
        settle()
        assert find("desktopLoginUmeko") is originalSwitch, "Match AgentPage: hide and reuse the settings component"
        assert backend.startup.refreshes == refreshes + 1 and checked() == (False, True)

        reason = "开机启动仅适用于打包后的应用。"
        backend.startup.system.update(available=False, reason=reason, umeko=False, proxy=False)
        backend.startup.refresh()
        for language, expected in (("zh", reason), ("en", "Start at login is available only in packaged applications.")):
            backend.set_language(language)
            settle()
            assert not find("desktopLoginUmeko").isEnabled()
            assert not find("desktopLoginProxy").isEnabled()
            message = find("desktopLoginStartupReason")
            assert message.isVisible() and message.property("text") == expected

        backend.startup.system.update(available=True, reason="", umeko=True, proxy=True)
        backend.startup.refresh()
        output = ROOT / "build/login-startup-ui"
        output.mkdir(parents=True, exist_ok=True)
        for language in ("zh", "en"):
            backend.set_language(language)
            settle()
            assert checked() == (True, True)
            assert not find("desktopLoginStartupReason").isVisible()
            assert window.grabWindow().save(str(output / ("settings-" + language + ".png")))
        assert not warnings, "\n".join(warnings)
        print("LOGIN_STARTUP_UI_OK: real bilingual settings, independent/both toggles, rejected write, system refresh, reopen and unavailable reason; fake OS only")
    finally:
        import shiboken6
        window.close()
        shiboken6.delete(engine)
        app.processEvents()


if __name__ == "__main__":
    main()
