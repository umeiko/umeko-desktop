"""Real frame-driven PID motion, including retargeting while in flight."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('UMEKO_LANGUAGE','zh')
os.environ["UMEKO_DATA_DIR"] = tempfile.mkdtemp(prefix="umeko-pid-tabs-")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
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


def settle():
    positions = []
    for _ in range(180):
        QTest.qWait(16)
        positions.append(glow.x())
        if not glow.property("moving"): return positions
    raise AssertionError(("PID did not settle", glow.x(), glow.property("targetX"), glow.property("velocityX")))


def target(tab):
    x, width = glow.x(), glow.width()
    vx, vw = glow.property("velocityX"), glow.property("velocityWidth")
    window.setProperty("settingsTab", tab)
    # Changing a setpoint must not reset the current state or velocity.
    assert abs(glow.x() - x) < 0.001 and abs(glow.width() - width) < 0.001
    assert abs(glow.property("velocityX") - vx) < 0.001
    assert abs(glow.property("velocityWidth") - vw) < 0.001


try:
    window.setProperty("page", "settings")
    QTest.qWait(120)
    glow = find("settingsTabHighlight")
    assert not glow.property("moving")
    assert abs(glow.width() - find("settingsTab_0").width()) < 0.1
    button = find("settingsTab_5")
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, button.mapToScene(button.boundingRect().center()).toPoint())
    assert window.property("settingsTab") == 5
    assert glow.x() < button.x() - 100, "highlight teleported"
    positions = settle()
    assert max(positions) > button.x() + 1, "missing damped overshoot"
    assert abs(glow.x() - button.x()) < 0.12 and abs(glow.width() - button.width()) < 0.12
    assert (glow.mapToScene(glow.boundingRect().topLeft()) - button.mapToScene(button.boundingRect().topLeft())).manhattanLength() < 0.12
    for tab, delay in [(0,48),(3,32),(1,32),(5,48),(0,16),(3,32)]:
        target(tab)
        QTest.qWait(delay)
        assert glow.property("moving")
    settle()
    assert abs(glow.x() - find("settingsTab_3").x()) < 0.12
    assert abs(glow.width() - find("settingsTab_3").width()) < 0.12
    # Themes and a smaller window retain target geometry without idle updates.
    for theme in ("yanami","dark","light"):
        backend.setTheme(theme)
        window.resize(1060,700)
        QTest.qWait(80)
        assert not glow.property("moving")
        assert abs(glow.x() - find("settingsTab_3").x()) < 0.12
    # No hidden animations, or fly-in on returning to settings.
    target(5); QTest.qWait(48)
    assert glow.property("moving")
    window.setProperty("page", "chat"); QTest.qWait(30)
    assert not glow.property("moving") and glow.property("velocityX") == 0
    window.setProperty("page", "settings"); QTest.qWait(30)
    assert not glow.property("moving") and abs(glow.x() - find("settingsTab_5").x()) < 0.1
    assert not warnings, "\n".join(warnings)
    print("SETTINGS_PID_OK: native clicks, continuous position/width/velocity, rapid retargeting, overshoot/settling, themes/resize, hidden cancellation, no idle frames")
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
