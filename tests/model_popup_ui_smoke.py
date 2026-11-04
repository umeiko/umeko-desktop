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
from PySide6.QtCore import QMetaObject, QObject, QPoint, QPointF, Qt
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

    # #70: independent toolbar rows used to overlap with long provider names.
    # Exercise actual layout bounds, including translated running/permission labels.
    provider = backend.store.data['providers'][0]
    provider['name'] = 'Long provider / ' + '供应商名称很长' * 8
    long_model = 'a-very-long-model-name-with-a-preview-version-and-region-' * 3
    provider['models'][0]['alias'] = long_model
    backend.selectModel(provider['id'], long_model)
    backend.setReasoningEffort('max')
    record = backend._view
    record.id = 'composer-layout-fixture'
    backend.store.data['sessionMeta'][record.id] = {'dangerousAllowed':True}
    saw_stacked = saw_hidden_hint = saw_elided_name = False

    def rect(item):
        point = item.mapToScene(QPointF(0, 0))
        return point.x(), point.y(), point.x() + item.width(), point.y() + item.height()

    def check_toolbar():
        # Row positions update during polish. Sample that layout, even while
        # the enclosing sidebar PID is still changing the available width.
        for name in ('composerUtilityIcons','composerUtilityControls','composerSendControls','composerModelLabels'):
            assert QMetaObject.invokeMethod(find(name),'forceLayout',Qt.DirectConnection), name
        controls = [find(name) for name in ('composerUtilityControls','modelSelector','composerSendControls')]
        left, top, right, bottom = rect(find('composerToolbar'))
        for item in controls:
            x1,y1,x2,y2 = rect(item)
            assert x1 >= left-.5 and x2 <= right+.5 and y1 >= top-.5 and y2 <= bottom+.5, (item.objectName(),rect(item),(left,top,right,bottom))
        for index, first in enumerate(controls):
            for second in controls[index+1:]:
                a,b = rect(first),rect(second)
                assert min(a[2],b[2])-max(a[0],b[0]) <= .5 or min(a[3],b[3])-max(a[1],b[1]) <= .5, (first.objectName(),a,second.objectName(),b)
        selector = find('modelSelector')
        assert selector.width() >= 32 and find('sendButton').isVisible()
        assert provider['name'] in selector.property('hint') and long_model in selector.property('hint')
        for name in ('composerProviderName','composerModelName','reasoningEffortBadge','composerModelChevron'):
            label = find(name)
            if label.isVisible():
                a,b = rect(label),rect(selector)
                assert a[0] >= b[0]-.5 and a[2] <= b[2]+.5, (name,a,b,
                    {key:selector.property(key) for key in ('width','scale','namesWidth','showProvider','providerWidth')},
                    [(child.objectName(),child.x(),child.width(),child.isVisible()) for child in label.parentItem().childItems()])

    with patch.object(backend, '_command_pi', return_value=True):
        backend.subagents.open('popup-child')
    window.setProperty('webPreferredWidth',420)
    wait(lambda:not find('webPane').property('moving'),'Narrow chat pane did not settle')
    for language in ('zh','en'):
        backend.setLanguage(language)
        for scale in (.5,1.,1.25,2.):
            backend.setFontScale(scale)
            for width in (1060,1320):
                window.resize(width,900)
                for phase in ('idle','running'):
                    record.action,record.phase,record.ready = 'prompt',phase,True
                    backend.changed.emit(); backend.chatChanged.emit(); QTest.qWait(100)
                    check_toolbar()
                    saw_stacked |= find('composerToolbar').property('stacked')
                    saw_hidden_hint |= not find('composerStatus').isVisible()
                    saw_elided_name |= not find('composerProviderName').isVisible() or find('composerProviderName').property('truncated')
    assert saw_stacked and saw_hidden_hint and saw_elided_name
    # Serif and monospace bearings differ from their horizontal advance.
    for family in ('serif','monospace'):
        backend.setFontFamily(family)
        for scale in (1.,2.):
            backend.setFontScale(scale); QTest.qWait(100)
            check_toolbar()
    backend.setFontFamily('系统默认')
    record.phase = 'idle'; backend.changed.emit()
    click('closeSubagentPaneButton')
    wait(lambda:not find('webPane').property('moving'),'Narrow pane did not close')
    backend.setLanguage('zh'); backend.setFontScale(1.)
    window.resize(1060,900)
    open_popup()
    QTest.keyClick(window,Qt.Key_Escape)
    wait(lambda:not popup.property('visible'),'Responsive selector cannot close')
    assert not warnings, "\n".join(warnings)
    print("MODEL_POPUP_UI_OK: provider/model selection, popup focus, long-name toolbar bounds, 50-200% fonts, Chinese/English and idle/running layouts")
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
