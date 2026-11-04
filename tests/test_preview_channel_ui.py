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
from app.preview_network import NETWORK_MESSAGES, network_failure
from app.preview_source import PreviewError
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

    def finish_preflight(self, checks, language):
        ui = self.ui
        ui.backend._language = language
        ui.backend.changed.emit()
        ui.manager.preflight.return_value = {
            "ready": all(check["ready"] for check in checks), "details": checks,
        }
        ui.find("updateChannelPicker").activated.emit(1)
        self.assertTrue(ui.preview.busy)
        ui.controller.finish()
        self.app.processEvents()
        self.assertEqual(ui.preview.status["state"], "prerequisites")
        self.assertFalse(ui.preview.busy)

    def test_all_prerequisites_enable_install_and_explain_success_bilingually(self):
        checks = [{"name": name, "ready": True, "detail": "OK"} for name in (
            "保留的正式版", "网络与代理", "Git", "Python 3.10+ / venv", "Node.js 22.19+",
            "npm", "安装脚本 Shell", "磁盘空间 (至少 2 GiB)", "官方 main 分支连接")]
        for language, summary, passed in (
                ("zh", "运行前提全部满足，可以确认并安装预览版。", "已满足"),
                ("en", "All prerequisites are met. You can confirm and install Preview.", "Passed")):
            with self.subTest(language=language):
                self.finish_preflight(checks, language)
                self.assertTrue(self.ui.preview.status["ready"])
                self.assertTrue(self.ui.find("preparePreviewButton").property("enabled"))
                self.assertEqual(self.ui.find("previewPrerequisiteResult").property("text"), summary)
                details = self.ui.find("previewChannelDetails")
                self.assertTrue(details.property("visible"))
                self.assertIn(passed + " · Git: OK", details.property("text"))
                self.ui.manager.switch_to_preview.assert_not_called()
        self.assertEqual(self.ui.warnings, [])

    def test_each_failed_prerequisite_disables_install_and_shows_bilingual_remedy(self):
        remedies = (
            ("保留的正式版", "完整解压", "fully extracted Release"),
            ("Git", "安装 Git", "Install Git"),
            ("Python 3.10+ / venv", "含 venv 和 ensurepip", "with venv and ensurepip"),
            ("Node.js 22.19+", "安装 Node.js 22.19", "Install Node.js 22.19"),
            ("npm", "含 npm", "with npm"),
            ("安装脚本 Shell", "PowerShell 可用", "PowerShell is available"),
            ("磁盘空间 (至少 2 GiB)", "腾出至少 2 GiB", "Free at least 2 GiB"),
            ("官方 main 分支连接", "Git 的网络、代理及证书", "Git network, proxy and certificate"),
        )
        for name, chinese, english in remedies:
            for language, remedy, failed, disabled in (
                    ("zh", chinese, "未满足", "安装按钮暂不可用"),
                    ("en", english, "Failed", "installation is disabled")):
                with self.subTest(check=name, language=language):
                    checks = [{"name": label, "ready": label != name, "detail": "probe result"}
                              for label, _, _ in remedies]
                    self.finish_preflight(checks, language)
                    self.assertFalse(self.ui.preview.status["ready"])
                    self.assertFalse(self.ui.find("preparePreviewButton").property("enabled"))
                    result = self.ui.find("previewPrerequisiteResult")
                    self.assertTrue(result.property("visible"))
                    self.assertIn(disabled, result.property("text"))
                    details = self.ui.find("previewChannelDetails")
                    self.assertTrue(details.property("visible"))
                    self.assertEqual(details.property("text").count(failed + " · "), 1)
                    self.assertIn(remedy, details.property("text"))
                    self.ui.preview.switchToPreview()
                    self.assertEqual(self.ui.controller.jobs, [])
                    self.ui.manager.switch_to_preview.assert_not_called()
        self.assertEqual(self.ui.warnings, [])

    def test_recheck_replaces_failed_result_without_starting_installation(self):
        self.finish_preflight([{"name": "Python 3.10+ / venv", "ready": False,
                                "detail": "未找到系统 Python 3.10+"}], "zh")
        self.ui.manager.preflight.return_value = {
            "ready": True, "details": [{"name": "Python 3.10+ / venv", "ready": True, "detail": "OK"}]}
        self.ui.click("recheckPreviewPrerequisitesButton")
        self.assertTrue(self.ui.preview.busy)
        self.assertFalse(self.ui.find("preparePreviewButton").property("enabled"))
        self.ui.controller.finish()
        self.app.processEvents()
        self.assertTrue(self.ui.find("preparePreviewButton").property("enabled"))
        self.assertNotIn("未满足", self.ui.find("previewChannelDetails").property("text"))
        self.assertEqual(self.ui.manager.preflight.call_count, 2)
        self.ui.manager.switch_to_preview.assert_not_called()
        self.assertEqual(self.ui.warnings, [])

    def test_network_failure_categories_and_hints_are_bilingual_and_private(self):
        english = {
            "certificate": ("Certificate problem", "root certificate"),
            "proxy": ("Proxy problem", "HTTP proxy"),
            "dns": ("DNS problem", "DNS and proxy"),
            "timeout": ("Connection timed out", "network connectivity"),
            "other": ("Other network problem", "required tools"),
        }
        for category, (label, hint) in NETWORK_MESSAGES.items():
            for language in ("zh", "en"):
                with self.subTest(category=category, language=language):
                    failure = network_failure(category, [{"code": "PREVIEW_PROXY_UNSUPPORTED"}])
                    self.finish_preflight([{"name": "官方 main 分支连接", "ready": False, **failure}], language)
                    self.assertFalse(self.ui.find("preparePreviewButton").property("enabled"))
                    text = self.ui.find("previewChannelDetails").property("text")
                    expected_label, expected_hint = (label, hint) if language == "zh" else english[category]
                    self.assertIn(expected_label, text)
                    self.assertIn(expected_hint, text)
                    self.assertIn("SOCKS", text)
                    # A later fetch/setup error follows the same controller/UI contract.
                    self.ui.status({}, channel="preview")
                    self.ui.manager.check_update.side_effect = PreviewError(
                        "预览版网络步骤失败。", "https://private.invalid/path user:secret@proxy.invalid", category, failure["limitation"])
                    self.ui.click("checkPreviewUpdatesButton")
                    self.ui.controller.finish()
                    self.app.processEvents()
                    text = self.ui.find("previewChannelDetails").property("text")
                    self.assertIn(expected_label, text)
                    self.assertIn(expected_hint, text)
                    self.assertNotIn("private.invalid", text)
                    self.assertNotIn("secret", text)
                    self.assertIn("SOCKS", text)
                    self.ui.status({}, channel="release")
        self.assertEqual(self.ui.warnings, [])


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
