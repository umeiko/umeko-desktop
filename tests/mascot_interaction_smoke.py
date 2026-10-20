"""Actual welcome gestures, spring reset, local reactions and input preservation."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["UMEKO_DATA_DIR"] = tempfile.mkdtemp(prefix="umeko-mascot-ui-")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest, QSignalSpy
from app.storage import Store
from main import create_application

store = Store()
store.data["agent"]["agentDir"] = str(store.directory / "agent")
store.save()
app, engine, backend = create_application()
window = engine.rootObjects()[0]
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))


def find(name):
    stack = [window.contentItem()]
    while stack:
        item = stack.pop()
        if item.objectName() == name: return item
        stack.extend(item.childItems())
    raise AssertionError(name)


def capture(name):
    target = ROOT / "artifacts/screenshots" / (name + ".png")
    target.parent.mkdir(parents=True, exist_ok=True)
    assert window.grabWindow().save(str(target))


def wait_idle():
    for _ in range(250):
        QTest.qWait(20)
        if not mascot.property("animating"): return
    raise AssertionError("Mascot did not stop animating")


try:
    QTest.qWait(150)
    backend.setTheme("yanami")
    mascot, pointer, prompt = find("welcomeMascot"), find("welcomeMascotPointer"), find("promptInput")
    spy = QSignalSpy(mascot.interaction)
    greeting, portrait = backend.greeting, backend.portrait
    center = pointer.mapToScene(pointer.boundingRect().center()).toPoint()
    prompt.setProperty("text", "Unsent mascot fixture draft")
    prompt.forceActiveFocus()
    assert not mascot.property("animating")
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, center)
    QTest.qWait(100)
    assert mascot.property("squashX") > 1 and mascot.property("squashY") < 1
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, center)
    QTest.qWait(70)
    assert spy.at(0) == ["tap"] and mascot.property("hop") < 0
    assert mascot.property("reactionText") and prompt.hasActiveFocus()
    capture("55-mascot-tap-bounce")
    wait_idle()
    assert abs(mascot.property("hop")) < 0.1
    assert (backend.greeting, backend.portrait) == (greeting, portrait)
    # A drag must not also count as a click or trigger the long-press surprise.
    count = spy.count()
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, center)
    QTest.mouseMove(window, center + QPoint(54, -30)); QTest.qWait(60)
    assert mascot.property("dragging")
    assert abs(mascot.property("offsetX") - 54) < 1 and mascot.property("tilt") > 0
    capture("56-mascot-drag")
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, center + QPoint(54, -30))
    assert spy.count() == count + 1 and spy.at(count) == ["drag"]
    wait_idle()
    assert abs(mascot.property("offsetX")) < 0.2 and abs(mascot.property("offsetY")) < 0.2
    assert abs(mascot.property("tilt")) < 0.2
    # Hold and release: exactly one hold, with a finite, local cookie burst.
    count = spy.count()
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, center)
    QTest.qWait(750)
    assert spy.count() == count + 1 and spy.at(count) == ["hold"]
    assert mascot.property("celebrating") and find("welcomeCookie").isVisible()
    capture("57-mascot-cookie-surprise")
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, center)
    assert spy.count() == count + 1, "hold also fired a click"
    wait_idle()
    QTest.qWait(3300)
    assert find("welcomeGreeting").property("text") == greeting
    assert prompt.property("text") == "Unsent mascot fixture draft"
    # Keyboard interaction and quick-tap easter egg use the same bounded effect.
    mascot.forceActiveFocus()
    QTest.keyClick(window, Qt.Key_Space)
    QTest.keyClick(window, Qt.Key_Return)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, center)
    assert mascot.property("celebrating")
    # Leaving the view cancels all motion and transient text immediately.
    window.setProperty("page", "settings"); QTest.qWait(80)
    assert not mascot.property("animating") and mascot.property("reactionText") == ""
    window.setProperty("page", "chat"); QTest.qWait(80)
    assert find("welcomeGreeting").property("text") == greeting
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, center)
    assert mascot.property("animating")
    backend.newSession(); QTest.qWait(80)
    assert mascot.property("reactionText") == "" and not mascot.property("animating")
    count = spy.count()
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, center)
    QTest.mouseMove(window, center + QPoint(30, -20)); QTest.qWait(50)
    backend.newSession(); QTest.qWait(80)
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, center + QPoint(30, -20))
    assert spy.count() == count, "old gesture leaked into the new conversation"
    assert mascot.property("reactionText") == "" and not mascot.property("animating")
    assert not warnings, "\n".join(warnings)
    print("MASCOT_UI_OK: click squash/bounce, drag spring, hold/quick-tap surprise, keyboard, draft/focus, greeting reset, hidden/view cancellation, no idle animation")
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
