"""Verify actual QML hit targets dispatch all eight native resize directions."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('UMEKO_LANGUAGE','zh')
os.environ["UMEKO_DATA_DIR"] = tempfile.mkdtemp(prefix="umeko-window-resize-ui-")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
from PySide6.QtCore import QObject, Property, QPoint, Qt, Slot
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


class ResizeProbe(QObject):
    """Capture the OS request; offscreen Qt cannot perform system window drags."""
    def __init__(self):
        super().__init__()
        self.calls = []

    @Property(int, constant=True)
    def visibility(self): return 2  # QWindow.Windowed

    @Slot(int, result=bool)
    def startSystemResize(self, edges):
        self.calls.append(edges)
        return True


probe = ResizeProbe()

class MoveProbe(QObject):
    def __init__(self):
        super().__init__()
        self.state, self.calls, self.left, self.top = 4, [], 0.0, 0.0

    @Property(int)
    def visibility(self): return self.state

    @Property(float)
    def width(self): return 1320.0 if self.state == 4 else 1060.0

    @Property(float)
    def x(self): return self.left
    @x.setter
    def x(self, value): self.left = value

    @Property(float)
    def y(self): return self.top
    @y.setter
    def y(self, value): self.top = value

    @Slot()
    def showNormal(self): self.calls.append('restore'); self.state = 2

    @Slot(result=bool)
    def startSystemMove(self): self.calls.append('move'); return True

try:
    QTest.qWait(200)
    handles = find("windowResizeHandles")
    handles.setProperty("targetWindow", probe)
    cases = [
        ("left", Qt.LeftEdge, Qt.SizeHorCursor), ("right", Qt.RightEdge, Qt.SizeHorCursor),
        ("top", Qt.TopEdge, Qt.SizeVerCursor), ("bottom", Qt.BottomEdge, Qt.SizeVerCursor),
        ("topLeft", Qt.TopEdge | Qt.LeftEdge, Qt.SizeFDiagCursor),
        ("topRight", Qt.TopEdge | Qt.RightEdge, Qt.SizeBDiagCursor),
        ("bottomLeft", Qt.BottomEdge | Qt.LeftEdge, Qt.SizeBDiagCursor),
        ("bottomRight", Qt.BottomEdge | Qt.RightEdge, Qt.SizeFDiagCursor),
    ]
    for page in ("chat", "settings"):
        window.setProperty("page", page)
        window.resize(1060, 700)
        QTest.qWait(100)
        for name, edges, cursor in cases:
            target = find("windowResize_" + name)
            assert target.isEnabled() and target.property("cursorShape") == cursor
            # The corners must work well inside the previous 5-pixel border, too.
            point = target.mapToScene(target.boundingRect().center()).toPoint()
            QTest.mouseMove(window, point)
            QTest.qWait(20)
            assert target.property("containsMouse"), name
            before = len(probe.calls)
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
            assert probe.calls[before:] == [edges.value], (name, probe.calls)
        # Check the exact outer corner pixels as well as the enlarged inner targets.
        for point, edges in [(QPoint(1, 1), Qt.TopEdge | Qt.LeftEdge),
                             (QPoint(window.width()-2, 1), Qt.TopEdge | Qt.RightEdge),
                             (QPoint(1, window.height()-2), Qt.BottomEdge | Qt.LeftEdge),
                             (QPoint(window.width()-2, window.height()-2), Qt.BottomEdge | Qt.RightEdge)]:
            before = len(probe.calls)
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
            assert probe.calls[before:] == [edges.value]
    window.setProperty("page", "chat")
    prompt = find("promptInput")
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, prompt.mapToScene(prompt.boundingRect().center()).toPoint())
    QTest.keyClick(window, Qt.Key_A)
    assert prompt.property("text").lower() == "a"
    handles.setProperty("targetWindow", window)
    window.showMaximized(); QTest.qWait(100)
    assert not handles.isEnabled()
    window.showFullScreen(); QTest.qWait(100)
    assert not handles.isEnabled()
    window.showNormal(); QTest.qWait(100)
    assert handles.isEnabled()
    # Native movement is delegated only after Qt has restored maximized state.
    move_probe = MoveProbe()
    title = find('mainTitleDrag')
    title.setProperty('targetWindow', move_probe)
    point = title.mapToScene(title.boundingRect().center()).toPoint()
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, point)
    assert not move_probe.calls
    QTest.mouseMove(window, point + QPoint(50, 0))
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, point + QPoint(50, 0))
    assert move_probe.calls == ['restore', 'move'], move_probe.calls
    title.setProperty('targetWindow', window)
    # A preview must not reduce the conversation below its usable width.
    pane = find('webPane')
    sidebar_width = backend.sidebarWidth
    window.resize(1060, 700)
    pane.setProperty('mode', 'document')
    pane.setProperty('opened', True)
    QTest.qWait(1200)
    assert find('chatPage').width() >= 639
    assert pane.width() >= 319
    assert window.property('previewSidebarCollapsed')
    assert not backend.sidebarCollapsed and backend.sidebarWidth == sidebar_width
    # Native browser child windows leave the splitter and outer resize targets free.
    surface = find('webSurfaceLoader')
    assert surface.x() >= 6 and pane.width() - surface.x() - surface.width() >= 11
    pane.setProperty('opened', False)
    QTest.qWait(1000)
    assert not window.property('previewSidebarCollapsed')
    assert find('mainArea').x() > 100
    # Closing the model popup restores typing immediately, including during exit.
    window.resize(1320, 860)
    selector = find('modelSelector')
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, selector.mapToScene(selector.boundingRect().center()).toPoint())
    QTest.qWait(900)
    assert find('modelSearch').hasActiveFocus()
    QTest.keyClick(window, Qt.Key_Escape)
    QTest.qWait(80)
    assert prompt.hasActiveFocus()
    QTest.keyClick(window, Qt.Key_B)
    assert prompt.property('text').lower() == 'ab'
    assert not warnings, "\n".join(warnings)
    print("WINDOW_RESIZE_UI_OK: eight directions, restore, preview width and temporary sidebar collapse, native web insets, popup typing focus")
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
