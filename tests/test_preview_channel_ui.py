"""Real preview preferences QML, isolated jobs, and offscreen documentation captures.

Run captures explicitly with: python tests/test_preview_channel_ui.py --capture
This harness never constructs the application controller, tray or notifications.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QUICK_BACKEND"] = "software"
os.environ["QT_QUICK_CONTROLS_STYLE"] = "Basic"

from PySide6.QtCore import QObject, Property, QEventLoop, QTimer, QUrl, Signal
from PySide6.QtGui import QFontDatabase, QFontMetrics
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
import shiboken6
from app.preview_channel import PreviewChannel
from test_preview_channel import JobController, isolated_test_module, qt_application


class PreferencesBackend(QObject):
    changed = Signal()

    def __init__(self, preview, language):
        super().__init__()
        self._preview = preview
        self._language = language

    @Property(QObject, constant=True)
    def appAbout(self): return self

    @Property(QObject, constant=True)
    def preview(self): return self._preview

    @Property(str, notify=changed)
    def language(self): return self._language

    @Property(float, constant=True)
    def fontScale(self): return 1.0

    @Property(str, constant=True)
    def lineSpacing(self): return "standard"

    @Property("QVariantMap", constant=True)
    def config(self): return {"fontFamily": qt_application().font().family(), "theme": "light"}

    @Property("QVariantMap", constant=True)
    def themeStyle(self): return {"base": "light", "colors": {}}


class PreviewPreferences:
    def __init__(self, directory, language="zh", channel="release"):
        self.directory = Path(directory)
        release = self.directory / "retained-release.exe"
        release.touch()
        self.state = {"channel": channel, "releaseExecutable": str(release)}
        self.save_state()
        self.controller = JobController(directory)
        self.preview = PreviewChannel(self.controller)
        self.preview._environment = Mock(return_value={})
        self.manager = Mock()
        self.preview._manager = self.manager
        self.backend = PreferencesBackend(self.preview, language)
        self.engine = QQmlApplicationEngine()
        self.warnings = []
        self.engine.warnings.connect(lambda errors: self.warnings.extend(error.toString() for error in errors))
        self.engine.rootContext().setContextProperty("backend", self.backend)
        qml = '''
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "%s" as UI
ApplicationWindow {
    width: 820; height: 560; visible: true
    color: UI.Theme.bg
    title: "Umeko preferences"
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 36; spacing: 22
        Text { text: "Umeko"; color: UI.Theme.muted; font.family: UI.Theme.fontFamily; font.pixelSize: 12; font.letterSpacing: 1.6 }
        Text { text: UI.I18n.t("偏好设置"); color: UI.Theme.ink; font.family: UI.Theme.fontFamily; font.pixelSize: 28; font.weight: Font.DemiBold }
        UI.SectionCard {
            Layout.fillWidth: true
            contentItem: UI.PreviewChannelSettings { objectName: "previewSettings" }
        }
        Item { Layout.fillHeight: true }
    }
}
''' % QUrl.fromLocalFile(str(ROOT / "app/qml")).toString()
        self.engine.loadData(qml.encode("utf-8"), QUrl.fromLocalFile(str(ROOT / "tests/PreviewPreferencesHarness.qml")))
        roots = self.engine.rootObjects()
        if not roots:
            raise AssertionError("\n".join(self.warnings))
        self.window = roots[0]
        if not isinstance(self.window, QQuickWindow):
            raise AssertionError("Expected a Qt Quick application window")
        # Transitions are irrelevant to state contracts and must never gate tests.
        for name in ("previewSwitchConfirmation", "previewUpdateConfirmation", "releaseChannelConfirmation", "previewRestartConfirmation"):
            popup = self.find(name)
            popup.setProperty("enter", None)
            popup.setProperty("exit", None)
        qt_application().processEvents()

    def save_state(self):
        (self.directory / "preview-channel.json").write_text(json.dumps(self.state), encoding="utf-8")

    def status(self, value, channel=None):
        if channel:
            self.state["channel"] = channel
            self.save_state()
            self.preview._state = dict(self.state)
        self.preview._status = dict(value)
        if value.get("state") in ("available", "current"):
            self.preview._plan = dict(value)
        self.preview.changed.emit()
        qt_application().processEvents()

    def find(self, name):
        found = self.window.findChild(QObject, name)
        if found is None:
            raise AssertionError("QML object missing: " + name)
        return found

    def click(self, name):
        button = self.find(name)
        if not button.property("visible") or not button.property("enabled"):
            raise AssertionError("QML action unavailable: " + name)
        button.clicked.emit()
        qt_application().processEvents()

    def render(self):
        """Wait for a render event; the timer only prevents an infrastructure hang."""
        loop = QEventLoop()
        guard = QTimer()
        guard.setSingleShot(True)
        guard.timeout.connect(loop.quit)
        self.window.afterAnimating.connect(loop.quit)
        self.window.requestUpdate()
        guard.start(5000)
        loop.exec()
        self.window.afterAnimating.disconnect(loop.quit)
        guard.stop()
        qt_application().processEvents()

    def capture(self, path):
        self.render()
        image = self.window.grabWindow()
        if image.isNull() or not image.save(str(path)):
            raise AssertionError("Unable to capture offscreen QML: " + str(path))

    def close(self):
        self.window.close()
        self.engine.rootContext().setContextProperty("backend", self.backend)
        shiboken6.delete(self.engine)


class PreviewChannelUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_application()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="umeko-preview-qml-")
        self.addCleanup(self.temporary.cleanup)
        self.environment = patch.dict(os.environ, {"UMEKO_DATA_DIR": self.temporary.name})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.ui = PreviewPreferences(self.temporary.name)
        self.addCleanup(self.ui.close)

    def test_offscreen_font_has_latin_and_chinese_glyphs(self):
        font = self.app.font()
        metrics = QFontMetrics(font)
        if os.name == "nt":
            self.assertIn(font.family(), QFontDatabase.families())
            characters = "Umeko更新通道"
        else:
            characters = "Umeko"
        self.assertTrue(all(metrics.inFontUcs4(ord(character)) for character in characters))

    def test_preflight_and_explicit_install_confirmation(self):
        ui = self.ui
        ui.manager.preflight.return_value = {"ready": True, "detail": "Git · Python · Node.js"}
        ui.find("updateChannelPicker").activated.emit(1)
        self.assertTrue(ui.preview.busy)
        self.assertFalse(ui.find("updateChannelPicker").property("enabled"))
        ui.controller.finish()
        self.app.processEvents()
        self.assertEqual(ui.preview.status["state"], "prerequisites")
        ui.manager.switch_to_preview.assert_not_called()
        ui.click("preparePreviewButton")
        self.assertTrue(ui.find("previewSwitchConfirmation").property("opened"))
        ui.manager.switch_to_preview.assert_not_called()
        ui.click("confirmPreviewSwitchButton")
        self.assertEqual(len(ui.controller.jobs), 1)
        ui.state["channel"] = "preview"
        ui.save_state()
        ui.manager.switch_to_preview.return_value = {"state": "restart-required", "message": "预览版已准备完成。保存后可重启。"}
        ui.controller.finish()
        self.app.processEvents()
        self.assertEqual(ui.preview.channel, "preview")
        self.assertTrue(ui.find("restartChannelButton").property("visible"))
        ui.controller.close.assert_not_called()
        ui.controller.store.save.assert_not_called()
        self.assertFalse(ui.find("previewRestartConfirmation").property("opened"))
        ui.click("restartChannelButton")
        self.assertTrue(ui.find("previewRestartConfirmation").property("opened"))
        ui.controller.close.assert_not_called()
        self.assertEqual(ui.warnings, [])

    def test_update_review_and_dependency_retry_are_exposed(self):
        ui = self.ui
        plan = illustrative_plan("zh")
        plan["dependencyPending"] = True
        ui.status({"state": "error", "message": "依赖安装失败，请重试。"}, channel="preview")
        self.assertTrue(ui.find("checkPreviewUpdatesButton").property("visible"))
        ui.manager.check_update.return_value = plan
        ui.click("checkPreviewUpdatesButton")
        ui.controller.finish()
        self.app.processEvents()
        self.assertTrue(ui.find("reviewPreviewUpdateButton").property("visible"))
        ui.click("reviewPreviewUpdateButton")
        self.assertTrue(ui.find("previewUpdateConfirmation").property("opened"))
        self.assertEqual(ui.find("previewCommitSummary").property("text"), plan["summary"])
        self.assertEqual(ui.find("previewCommitRange").property("text"), "814ca59b2301 → b9072cd81e64")
        ui.manager.apply_update.assert_not_called()
        ui.click("confirmPreviewUpdateButton")
        ui.manager.apply_update.return_value = {"state": "restart-required", "message": "更新完成。"}
        ui.controller.finish()
        self.assertEqual(ui.manager.apply_update.call_args.args, (plan,))
        self.assertEqual(ui.preview.status["state"], "restart-required")
        ui.controller.close.assert_not_called()
        self.assertEqual(ui.warnings, [])

    def test_release_confirmation_preserves_optional_checkout_removal(self):
        ui = self.ui
        ui.status({}, channel="preview")
        ui.find("updateChannelPicker").activated.emit(0)
        self.app.processEvents()
        self.assertTrue(ui.find("releaseChannelConfirmation").property("opened"))
        self.assertFalse(ui.find("removePreviewCheckout").property("checked"))
        ui.manager.switch_to_release.assert_not_called()
        ui.find("removePreviewCheckout").setProperty("checked", True)
        ui.click("confirmReleaseChannelButton")
        ui.manager.switch_to_release.return_value = {"state": "restart-required"}
        ui.controller.finish()
        ui.manager.switch_to_release.assert_called_once_with(remove_checkout=True)
        ui.controller.close.assert_not_called()
        self.assertEqual(ui.warnings, [])

    def test_failed_preflight_disables_install_and_english_is_production_translation(self):
        ui = self.ui
        ui.backend._language = "en"
        ui.backend.changed.emit()
        ui.status({"state": "prerequisites", "ready": False, "message": "请确认运行前提和配置兼容性，再安装预览版。", "detail": "Node.js 22.19+ required"})
        self.assertFalse(ui.find("preparePreviewButton").property("enabled"))
        self.assertEqual(ui.find("preparePreviewButton").property("text"), "Confirm and install preview")
        self.assertIn("Node.js", ui.find("previewChannelDetails").property("text"))
        self.assertIn("official main", ui.find("previewChannelWarning").property("text"))
        self.assertEqual(ui.controller.jobs, [])
        self.assertEqual(ui.warnings, [])


def illustrative_plan(language):
    summaries = {
        "zh": "b9072cd 让偏好设置在窗口缩放时保持清晰\n53ac418 改善会话列表的键盘导航\n2d68f90 完善更新通道的状态提示",
        "en": "b9072cd Keep preferences clear when resizing\n53ac418 Improve keyboard navigation in the session list\n2d68f90 Clarify update channel status",
    }
    return {"state": "available", "message": "发现预览版更新", "base": "814ca59b2301", "target": "b9072cd81e64",
            "summary": summaries[language], "dependencies": []}


def capture_documentation():
    app = qt_application()
    output = ROOT / "docs/images"
    output.mkdir(parents=True, exist_ok=True)
    for language in ("zh", "en"):
        with tempfile.TemporaryDirectory(prefix="umeko-preview-capture-") as directory, patch.dict(os.environ, {"UMEKO_DATA_DIR": directory}):
            ui = PreviewPreferences(directory, language, "preview")
            try:
                ui.status(illustrative_plan(language))
                ui.capture(output / ("preview-channel-" + language + ".png"))
                ui.click("reviewPreviewUpdateButton")
                ui.capture(output / ("preview-confirmation-" + language + ".png"))
                if ui.warnings:
                    raise AssertionError("\n".join(ui.warnings))
            finally:
                ui.close()
    print("Offscreen captures: docs/images/preview-{channel,confirmation}-{zh,en}.png")


if __name__ != "__main__":
    class IsolatedPreviewChannelUiTests(unittest.TestCase):
        def test_preview_channel_ui_in_isolated_process(self):
            isolated_test_module(self, Path(__file__).resolve())


def load_tests(loader, tests, pattern):
    if __name__ == "__main__":
        return tests
    return unittest.TestSuite([IsolatedPreviewChannelUiTests("test_preview_channel_ui_in_isolated_process")])


if __name__ == "__main__":
    if sys.argv[1:] == ["--capture"]:
        capture_documentation()
    else:
        unittest.main()
