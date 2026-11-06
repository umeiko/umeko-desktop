"""Observe the real composer's IMM coordinates on a Windows CI desktop only.

Key events stay inside Qt. WM_IME_START/ENDCOMPOSITION are synchronously
dispatched to this process's own HWND to exercise QWindowsInputContext without
depending on a particular installed keyboard or injecting OS keyboard input.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
NATIVE_CI = (sys.platform == "win32" and os.environ.get("GITHUB_ACTIONS") == "true"
             and os.environ.get("RUNNER_OS") == "Windows"
             and os.environ.get("UMEKO_NATIVE_IME_TEST") == "1")


def run_native():
    if not NATIVE_CI:
        raise RuntimeError("Native IME regression runs only on the Windows CI desktop")
    import ctypes
    from ctypes import wintypes

    os.environ.update(QT_QPA_PLATFORM="windows", QT_QUICK_BACKEND="software",
                      QT_QUICK_CONTROLS_STYLE="Basic", UMEKO_IME_TRACE="1")
    sys.path.insert(0, str(ROOT))
    from PySide6.QtCore import QCoreApplication, QEvent, QPointF, QRectF, Qt, QUrl, qVersion
    from PySide6.QtGui import QGuiApplication, QInputMethodEvent, QKeyEvent
    from PySide6.QtQml import QQmlComponent
    from PySide6.QtQuick import QQuickItem, QQuickView
    from PySide6.QtTest import QTest
    from shiboken6 import delete
    from app.input_method import InputMethodUpdates

    class CompositionForm(ctypes.Structure):
        _fields_ = [("style", wintypes.DWORD), ("point", wintypes.POINT), ("area", wintypes.RECT)]

    class CandidateForm(ctypes.Structure):
        _fields_ = [("index", wintypes.DWORD), ("style", wintypes.DWORD),
                    ("point", wintypes.POINT), ("area", wintypes.RECT)]

    imm = ctypes.WinDLL("imm32", use_last_error=True)
    imm.ImmGetContext.argtypes = [wintypes.HWND]
    imm.ImmGetContext.restype = wintypes.HANDLE
    imm.ImmReleaseContext.argtypes = [wintypes.HWND, wintypes.HANDLE]
    imm.ImmGetCompositionWindow.argtypes = [wintypes.HANDLE, ctypes.POINTER(CompositionForm)]
    imm.ImmGetCandidateWindow.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(CandidateForm)]
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.SendMessageW.restype = ctypes.c_ssize_t

    with tempfile.TemporaryDirectory(prefix="umeko-native-ime-") as folder:
        os.environ["UMEKO_DATA_DIR"] = str(Path(folder) / "profile")
        os.environ["PI_CODING_AGENT_DIR"] = str(Path(folder) / "agent")
        app = QGuiApplication([])
        assert app.platformName() == "windows", app.platformName()
        updates = InputMethodUpdates(app)
        view = QQuickView()
        view.setResizeMode(QQuickView.SizeRootObjectToView)
        engine = view.engine()
        # Real Composer.qml, with a quiet data-only backend: no profiles,
        # runtime workers, accounts, tray, model calls or notifications.
        backend_component = QQmlComponent(engine)
        fixture_url = QUrl.fromLocalFile(str(ROOT / "tests/fixtures/native-ime.qml"))
        backend_component.setData(b'''import QtQuick
QtObject {
    property real fontScale: 1
    property string language: "zh"
    property string lineSpacing: "standard"
    property var config: ({theme: "white", fontFamily: "", providers: [],
        selectedProvider: "", selectedModel: "", workspace: "", agent: {toolPermissionMode: "auto"}})
    property var themeStyle: ({base: "white", colors: {}})
    property var attachments: []
    property var queuedMessages: []
    property var contextUsage: ({})
    property var turnStatus: ({})
    property var slashCommands: ({entries: []})
    property string reasoningEffort: "off"
    property bool dangerousAllowed: false
    property bool compacting: false
    property bool loading: false
    property bool running: false
    property bool kernelBusy: false
    property bool busy: false
    property bool compactionAvailable: false
    property string activeSession: ""
    signal editorText(string text)
    signal viewChanged()
    function setDraft(text) {}
}''', fixture_url)
        assert backend_component.isReady(), [e.toString() for e in backend_component.errors()]
        backend = backend_component.create()
        engine.rootContext().setContextProperty("backend", backend)
        component = QQmlComponent(engine)
        qml_dir = QUrl.fromLocalFile(str(ROOT / "app/qml")).toString()
        component.setData(('''import QtQuick
import "%s" as Umeko
Item { Umeko.Composer { x: 24; width: parent.width - 48
    anchors.bottom: parent.bottom; anchors.bottomMargin: 24 } }
''' % qml_dir).encode(), fixture_url)
        assert component.isReady(), [e.toString() for e in component.errors()]
        root = component.create()
        view.setContent(fixture_url, component, root)
        view.resize(840, 440)
        view.show()
        view.requestActivate()
        prompt = root.findChild(QQuickItem, "promptInput")
        assert prompt is not None
        prompt.forceActiveFocus()
        assert QTest.qWaitForWindowActive(view, 5000), "CI native window never activated"
        QTest.qWait(150)
        assert app.focusObject() == prompt, "Composer does not have Qt keyboard focus"
        hwnd = int(view.winId())
        failures = []

        def key(code, text, modifiers=Qt.NoModifier):
            for kind in (QEvent.KeyPress, QEvent.KeyRelease):
                QCoreApplication.sendEvent(prompt, QKeyEvent(kind, code, modifiers, text))

        def snapshot(label):
            # Ground truth is the real editor's rectangle mapped through its
            # visual tree, independently of QInputMethod's cached transform.
            local = prompt.property("cursorRectangle")
            origin = prompt.mapToScene(QPointF(local.x(), local.y()))
            dpr = view.devicePixelRatio()
            native = QRectF(origin.x() * dpr, origin.y() * dpr,
                            local.width() * dpr, local.height() * dpr).toRect()
            expected = [native.x(), native.y(), native.width(), native.height()]
            context = imm.ImmGetContext(hwnd)
            assert context, "CI window has no IMM context"
            try:
                composition, candidate = CompositionForm(), CandidateForm()
                got_composition = bool(imm.ImmGetCompositionWindow(context, ctypes.byref(composition)))
                got_candidate = bool(imm.ImmGetCandidateWindow(context, 0, ctypes.byref(candidate)))
                row = dict(scenario=label, qt=qVersion(), dpr=dpr, expected=expected,
                           composition=[composition.style, composition.point.x, composition.point.y],
                           candidate=[candidate.style, candidate.point.x, candidate.point.y,
                                      candidate.area.left, candidate.area.top,
                                      candidate.area.right, candidate.area.bottom],
                           readback=[got_composition, got_candidate])
            finally:
                imm.ImmReleaseContext(hwnd, context)
            print("IMM_POSITION " + json.dumps(row), flush=True)
            x, y, width, height = expected
            if (not all(row["readback"]) or row["composition"] != [0x20, x, y]
                    or row["candidate"] != [0x80, x, y + height, x, y, x + width, y + height]):
                failures.append(label)

        def composition_start():
            user.SendMessageW(hwnd, 0x010D, 0, 0)  # WM_IME_STARTCOMPOSITION, this HWND only

        def composition_end():
            user.SendMessageW(hwnd, 0x010E, 0, 0)  # WM_IME_ENDCOMPOSITION

        try:
            # Establish Qt's own previous composition position, never seed IMM
            # with an invented stale rectangle. Every later edit is a Qt event.
            composition_start()
            snapshot("empty-composition-start")
            composition_end()
            actions = [
                ("committed-text", lambda: key(Qt.Key_A, "a")),
                ("newline", lambda: key(Qt.Key_Return, "\r", Qt.ShiftModifier)),
                ("space", lambda: key(Qt.Key_Space, " ")),
            ]
            for label, action in actions:
                action()
                QTest.qWait(50)
                snapshot(label + "-before-composition")
                composition_start()
                snapshot(label + "-composition-start")
                composition_end()
            assert not failures, "IMM caret positions lagged: " + ", ".join(failures)
        finally:
            updates._pending.stop()
            view.close()
            delete(view)
            delete(updates)
            app.processEvents()
        print("IMM_POSITION native composer regression passed", flush=True)


class WindowsImePositionTests(unittest.TestCase):
    @unittest.skipUnless(NATIVE_CI, "Requires the Windows CI native desktop")
    def test_caret_reaches_imm_before_composition_after_text_newline_and_space(self):
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--native"],
                                cwd=ROOT, env=dict(os.environ), capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=60)
        print(result.stdout, end="", flush=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    if "--native" in sys.argv:
        run_native()
    else:
        unittest.main()
