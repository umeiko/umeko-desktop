"""Select real provider/model options after the shared PID popup lifecycle runs."""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["UMEKO_DATA_DIR"] = tempfile.mkdtemp(prefix="umeko-model-popup-")
os.environ["UMEKO_LANGUAGE"] = "zh"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
from PySide6.QtCore import QObject, QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from main import create_application

app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))


def find(name):
    stack = [window.contentItem()]
    while stack:
        item = stack.pop()
        if item.objectName() == name: return item
        stack.extend(item.childItems())
    raise AssertionError(name)


def wait(predicate, label):
    for _ in range(400):
        QTest.qWait(10)
        if predicate(): return
    raise AssertionError(label + "\n" + "\n".join(warnings))


def click(name):
    item = find(name)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, item.mapToScene(item.boundingRect().center()).toPoint())


try:
    QTest.qWait(200)
    window.resize(1320, 900)
    providers = []
    for name, models in [("Alpha", ["swift", "careful"]), ("Beta", ["breeze"])]:
        assert backend.saveProvider("", name, "openai", "http://127.0.0.1:1/v1", "fixture-only",
                                    json.dumps([{"upstream": model, "alias": model} for model in models]))
        providers.append(next(row["id"] for row in backend.store.data["providers"] if row["name"] == name))
    popup = window.findChild(QObject, "modelPopup")

    def open_popup():
        click("modelSelector")
        wait(lambda: popup.property("desiredOpen") and not popup.property("animating"), "Model popup did not expand")
        assert popup.property("width") >= 300 and popup.property("height") >= 220, {
            key: popup.property(key) for key in ("width", "height", "expandedWidth", "expandedHeight", "heightLimit", "fullHeight", "desiredOpen", "anchorPosition")}
        assert popup.property("contentOpacity") > .98
        assert find("modelSearch").hasActiveFocus()
        search = find("modelSearch")
        top = search.mapToScene(QPointF(0, 0))
        bottom = search.mapToScene(QPointF(search.width(), search.height()))
        assert top.x() >= 0 and top.y() >= 0 and bottom.x() <= window.width() and bottom.y() <= window.height()

    open_popup()
    for character in "breeze": QTest.keyClick(window, Qt.Key(ord(character.upper())))
    QTest.qWait(80)
    assert not find("modelOption_" + providers[0] + "_swift").isVisible()
    click("modelOption_" + providers[1] + "_breeze")
    assert (backend.config["selectedProvider"], backend.config["selectedModel"]) == (providers[1], "breeze")
    QTest.qWait(80)
    assert find("promptInput").hasActiveFocus()
    wait(lambda: not popup.property("visible"), "Selected model did not close popup")
    assert find("promptInput").hasActiveFocus()
    open_popup()
    assert find("modelSearch").property("text") == ""
    click("modelOption_" + providers[0] + "_careful")
    assert (backend.config["selectedProvider"], backend.config["selectedModel"]) == (providers[0], "careful")
    wait(lambda: not popup.property("visible"), "Second selection did not close popup")
    # QML child conversations stay visible while the model selector is open;
    # only native browser surfaces need to be hidden under QML popups.
    from unittest.mock import patch
    backend.subagents.merge(backend._view, {"id": "popup-child", "status": "running", "avatarSlot": 0})
    with patch.object(backend, "_command_pi", return_value=True):
        backend.subagents.open("popup-child")
    backend.subagents.handle(backend._view, {"type": "subagent_context", "id": "popup-child", "messages": [{"role": "assistant", "text": "Working"}]})
    wait(lambda: not find("webPane").property("moving"), "Child pane did not settle")
    open_popup()
    assert find("subagentPane").isVisible(), "Model selection blanked the child conversation"
    QTest.keyClick(window, Qt.Key_Escape)
    wait(lambda: not popup.property("visible"), "Model popup did not close beside child")
    click("closeSubagentPaneButton")
    wait(lambda: not find("webPane").property("moving"), "Child pane did not close")
    backend.setFontScale(2.)
    window.resize(1060, 900)
    QTest.qWait(150)
    open_popup()
    QTest.keyClick(window, Qt.Key_Escape)
    wait(lambda: not popup.property("visible"), "Escape did not close popup")
    assert not popup.property("desiredOpen") and find("promptInput").hasActiveFocus()
    open_popup()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(400, 90))
    wait(lambda: not popup.property("visible"), "Outside click did not close popup")
    assert not warnings, "\n".join(warnings)
    print("MODEL_POPUP_UI_OK: expanded geometry, visible content, provider/model selection, search/reset, 200% font, Escape/outside close and typing focus")
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
