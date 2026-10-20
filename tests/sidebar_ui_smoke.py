"""Actual pointer resizing, collapse/restore, responsive bounds and restart."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RESTORE = "--check-restore" in sys.argv
if not RESTORE:
    os.environ["UMEKO_DATA_DIR"] = tempfile.mkdtemp(prefix="umeko-sidebar-ui-")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtQuick import QQuickItem
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


def click(name):
    item = find(name)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, item.mapToScene(item.boundingRect().center()).toPoint())
    QTest.qWait(100)


def resize_sidebar(delta):
    handle = find("sidebarResizeHandle")
    start = handle.mapToScene(QPointF(handle.width() / 2, 210)).toPoint()
    with patch.object(backend.store, "save", wraps=backend.store.save) as save:
        QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
        for step in range(1, 5):
            QTest.mouseMove(window, start + QPoint(round(delta * step / 4), 0))
            QTest.qWait(15)
        assert save.call_count == 0, "dragging wrote preferences before release"
        QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, start + QPoint(delta, 0))
        QTest.qWait(100)
        assert save.call_count <= 1, "one drag repeatedly saved the profile"


def capture(name):
    path = ROOT / "artifacts/screenshots" / (name + ".png")
    path.parent.mkdir(parents=True, exist_ok=True)
    assert window.grabWindow().save(str(path))


try:
    QTest.qWait(200)
    sidebar, main = find("sidebar"), find("mainArea")
    if RESTORE:
        assert backend.sidebarCollapsed
        assert not sidebar.isVisible() and sidebar.width() == 0
        assert main.x() == 0 and main.width() == window.width()
        assert backend.sidebarWidth == 346
        assert find("toggleSidebarButton").isVisible()
        assert not warnings, "\n".join(warnings)
        print("SIDEBAR_RESTORE_OK")
    else:
        assert sidebar.width() == 244 and main.x() == 244
        state = backend._view
        state.messages = [{"role": "user", "text": "Keep this conversation while adjusting the layout."},
                          {"role": "assistant", "text": "**Sidebar layout fixture**\n\nResize the sidebar, or collapse it to give the conversation more space.\n\n```python\nprint('Layout changes preserve the conversation')\n```"}]
        backend.chatChanged.emit()
        prompt = find("promptInput")
        prompt.setProperty("text", "Unsent fixture draft")
        resize_sidebar(102)
        assert abs(sidebar.width() - 346) < 1, sidebar.width()
        assert main.x() == sidebar.width()
        assert backend.sidebarWidth == 346
        assert Store(backend.store.directory).data["ui"]["sidebarWidth"] == 346
        resize_sidebar(-240)
        assert sidebar.width() == 200, sidebar.width()
        resize_sidebar(500)
        assert sidebar.width() == 480, sidebar.width()
        # Resize the window without forgetting the user's wider preference.
        window.resize(1060, 740)
        QTest.qWait(100)
        assert sidebar.width() == 300 and main.width() >= 760
        assert backend.sidebarWidth == 480
        window.resize(1320, 860)
        QTest.qWait(100)
        assert sidebar.width() == 480
        resize_sidebar(-134)
        assert sidebar.width() == 346
        backend.setTheme("yanami")
        QTest.qWait(150)
        capture("45-sidebar-resizable")
        click("toggleSidebarButton")
        assert backend.sidebarCollapsed and not sidebar.isVisible()
        assert main.x() == 0 and main.width() == window.width()
        assert not find("sidebarResizeHandle").isVisible()
        assert prompt.property("text") == "Unsent fixture draft"
        capture("46-sidebar-collapsed")
        click("toggleSidebarButton")
        assert sidebar.width() == 346 and sidebar.isVisible()
        # Collapse and restore also work while visiting settings or running a task.
        state.phase = "running"
        backend.chatChanged.emit()
        window.setProperty("page", "settings")
        QTest.qWait(100)
        QTest.keyClick(window, Qt.Key_B, Qt.ControlModifier)
        QTest.qWait(100)
        assert backend.sidebarCollapsed and main.x() == 0
        click("toggleSidebarButton")
        assert sidebar.width() == 346 and sidebar.isVisible()
        assert backend._view is state and backend.running
        assert state.draft == "Unsent fixture draft" and len(state.messages) == 2
        state.phase = "idle"
        backend.chatChanged.emit()
        window.setProperty("page", "chat")
        click("toggleSidebarButton")
        assert backend.sidebarCollapsed
        assert not warnings, "\n".join(warnings)
        backend.close()
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--check-restore"],
                                capture_output=True, text=True, timeout=20, cwd=ROOT)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "SIDEBAR_RESTORE_OK" in result.stdout
        print("SIDEBAR_UI_OK: pointer resize, bounds, responsive width, collapse button, shortcut, active-task/draft preservation, restart")
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
