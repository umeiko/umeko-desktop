"""Actual QML bindings and draft gear state, with a synthetic backend only.

This explicit UI smoke never starts Pi, makes requests, shows a window or
injects keyboard/pointer input. QQmlApplicationEngine owns the component tree.
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

from PySide6.QtCore import QObject, Property, Signal, Slot, QMetaObject, QUrl, Q_ARG, Q_RETURN_ARG
from PySide6.QtGui import QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QApplication


class Backend(QObject):
    reasoningLevelsChanged = Signal()
    reasoningChanged = Signal()

    def __init__(self):
        super().__init__()
        self.levels = ["low", "high", "max"]
        self.effort = "off"

    config = Property("QVariantMap", lambda self: {
        "providers": [], "fontFamily": "", "theme": "light"}, constant=True)
    themeStyle = Property("QVariantMap", lambda self: {}, constant=True)
    fontScale = Property(float, lambda self: 1.0, constant=True)
    lineSpacing = Property(str, lambda self: "standard", constant=True)
    language = Property(str, lambda self: "zh", constant=True)
    reasoningLevels = Property("QStringList", lambda self: self.levels, notify=reasoningLevelsChanged)
    reasoningEffort = Property(str, lambda self: self.effort, notify=reasoningChanged)

    @Slot(str, result=bool)
    def setReasoningEffort(self, value):
        if value not in ["off", *self.levels]:
            return False
        self.effort = value
        self.reasoningChanged.emit()
        return True

    @Slot(str, result="QVariantMap")
    def contextWindowSuggestion(self, name):
        return {"tokens": 128000, "matched": False}

    @Slot(str, result="QVariantMap")
    def visionSuggestion(self, name):
        return {"vision": False, "matched": False}


def run():
    app = QApplication([])
    if not QFontDatabase.families() and os.name == "nt":
        for name in ("msyh.ttc", "segoeui.ttf", "consola.ttf"):
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
    visible: false; width: 900; height: 700
    function loadModels(raw) { models.load(JSON.parse(raw)) }
    function modelRows() { return models.json() }
    function addModel() { models.addModel() }
    Item { id: anchor; width: 200; height: 32
        ModelPopup { objectName: "modelPopup"; parent: anchor }
    }
    ProviderModels { id: models; objectName: "providerModels"; width: 800 }
}'''
    window = None
    try:
        engine.loadData(source, QUrl.fromLocalFile(str(ROOT / "reasoning-auto-fixture.qml")))
        assert engine.rootObjects(), warnings
        window = engine.rootObjects()[0]

        def find(name):
            item = window.findChild(QObject, name)
            if item is not None:
                return item
            popup = window.findChild(QObject, "modelPopup")
            pending = [window.contentItem(), popup.property("contentItem")]
            while pending:
                item = pending.pop()
                if item.objectName() == name:
                    return item
                pending.extend(item.childItems())
            raise AssertionError("Missing QML object: " + name)

        def invoke(item, method, *args):
            assert QMetaObject.invokeMethod(item, method, *args), method
            app.processEvents()

        def load(rows):
            invoke(window, "loadModels", Q_ARG("QVariant", json.dumps(rows)))

        def rows():
            value = QMetaObject.invokeMethod(window, "modelRows", Q_RETURN_ARG("QVariant"))
            return json.loads(value)

        app.processEvents()
        slider = find("reasoningEffortSlider")
        assert slider.property("enabled") and slider.property("to") == 3
        backend.levels = ["custom-low", "custom-high"]
        backend.reasoningLevelsChanged.emit()
        assert backend.setReasoningEffort("custom-high")
        app.processEvents()
        assert slider.property("to") == 2 and slider.property("value") == 2
        assert find("reasoningSelectedLabel").property("text") == "custom-high"
        backend.levels = []
        backend.reasoningLevelsChanged.emit()
        assert backend.setReasoningEffort("off")
        app.processEvents()
        assert not slider.property("enabled") and slider.property("value") == 0
        backend.levels = ["single"]
        backend.reasoningLevelsChanged.emit()
        assert backend.setReasoningEffort("single")
        app.processEvents()
        assert slider.property("enabled") and slider.property("to") == 1
        slider.setProperty("value", 0)
        invoke(slider, "moved")
        assert backend.effort == "off"

        # Legacy records without a reasoning list remain automatic. Other flags
        # survive loading/serialization, and a new row is automatic as well.
        load([{"upstream": "test-model", "alias": "Testprovider/test-model",
               "contextWindowAuto": False, "contextWindow": 4096,
               "visionAuto": False, "vision": True}])
        initial = rows()[0]
        assert initial["reasoningLevelsAuto"] is True
        assert initial["contextWindowAuto"] is False and initial["visionAuto"] is False
        assert initial["vision"] is True and initial["contextWindow"] == "4096"
        invoke(window, "addModel")
        assert rows()[1]["reasoningLevelsAuto"] is True

        # Invoke real QML gear/confirm methods as fixture actions, with no input
        # events. Confirmation is a draft edit and switches only that row manual.
        invoke(find("providerModelSettings_0"), "clicked")
        dialog = find("providerModelReasoning")
        assert dialog.property("rowIndex") == 0 and dialog.property("visible")
        counter = find("providerModelReasoning_count")
        counter.setProperty("value", 2)
        invoke(counter, "valueModified")
        for index, name in enumerate(("custom-low", "custom-high")):
            field = find("providerModelReasoning_name_" + str(index))
            field.setProperty("text", name)
            invoke(field, "textEdited")
        invoke(dialog, "confirm")
        edited = rows()
        assert edited[0]["reasoningLevels"] == ["custom-low", "custom-high"]
        assert edited[0]["reasoningLevelsAuto"] is False
        assert edited[1]["reasoningLevelsAuto"] is True
        assert edited[0]["vision"] is True and edited[0]["visionAuto"] is False
        assert backend.levels == ["single"], "Gear changes must remain provider-editor drafts"

        # Explicit automatic and manual settings round-trip independently.
        load([{"upstream": "test-auto", "reasoningLevels": ["medium"], "reasoningLevelsAuto": True},
              {"upstream": "test-manual", "reasoningLevels": [], "reasoningLevelsAuto": False}])
        assert [row["reasoningLevelsAuto"] for row in rows()] == [True, False]
        assert rows()[1]["reasoningLevels"] == []
        assert not warnings, warnings
        print("REASONING_AUTO_UI_OK: actual slider bindings, off-only, gear draft and independent auto flags")
    finally:
        if window is not None:
            window.hide()
        import shiboken6
        shiboken6.delete(engine)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="umeko-reasoning-auto-ui-") as profile:
        os.environ["UMEKO_DATA_DIR"] = profile
        run()
