"""Render detector evidence in the real QML controls, using offscreen Qt only.

REASONING_EFFECT_RESULTS points to a JSON object keyed by scenario, with each
value containing the detector's ``levels`` and ``format`` results.
REASONING_EFFECT_SHOTS optionally keeps one menu and dialog PNG per scenario.
REASONING_EFFECT_SCENARIOS optionally selects comma-separated scenario keys.
All controls are exercised through QML functions; no pointer or keyboard input.
"""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QObject, Property, Q_ARG, Q_RETURN_ARG, QEventLoop, QMetaObject, QTimer, QUrl
from PySide6.QtGui import QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication

from reasoning_detection_ui_smoke import Backend as BaseBackend, PROVIDER


class Backend(BaseBackend):
    sessionBackend = Property(str, lambda self: "pi", constant=True)
    canChooseBackend = Property(bool, lambda self: True, constant=True)
    dshOwnConfig = Property(bool, lambda self: False, constant=True)
    dshRuntime = Property("QVariantMap", lambda self: {}, constant=True)


def run(results, shots):
    app = QApplication([])
    assert app.platformName() == "offscreen", app.platformName()
    if os.name == "nt":
        for font in ("msyh.ttc", "segoeui.ttf"):
            QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / font))
    backend = Backend()
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
    engine.rootContext().setContextProperty("backend", backend)
    source = b'''import QtQuick
import QtQuick.Controls
import "app/qml"
ApplicationWindow {
    visible: true; width: 720; height: 900; color: Theme.bg
    property string savedDraft: ""
    function showMenu() { dialog.close(); popup.open() }
    function closeMenu() { popup.close() }
    function showDialog(raw) {
        const row = JSON.parse(raw)
        dialog.edit(0, "Test provider / test-model", JSON.stringify(row.reasoningDetection.levels || []),
                    {savedAlias: "test-model", reasoningLevelsAuto: true, reasoningFormatAuto: true,
                     reasoningFormat: row.reasoningFormat}, "test-provider-id", "openai")
    }
    function exerciseManual() {
        dialog.setLevelsAuto(false)
        dialog.setFormat(dialog.formatIds.indexOf("deepseek") + 1)
        dialog.confirm()
        return savedDraft
    }
    Text { x: 40; y: 28; text: "Test provider / test-model"; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: 15 }
    Item { id: anchor; x: 178; y: 780; width: 365; height: 32
        ModelPopup { id: popup; objectName: "effectMenu"; parent: anchor }
    }
    ModelReasoningDialog {
        id: dialog; objectName: "effectDialog"
        onConfirmed: (index, levels, automatic, format, formatAutomatic) => {
            savedDraft = JSON.stringify({levels: JSON.parse(levels), levelsAuto: automatic,
                                         format: format, formatAuto: formatAutomatic})
        }
    }
}'''
    window = None

    def settle(milliseconds=80):
        loop = QEventLoop()
        QTimer.singleShot(milliseconds, loop.quit)
        loop.exec()

    def invoke(item, method, *args):
        assert QMetaObject.invokeMethod(item, method, *args), method
        settle()

    def find(name):
        item = window.findChild(QObject, name)
        assert item is not None, name
        return item

    def text(name):
        return str(find(name).property("text"))

    def shot(name, popup):
        if not shots:
            return
        settle(120)
        image = window.grabWindow()
        item = popup.property("contentItem")
        bounds = item.mapRectToScene(item.boundingRect())
        padding = float(popup.property("padding")) + 12
        ratio = image.devicePixelRatio()
        rect = bounds.adjusted(-padding, -padding, padding, padding)
        rect = rect.intersected(window.contentItem().boundingRect())
        image = image.copy(int(rect.x() * ratio), int(rect.y() * ratio),
                           int(rect.width() * ratio), int(rect.height() * ratio))
        assert image.save(str(shots / (name + ".png"))), name

    try:
        engine.loadData(source, QUrl.fromLocalFile(str(ROOT / "reasoning-effect-fixture.qml")))
        assert engine.rootObjects(), warnings
        window = engine.rootObjects()[0]
        settle()
        menu, dialog = find("effectMenu"), find("effectDialog")
        for scenario, result in results.items():
            levels, style = result["levels"], result["format"]
            row = {"reasoningLevelsAuto": True, "reasoningFormatAuto": True,
                   "reasoningFormat": style.get("format", "openai"),
                   "reasoningDetection": levels, "reasoningFormatDetection": style}
            backend.rows = {"test-model": row}
            backend.levels = levels.get("levels", [])
            backend.off_supported = style.get("offSupported")
            backend.effort = backend.levels[0] if backend.levels else "off"
            backend.changed.emit()
            backend.reasoningChanged.emit()
            backend.reasoningDetectionChanged.emit()
            invoke(window, "showMenu")
            settle(950)
            hint = text("reasoningEffectHint")
            if backend.effort != "off":
                assert text("reasoningSelectedLabel") != "关闭", backend.effort
            assert int(find("reasoningEffortSlider").property("value")) == (["off", *backend.levels].index(backend.effort))
            assert ("已观察到档位变化" if levels.get("verified") else "档位效果未能确认") in hint, hint
            assert ("开关已确认" if style.get("verified") else "开关效果未能确认") in hint, hint
            shot(scenario + "-menu", menu)
            invoke(window, "closeMenu")
            settle(850)
            invoke(window, "showDialog", Q_ARG("QVariant", json.dumps(row)))
            assert dialog.property("visible")
            assert text("effectDialog_levelsState") == ("已观察到档位变化" if levels.get("verified") else "档位效果未能确认")
            if style.get("degradingStyles"):
                assert "已排除" in text("effectDialog_degradingStyles")
            if levels.get("evidence"):
                assert text("effectDialog_levelEvidence"), levels
            shot(scenario + "-dialog", dialog)
            # Explicit manual settings continue to produce manual draft values.
            saved = json.loads(QMetaObject.invokeMethod(window, "exerciseManual", Q_RETURN_ARG("QVariant")))
            assert saved["levelsAuto"] is False and saved["formatAuto"] is False, saved
            assert saved["format"] == "deepseek", saved
            print(json.dumps({"scenario": scenario, "menuHint": hint,
                              "levelsVerified": levels.get("verified"), "styleVerified": style.get("verified")}, ensure_ascii=False), flush=True)
        assert not warnings, warnings
        print("REASONING_EFFECT_UI_OK: offscreen evidence, menu/dialog states, manual override", flush=True)
    finally:
        if window is not None:
            window.hide()
        import shiboken6
        shiboken6.delete(engine)


if __name__ == "__main__":
    results = json.loads(Path(os.environ["REASONING_EFFECT_RESULTS"]).read_text(encoding="utf-8"))
    if os.environ.get("REASONING_EFFECT_SCENARIOS"):
        results = {key: results[key] for key in os.environ["REASONING_EFFECT_SCENARIOS"].split(",")}
    shots = Path(os.environ["REASONING_EFFECT_SHOTS"]) if os.environ.get("REASONING_EFFECT_SHOTS") else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    # Callers may select an isolated test root; no real user profile is used.
    with tempfile.TemporaryDirectory(prefix="umeko-reasoning-effect-", dir=os.environ.get("UMEKO_TEST_ROOT")) as profile:
        os.environ["UMEKO_DATA_DIR"] = profile
        run(results, shots)
