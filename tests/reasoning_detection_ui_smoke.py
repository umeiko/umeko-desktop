"""Gear dialog and slider states for automatic reasoning detection.

Offscreen only, with a synthetic backend: no Pi, no requests and no real
desktop input. Clicks go to the offscreen window. Set
REASONING_UI_SHOTS to a directory to keep screenshots of each state.
"""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QObject, Property, Signal, Slot, QMetaObject, QUrl, Q_ARG, Q_RETURN_ARG, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow  # noqa: F401  (types the root window)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.thinking_formats import FORMAT_OPTIONS

PROVIDER = "test-provider-id"
# Strings that must never reach the user: format ids, status ids and raw JSON.
INTERNAL = ("openai-none", "chat-template", "anthropic-adaptive", "on-off-verified", "cannot-disable",
            "on-not-observable", "probing", "invalidAccepted", "offSupported", "{", "}")

KNOWN_FORMAT = {"state": "known", "source": "probe", "format": "chat-template", "verified": True,
                "offSupported": True, "status": "on-off-verified"}
STATES = {
    "auto-known": {
        "reasoningLevelsAuto": True, "reasoningFormatAuto": True, "reasoningFormat": "chat-template",
        "reasoningDetection": {"state": "known", "source": "metadata", "levels": ["low", "medium", "high"], "verified": True},
        "reasoningFormatDetection": KNOWN_FORMAT},
    "probing": {
        "reasoningLevelsAuto": True, "reasoningFormatAuto": True, "reasoningFormat": "openai",
        "reasoningDetection": {"state": "probing"}, "reasoningFormatDetection": {"state": "probing"}},
    "failed": {
        "reasoningLevelsAuto": True, "reasoningFormatAuto": True, "reasoningFormat": "openai",
        "reasoningDetection": {"state": "failed", "error": "HTTP 503: service unavailable", "levels": [], "verified": False},
        "reasoningFormatDetection": {"state": "failed", "error": "HTTP 503: service unavailable", "verified": False}},
    "unverified": {
        "reasoningLevelsAuto": True, "reasoningFormatAuto": True, "reasoningFormat": "chat-template",
        "reasoningDetection": {"state": "known", "source": "fallback", "verified": False, "invalidAccepted": True,
                               "levels": ["none", "minimal", "low", "medium", "high", "xhigh", "max"]},
        "reasoningFormatDetection": KNOWN_FORMAT},
    "manual-levels": {
        "reasoningLevels": ["low", "medium", "max"], "reasoningLevelsAuto": False,
        "reasoningFormatAuto": True, "reasoningFormat": "chat-template",
        "reasoningDetection": {"state": "known", "levels": ["low", "high"], "verified": True},
        "reasoningFormatDetection": KNOWN_FORMAT},
    "manual-format": {
        "reasoningLevelsAuto": True, "reasoningFormatAuto": False, "reasoningFormat": "qwen",
        "reasoningDetection": {"state": "known", "levels": ["low", "high"], "verified": True},
        "reasoningFormatDetection": KNOWN_FORMAT},
    "always-thinks": {
        "reasoningLevelsAuto": True, "reasoningFormatAuto": True, "reasoningFormat": "openai",
        "reasoningDetection": {"state": "known", "levels": ["low", "high", "max"], "verified": True},
        "reasoningFormatDetection": {"state": "known", "format": "openai", "verified": False,
                                     "offSupported": False, "status": "cannot-disable"}},
}


class Backend(QObject):
    changed = Signal()
    reasoningChanged = Signal()
    reasoningDetectionChanged = Signal()

    def __init__(self):
        super().__init__()
        self.levels = ["low", "high", "max"]
        self.effort = "off"
        self.theme = "light"
        self.off_supported = True
        self.rows = {}
        self.redetected = []

    def _config(self):
        return {"theme": self.theme, "fontFamily": "", "selectedProvider": PROVIDER, "selectedModel": "test-model",
                "providers": [{"id": PROVIDER, "name": "Test provider", "api": "openai",
                               "models": [{"alias": "test-model", "upstream": "test-model"}]}]}

    config = Property("QVariantMap", _config, notify=changed)
    themeStyle = Property("QVariantMap", lambda self: {}, constant=True)
    fontScale = Property(float, lambda self: 1.0, constant=True)
    lineSpacing = Property(str, lambda self: "standard", constant=True)
    language = Property(str, lambda self: "zh", constant=True)
    reasoningLevels = Property("QStringList", lambda self: self.levels, notify=changed)
    reasoningEffort = Property(str, lambda self: self.effort, notify=reasoningChanged)
    reasoningDetectionState = Property(str, lambda self: "known", notify=reasoningDetectionChanged)
    reasoningOffSupported = Property("QVariant", lambda self: self.off_supported, notify=reasoningDetectionChanged)
    reasoningFormatOptions = Property("QVariantList", lambda self: FORMAT_OPTIONS, constant=True)

    @Slot(str, result=bool)
    def setReasoningEffort(self, value):
        if value not in ["off", *self.levels]:
            return False
        self.effort = value
        self.reasoningChanged.emit()
        return True

    @Slot(str, str)
    def selectModel(self, provider, alias):
        pass

    @Slot(str, str, result="QVariantMap")
    def modelReasoningSettings(self, provider, alias):
        row = self.rows.get(alias) if provider == PROVIDER else None
        if row is None:
            return {}
        states = {"levels": "manual" if row["reasoningLevelsAuto"] is False else row["reasoningDetection"]["state"],
                  "format": "manual" if row["reasoningFormatAuto"] is False else row["reasoningFormatDetection"]["state"]}
        return {**row, "states": states}

    @Slot(str, str, result=bool)
    def redetectModelReasoning(self, provider, alias):
        self.redetected.append((provider, alias))
        self.rows[alias] = {**self.rows[alias], "reasoningDetection": {"state": "probing"},
                            "reasoningFormatDetection": {"state": "probing"}}
        self.reasoningDetectionChanged.emit()
        return True

    @Slot(str, result="QVariantMap")
    def contextWindowSuggestion(self, name):
        return {"tokens": 128000, "matched": False}

    @Slot(str, result="QVariantMap")
    def visionSuggestion(self, name):
        return {"vision": False, "matched": False}


def run(shots):
    app = QApplication([])
    if os.name == "nt":
        for name in ("msyh.ttc", "segoeui.ttf"):
            QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / name))
    backend = Backend()
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
    engine.rootContext().setContextProperty("backend", backend)
    source = b'''import QtQuick
import QtQuick.Controls
import "app/qml"
ApplicationWindow {
    visible: true; width: 900; height: 760
    color: Theme.bg
    function loadModels(raw) { models.load(JSON.parse(raw)) }
    function modelRows() { return models.json() }
    ProviderModels { id: models; objectName: "providerModels"; width: 800; x: 20; y: 20; providerId: "test-provider-id"; api: "openai" }
    Item { id: anchor; x: 40; y: 700; width: 200; height: 32
        ModelPopup { objectName: "modelPopup"; parent: anchor }
    }
}'''
    window = None
    try:
        engine.loadData(source, QUrl.fromLocalFile(str(ROOT / "reasoning-detection-fixture.qml")))
        assert engine.rootObjects(), warnings
        window = engine.rootObjects()[0]
        QTest.qWait(50)

        def find(name, root=None):
            pending = [root or window.contentItem()]
            overlay = window.property("overlay")
            if root is None and overlay is not None:
                pending.append(overlay)
            while pending:
                item = pending.pop()
                if item.objectName() == name:
                    return item
                pending.extend(item.childItems())
            item = window.findChild(QObject, name)
            assert item is not None, "Missing QML object: " + name
            return item

        def invoke(item, method, *args):
            assert QMetaObject.invokeMethod(item, method, *args), method
            QTest.qWait(30)

        def visible_texts(item):
            texts, pending = [], [item]
            while pending:
                node = pending.pop()
                if not node.isVisible():
                    continue
                for prop in ("text", "displayText", "placeholderText"):
                    value = node.property(prop)
                    if isinstance(value, str) and value:
                        texts.append(value)
                pending.extend(node.childItems())
            return texts

        dialog = find("providerModelReasoning")
        content = dialog.property("contentItem")

        def check_readable():
            texts = visible_texts(content)
            leaked = [text for text in texts if any(token in text for token in INTERNAL)]
            assert not leaked, leaked
            return texts

        def shot(name):
            QTest.qWait(80)
            if shots:
                assert window.grabWindow().save(str(Path(shots) / (name + ".png"))), name

        def open_state(key):
            if dialog.property("visible"):
                invoke(dialog, "close")
            backend.rows = {"test-model": STATES[key]}
            row = {"upstream": "test-model", "alias": "test-model", **STATES[key]}
            invoke(window, "loadModels", Q_ARG("QVariant", json.dumps([row])))
            invoke(find("providerModelSettings_0"), "clicked")
            assert dialog.property("visible")
            QTest.qWait(60)
            return check_readable()

        def text(name):
            return find(name, content).property("text")

        def shown(name):
            return find(name, content).isVisible()

        def rows():
            return json.loads(QMetaObject.invokeMethod(window, "modelRows", Q_RETURN_ARG("QVariant")))

        for theme in ("light", "dark"):
            backend.theme = theme
            backend.changed.emit()
            suffix = "-" + theme

            texts = open_state("auto-known")
            assert shown("providerModelReasoning_autoLevels") and not shown("providerModelReasoning_manualLevels")
            assert text("providerModelReasoning_levelsState") == "已检测"
            assert "1  Low" in texts and "3  High" in texts, texts
            assert text("providerModelReasoning_formatState") == "已检测：通过 chat_template_kwargs 里的 enable_thinking 开关"
            assert text("providerModelReasoning_formatNote") == "已确认可以开启和关闭思考"
            assert not shown("providerModelReasoning_alwaysThinks")
            assert find("providerModelReasoning_format", content).property("currentIndex") == 0
            shot("dialog-auto-detected" + suffix)

            open_state("probing")
            assert text("providerModelReasoning_levelsState") == "检测中…"
            assert text("providerModelReasoning_formatState") == "检测中…"
            assert not shown("providerModelReasoning_detectedLevels")
            shot("dialog-probing" + suffix)

            open_state("failed")
            assert text("providerModelReasoning_levelsState") == "检测失败"
            assert text("providerModelReasoning_levelsNote") == "原因：HTTP 503: service unavailable"
            assert text("providerModelReasoning_formatNote") == "原因：HTTP 503: service unavailable"
            shot("dialog-failed" + suffix)

            texts = open_state("unverified")
            assert text("providerModelReasoning_levelsState") == "已检测 · 档位未经验证"
            assert "服务端接受任何档位值" in text("providerModelReasoning_levelsNote")
            assert "7  Max" in texts and "共 7 档，从低到高，不含关闭" in texts, texts
            shot("dialog-unverified" + suffix)

            open_state("manual-levels")
            assert shown("providerModelReasoning_manualLevels") and not shown("providerModelReasoning_autoLevels")
            assert find("providerModelReasoning_count", content).property("value") == 3
            assert [find("providerModelReasoning_name_%d" % i, content).property("text") for i in range(3)] == ["low", "medium", "max"]
            assert find("providerModelReasoning_levelsMode", content).property("currentIndex") == 1
            shot("dialog-manual-levels" + suffix)

            open_state("manual-format")
            picker = find("providerModelReasoning_format", content)
            assert picker.property("currentIndex") == [o["value"] for o in FORMAT_OPTIONS if o["value"] != "anthropic-adaptive"].index("qwen") + 1
            assert picker.property("displayText") == "通过 enable_thinking 开关"
            assert text("providerModelReasoning_formatNote") == "按所选方式发送，自动检测结果不会覆盖。"
            assert not shown("providerModelReasoning_formatState")
            shot("dialog-manual-format" + suffix)

            open_state("always-thinks")
            assert shown("providerModelReasoning_alwaysThinks")
            assert "这个模型总会思考，选「关闭」也会思考" in visible_texts(content)
            assert text("providerModelReasoning_formatState") == "已检测：通过 reasoning_effort 设置，关闭时不发送"
            shot("dialog-always-thinks" + suffix)
            invoke(dialog, "close")

            # Chat slider: effective levels and the always-thinking note, no hover tooltip.
            backend.levels, backend.off_supported = ["low", "medium", "high", "max"], False
            backend.changed.emit(); backend.reasoningDetectionChanged.emit()
            assert backend.setReasoningEffort("high")
            popup = find("modelPopup")
            invoke(popup, "open")
            QTest.qWait(900)
            slider = find("reasoningEffortSlider")
            note = find("reasoningOffNote")
            assert slider.property("to") == 4 and slider.property("value") == 3
            assert note.isVisible() and note.property("text") == "这个模型总会思考，选「关闭」也会思考"
            note_bottom = note.mapToScene(note.boundingRect().bottomLeft()).y()
            manage = find("manageProvidersButton")
            assert note_bottom <= manage.mapToScene(manage.boundingRect().topLeft()).y(), "note overlaps the footer"
            shot("slider-always-thinks" + suffix)
            backend.off_supported = True
            backend.reasoningDetectionChanged.emit(); QTest.qWait(50)
            assert not note.isVisible()
            backend.levels = ["low", "high"]
            backend.changed.emit(); QTest.qWait(50)
            assert slider.property("to") == 2
            invoke(popup, "close")
            QTest.qWait(900)

        # Re-detect: a real click on the button calls the backend slot.
        open_state("auto-known")
        button = find("providerModelReasoning_redetect", content)
        assert button.property("enabled")
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, button.mapToScene(button.boundingRect().center()).toPoint())
        QTest.qWait(100)
        assert backend.redetected == [(PROVIDER, "test-model")], backend.redetected
        assert text("providerModelReasoning_levelsState") == "检测中…"

        # Draft results: manual levels and manual format are emitted to the row.
        open_state("auto-known")
        mode = find("providerModelReasoning_levelsMode", content)
        mode.setProperty("currentIndex", 1)
        invoke(mode, "activated", Q_ARG(int, 1))
        assert shown("providerModelReasoning_manualLevels")
        assert [find("providerModelReasoning_name_%d" % i, content).property("text") for i in range(3)] == ["low", "medium", "high"]
        picker = find("providerModelReasoning_format", content)
        index = [o["value"] for o in FORMAT_OPTIONS if o["value"] != "anthropic-adaptive"].index("deepseek") + 1
        picker.setProperty("currentIndex", index)
        invoke(picker, "activated", Q_ARG(int, index))
        invoke(dialog, "confirm")
        row = rows()[0]
        assert row["reasoningLevels"] == ["low", "medium", "high"] and row["reasoningLevelsAuto"] is False
        assert row["reasoningFormat"] == "deepseek" and row["reasoningFormatAuto"] is False

        # Returning both parts to automatic keeps the detected list.
        open_state("manual-levels")
        mode = find("providerModelReasoning_levelsMode", content)
        mode.setProperty("currentIndex", 0)
        invoke(mode, "activated", Q_ARG(int, 0))
        invoke(dialog, "confirm")
        row = rows()[0]
        assert row["reasoningLevelsAuto"] is True and row["reasoningLevels"] == ["low", "high"]
        assert row["reasoningFormatAuto"] is True

        # Unsaved rows have no detection result and cannot be re-detected yet.
        invoke(window, "loadModels", Q_ARG("QVariant", json.dumps([{"upstream": "new-model", "alias": "new-model"}])))
        backend.rows = {}
        invoke(find("providerModelSettings_0"), "clicked")
        assert text("providerModelReasoning_levelsState") == "尚未检测，保存后会在后台自动检测"
        assert not find("providerModelReasoning_redetect", content).property("enabled")
        check_readable()
        invoke(dialog, "close")

        assert not warnings, warnings
        print("REASONING_DETECTION_UI_OK: auto, probing, failed, unverified, manual levels, manual format, always thinks, slider note, re-detect click")
    finally:
        if window is not None:
            window.hide()
        import shiboken6
        shiboken6.delete(engine)


if __name__ == "__main__":
    shots = os.environ.get("REASONING_UI_SHOTS", "")
    if shots:
        Path(shots).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="umeko-reasoning-detection-ui-") as profile:
        os.environ["UMEKO_DATA_DIR"] = profile
        run(shots)
