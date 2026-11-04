"""Offscreen, synchronous input-method publications from real application QML.

``python -m unittest tests.test_input_method_geometry`` uses an isolated process
so legacy discovery's QCoreApplication cannot replace QApplication. The explicit
``--trace --output PATH`` entry point records geometry only, including transient
signals; ``--source-root`` lets exactly the same harness run a git-archive export.
No OS keyboard/IME injection, plugin workers, model calls, tray or notifications.
"""
from __future__ import annotations

from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ("composer-preedit", "composer-commit", "composer-enter",
            "multiline-wrap", "toolbar-reflow", "attachment-layout", "composer-scroll",
            "streamed-reply", "session-switch", "model-popup", "focus-churn",
            "sidebar-geometry", "widget-panel-geometry", "window-geometry", "widget-preedit")


def run_trace(source_root=ROOT, output=None, exhaustive=False):
    """Return every publication synchronously, not a later reconstruction."""
    source_root = Path(source_root).resolve()
    sys.path.insert(0, str(source_root))
    os.environ.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                      QT_QUICK_CONTROLS_STYLE="Basic", UMEKO_LANGUAGE="zh")
    from PySide6.QtCore import QObject, Property, QCoreApplication, QEvent, QMetaObject, QRectF, Qt, QUrl, Signal, Slot, qVersion
    from PySide6.QtGui import QInputMethodEvent, QKeyEvent
    from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression
    from PySide6.QtQuick import QQuickItem, QQuickView, QQuickWindow
    from shiboken6 import delete

    class QuietTray(QObject):
        quitRequested = Signal()
        notificationRequested = Signal(str)
        def __init__(self, window, icon, parent):
            super().__init__(parent)
            self.tray = None
        def set_language(self, language): pass

    class QuietNotifications(QObject):
        activated = Signal(str)
        def __init__(self, window, tray, root, parent): super().__init__(parent)
        @Slot(str, str, bool, bool)
        def task_finished(self, *args): pass

    class EditorSdk(QObject):
        hostResponse = Signal(str, "QVariantMap")
        activeChanged = Signal()
        languageChanged = Signal()
        @Property(bool, notify=activeChanged)
        def active(self): return False
        @Property(float, constant=True)
        def scale(self): return 1.
        @Property(str, notify=languageChanged)
        def language(self): return "en"
        @Property("QVariantMap", constant=True)
        def hostCapabilities(self): return {"operations": {}}
        @Property("QVariantMap", constant=True)
        def colors(self):
            return dict(surface="#202521", bg="#181d19", ink="#e4e9e3", muted="#929e94",
                        accent="#9cc69f", accentBg="#334636", hover="#29362b", line="#465148")

    class ExactFixtureBytes:
        """Exact bytes in place of unused profile identity digests; no hashing."""
        def __init__(self, value): self.value = value
        def digest(self): return self.value
        def hexdigest(self): return self.value.hex()

    def descendants(item):
        yield item
        for child in item.childItems():
            yield from descendants(child)

    def find(name, root):
        return next(item for item in descendants(root) if item.objectName() == name)

    def evaluate(root, source):
        expression = QQmlExpression(QQmlEngine.contextForObject(root), root, source)
        result = expression.evaluate()
        if expression.hasError(): raise AssertionError(expression.error().toString())
        return result[0]

    def values(rect): return [rect.x(), rect.y(), rect.width(), rect.height()]
    def delta(a, b): return max(abs(x-y) for x, y in zip(a, b))

    sandbox = tempfile.TemporaryDirectory(prefix="umeko-ime-geometry-")
    os.environ["UMEKO_DATA_DIR"] = str(Path(sandbox.name) / "profile")
    os.environ["PI_CODING_AGENT_DIR"] = str(Path(sandbox.name) / "agent")
    from app.storage import Store
    # These isolated fixtures have no credentials, projects or user files.
    # Skip bundled-file verification entirely and retain exact bytes for the
    # storage-only namespace/empty-secret cache; no digest/checksum executes.
    no_digest = SimpleNamespace(sha256=ExactFixtureBytes)
    patches = ExitStack()
    patches.enter_context(patch("app.storage.hashlib", no_digest))
    patches.enter_context(patch("app.bundled_skills.install_bundled", lambda *args: None))
    patches.enter_context(patch("app.tray.TrayController", QuietTray))
    patches.enter_context(patch("app.notifications.TaskNotifications", QuietNotifications))
    patches.enter_context(patch("app.controller.Controller.loadNativeIndex", lambda self: None))
    patches.enter_context(patch("app.desktop_plugins.DesktopPlugins.start", lambda *args: None))
    seed = Store()
    seed.data["agent"]["agentDir"] = str(Path(sandbox.name) / "agent")
    seed.data["desktop"]["webDisplay"] = "external"
    seed.save()
    from main import create_application
    app, engine, backend = create_application()
    window = engine.rootObjects()[0]
    im = app.inputMethod()
    events, observations, failures, callback_errors = [], [], [], []
    patches.enter_context(patch.object(sys, "excepthook", lambda kind, value, tb: callback_errors.append(str(value))))
    state = {"scenario": "initial", "fontScale": 1., "phase": "sync", "capturing": True}
    roots, extra_windows = [window.contentItem()], []
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))

    def native(rect, dpr):
        # qwindowsinputcontext.cpp cursorRectChanged: the logical rectangle
        # already belongs to the window; use QRectF::toRect's actual rounding.
        r = QRectF(rect[0]*dpr, rect[1]*dpr, rect[2]*dpr, rect[3]*dpr).toRect()
        return {"rect": [r.x(), r.y(), r.width(), r.height()],
                "composition": [r.x(), r.y()], "candidate": [r.x(), r.y()+r.height()],
                "exclusion": [r.x(), r.y(), r.x()+r.width(), r.y()+r.height()]}

    def snapshot(kind):
        focus, focus_window = app.focusObject(), app.focusWindow()
        editor = isinstance(focus, QQuickItem) and bool(focus.flags() & QQuickItem.ItemAcceptsInputMethod)
        row = {"n": len(events), "kind": kind, **state,
               "focus": focus.objectName() if isinstance(focus, QObject) else "",
               "window": focus_window.objectName() if focus_window else "",
               "logical": values(im.cursorRectangle()), "anchor": values(im.anchorRectangle())}
        row.pop("capturing")
        if editor and focus_window:
            visual_root = focus
            while visual_root.parentItem() is not None: visual_root = visual_root.parentItem()
            row["rootMatchesFocusWindow"] = isinstance(focus_window, QQuickWindow) and visual_root == focus_window.contentItem()
            caret = focus.property("cursorRectangle")
            query = focus.inputMethodQuery(Qt.ImCursorRectangle)
            # Qt's window transform includes the content root's own transform.
            # Mapping to contentItem instead would cancel a nonidentity root.
            mapped = focus.mapRectToScene(caret)
            mapped_query = focus.mapRectToScene(query)
            anchor_query = focus.mapRectToScene(focus.inputMethodQuery(Qt.ImAnchorRectangle))
            expected = values(mapped)
            dpr = focus_window.devicePixelRatio()
            row.update(editor=True, expected=expected, query=values(mapped_query), local=values(caret),
                       expectedAnchor=values(anchor_query), anchorError=delta(row["anchor"], values(anchor_query)),
                       dpr=dpr, native=native(row["logical"], dpr), expectedNative=native(expected, dpr),
                       composing=bool(focus.property("inputMethodComposing")),
                       logicalError=delta(row["logical"], expected), queryError=delta(values(mapped_query), expected))
            # A TextArea's cursorRectangle is QQuickTextControl's preedit-aware
            # caret. Record QTextLayout's preedit separately to establish that
            # this is live composition, never positionToRectangle(cursorPosition).
            doc_wrapper = focus.property("textDocument")
            if doc_wrapper is not None and hasattr(doc_wrapper, "textDocument"):
                doc = doc_wrapper.textDocument()
                block = doc.findBlock(int(focus.property("cursorPosition")))
                layout = block.layout()
                row["preeditLength"] = len(layout.preeditAreaText()) if layout else 0
                row["preeditPosition"] = layout.preeditAreaPosition() if layout else -1
        else:
            row["editor"] = False
        return row

    def record(kind, flags=None):
        if state["capturing"]:
            # Queries can synchronously cause nested publications. Reserve
            # this event's position first, retaining signal-entry order.
            position = len(events)
            row = {}
            events.append(row)
            row.update(snapshot(kind))
            row["n"] = position
            if flags is not None: row["flags"] = flags.value

    im.cursorRectangleChanged.connect(lambda: record("cursor-signal", Qt.ImCursorRectangle))
    im.anchorRectangleChanged.connect(lambda: record("anchor-signal", Qt.ImAnchorRectangle))
    original_update = im.update
    def update(flags):
        record("python-update-before", flags)
        original_update(flags)
        record("python-update-after", flags)
    patches.enter_context(patch.object(im, "update", update))

    def settle():
        # Explicitly flush queued turns and polish. No sleep, frame, latency,
        # animation completion or wall-clock criterion participates in tests.
        state["phase"] = "flush"
        for _ in range(3):
            for root in roots:
                for item in descendants(root): item.ensurePolished()
            QCoreApplication.sendPostedEvents()
            app.processEvents()
        state["phase"] = "settled"

    def observe(label, require_editor=True):
        row = snapshot("observation")
        row["label"] = label
        observations.append(row)
        if require_editor and not row["editor"]:
            failures.append({"label": label, "reason": "no active editor", "focus": row["focus"]})
        elif row["editor"] and row["logicalError"] > 1.:
            failures.append({"label": label, "reason": "settled cursor differs from live caret", "record": row})
        return row

    def step(label, action, require_editor=True):
        state.update(scenario=label, phase="sync")
        action()
        settle()
        return observe(label, require_editor)

    def focus(item, win=window):
        win.requestActivate()
        item.forceActiveFocus()

    def preedit(item, text):
        attrs = [QInputMethodEvent.Attribute(QInputMethodEvent.Cursor, len(text), 1, None)]
        QCoreApplication.sendEvent(item, QInputMethodEvent(text, attrs))

    def commit(item, text):
        event = QInputMethodEvent()
        event.setCommitString(text)
        QCoreApplication.sendEvent(item, event)

    def key(item, key_value, text="", modifiers=Qt.NoModifier):
        QCoreApplication.sendEvent(item, QKeyEvent(QEvent.KeyPress, key_value, modifiers, text))
        QCoreApplication.sendEvent(item, QKeyEvent(QEvent.KeyRelease, key_value, modifiers, text))

    def composer_scroll(prompt):
        scroll = prompt.parentItem()
        while scroll.property("contentY") is None: scroll = scroll.parentItem()
        scroll.setProperty("contentY", float(scroll.property("contentY")) + 12)

    try:
        # Input events arrive directly at Qt objects in this process. Prevent
        # application send from ever starting a model/runtime worker.
        sent = []
        patches.enter_context(patch.object(type(backend), "send", lambda self, text: sent.append(text) or True))
        window.requestActivate()
        settle()
        prompt = find("promptInput", window.contentItem())
        composer = find("composer", window.contentItem())
        # Isolated host ensures unrelated Main PID motion cannot accidentally
        # hide a missing publication in the fixed-transform focus regression.
        host = QQuickView()
        host.setObjectName("fixedComposerWindow")
        host.engine().rootContext().setContextProperty("backend", backend)
        host.setResizeMode(QQuickView.SizeRootObjectToView)
        component = QQmlComponent(host.engine())
        host_url = QUrl.fromLocalFile(str(source_root / "tests/fixtures/geometry.qml"))
        qml_dir = QUrl.fromLocalFile(str(source_root / "app/qml")).toString()
        component.setData(('''import QtQuick
import "%s" as Umeko
Item { Umeko.Composer { objectName: "fixedComposer"; x: 20; width: parent.width - 40
anchors.bottom: parent.bottom; anchors.bottomMargin: 20 } }''' % qml_dir).encode(), host_url)
        if not component.isReady(): raise AssertionError([e.toString() for e in component.errors()])
        host.setContent(host_url, component, component.create())
        host.resize(840, 400)
        host.show()
        roots.append(host.rootObject()); extra_windows.append(host)
        fixed = find("promptInput", host.rootObject())
        step("fixed-composer-first-focus", lambda: focus(fixed, host))
        step("fixed-composer-blur", lambda: fixed.setFocus(False), require_editor=False)
        before = len(events)
        step("fixed-composer-refocus", lambda: focus(fixed, host))
        publications = [e for e in events[before:] if e["kind"] == "cursor-signal"]
        if not publications: failures.append({"label": "fixed-composer-refocus", "reason": "no cursor publication after focus"})
        step("fixed-composer-preedit", lambda: preedit(fixed, "nihao"))
        step("fixed-composer-resize", lambda: host.resize(740, 520))
        def fixed_scroll():
            commit(fixed, "")
            fixed.setProperty("text", "line\n" * 20)
            fixed.setProperty("cursorPosition", 20)
            preedit(fixed, "nihao")
        step("fixed-composer-multiline", fixed_scroll)
        step("fixed-composer-scroll", lambda: composer_scroll(fixed))
        step("fixed-composer-clear-preedit", lambda: commit(fixed, ""))
        step("scene-root-transform", lambda: (host.contentItem().setScale(1.25), host.contentItem().setRotation(3.)))
        step("scene-root-reset", lambda: (host.contentItem().setScale(1.), host.contentItem().setRotation(0.)))

        sdk = EditorSdk()
        widget = QQuickView()
        widget.setObjectName("widgetWindow")
        widget.engine().rootContext().setContextProperty("backend", backend)
        widget.setResizeMode(QQuickView.SizeRootObjectToView)
        widget.setInitialProperties({"sdk": sdk})
        widget.setSource(QUrl.fromLocalFile(str(source_root / "umeko-plugins/skill-manager/qml/Main.qml")))
        if widget.status() != QQuickView.Ready: raise AssertionError([e.toString() for e in widget.errors()])
        widget.resize(500, 700); widget.show()
        roots.append(widget.rootObject()); extra_windows.append(widget)
        widget_editor = find("skillManagerSearch", widget.rootObject())
        # This is a guard contract, not a claimed real-world repro: a query
        # filter must decline a foreign or detached item instead of assigning
        # its transform to another focus window. Old implementations lack the
        # helper, so baseline traces report this contract as unavailable.
        updates = getattr(app, "_input_method_updates", None)
        guard = {"available": hasattr(updates, "_synchronize_transform")}
        if guard["available"]:
            state["capturing"] = False
            unchanged = im.inputItemTransform()
            guard["foreignRejected"] = not updates._synchronize_transform(widget_editor, host)
            detached = QQuickItem()
            detached.setFlag(QQuickItem.ItemAcceptsInputMethod, True)
            guard["detachedRejected"] = not updates._synchronize_transform(detached, host)
            guard["unchanged"] = unchanged == im.inputItemTransform()
            delete(detached)
            state["capturing"] = True
            if not all(guard.values()): failures.append({"label": "foreign-root-guard", "reason": "foreign/detached input transform assigned", "guard": guard})

        scales = (.5, 1., 1.5, 2.) if exhaustive else (1.,)
        for font_scale in scales:
            state["fontScale"] = font_scale
            backend.store.data["ui"]["fontScale"] = font_scale
            backend.appearanceChanged.emit()
            step("composer-focus", lambda: (window.setProperty("page", "chat"), prompt.setProperty("text", ""),
                                            evaluate(window, "sidebarWidthMotion.snap()"), focus(prompt)))
            for syllable in ("n", "ni", "nihao", "nihaozhongguo"):
                row = step("composer-preedit", lambda s=syllable: preedit(prompt, s))
                if not row.get("composing"): failures.append({"label": "composer-preedit", "reason": "composition missing"})
            step("composer-commit", lambda: commit(prompt, "你好中国"))
            step("composer-typing", lambda: key(prompt, Qt.Key_A, "a"))
            step("composer-enter", lambda: key(prompt, Qt.Key_Return, "\r"))
            if not sent: failures.append({"label": "composer-enter", "reason": "Enter did not reach patched send"})

            def multiline():
                prompt.setProperty("text", "long wrapped line " * 16 + "\n" + "line\n" * 16)
                prompt.setProperty("cursorPosition", 21)
                preedit(prompt, "nihao")
            step("multiline-wrap", multiline)
            step("toolbar-reflow", lambda: (window.resize(820, 740), evaluate(window, "sidebarWidthMotion.snap()")))
            def attachments():
                backend._view.attachments = [{"id": "fixture", "kind": "file", "name": "fixture.txt", "path": "fixture.txt"}]
                backend.attachmentsChanged.emit()
            step("attachment-layout", attachments)
            step("composer-scroll", lambda: composer_scroll(prompt))
            def grow_messages():
                backend._view.messages = [{"role": "user", "text": "fixture question"}, {"role": "assistant", "text": "streamed reply\n"*20}]
                backend.chatChanged.emit()
                backend._view.messages[-1]["text"] += "more streamed text\n"*20
                backend.chatChanged.emit()
            step("streamed-reply", grow_messages)
            def switch_session():
                previous = backend._view
                alternate = backend._new_view()
                alternate.draft = "other session"
                backend._activate(alternate)
                backend._activate(previous)
                focus(prompt)
            step("session-switch", switch_session)
            def popup_focus():
                evaluate(window, "modelPopup.open()")
                find("modelSearch", window.contentItem()).forceActiveFocus()
            step("model-popup", popup_focus)
            step("model-popup-dismiss", lambda: (evaluate(window, "modelPopup.close()"), focus(prompt)))
            def churn():
                evaluate(window, "searchVisible = true; searchPane.focusSearch()")
                evaluate(window, 'sidebarMenus.target = {kind:"session", id:"fixture", title:""}; sidebarMenus.rename()')
                find("renameInput", window.contentItem()).forceActiveFocus()
                focus(widget_editor, widget)
                focus(fixed, host)
                focus(prompt)
                evaluate(window, "searchVisible = false")
                window.findChild(QObject, "renamePopup").close()
            step("focus-churn", churn)
            step("sidebar-geometry", lambda: (window.setProperty("sidebarPreferredWidth", 300), evaluate(window, "sidebarWidthMotion.snap()"), focus(prompt)))
            def panel_geometry():
                evaluate(window, 'webPane.mode = "plugin"; webPane.opened = true; webPane.preferredWidth = 320; webPane.snapWidth()')
            step("widget-panel-geometry", panel_geometry)
            step("widget-panel-close", lambda: evaluate(window, "webPane.opened = false; webPane.snapWidth()"))
            step("window-geometry", lambda: (window.setPosition(321, 219), window.resize(1280, 820), evaluate(window, "sidebarWidthMotion.snap()")))
            step("widget-focus", lambda: focus(widget_editor, widget))
            step("widget-preedit", lambda: preedit(widget_editor, "nihao"))
            step("widget-resize", lambda: widget.resize(600, 650))
            step("widget-commit", lambda: commit(widget_editor, "你好"))
            step("composer-return", lambda: focus(prompt))
            state.update(scenario="scenario-cleanup", phase="sync")
            commit(prompt, "")
            backend._view.attachments = []
            backend.attachmentsChanged.emit()

        # Negative capability probe: update is not invokable with this Qt
        # binding. Signals still observe cursor/anchor publications; Python
        # interception sees only Python refresh calls, never all C++ calls.
        before = len(events)
        state.update(scenario="native-slot-probe", phase="sync")
        probe_error = ""
        try:
            invoked = QMetaObject.invokeMethod(im, "update", Qt.DirectConnection,
                                              __import__("PySide6.QtCore", fromlist=["Q_ARG"]).Q_ARG("Qt::InputMethodQueries", Qt.ImCursorRectangle | Qt.ImAnchorRectangle))
        except (RuntimeError, TypeError) as error:
            invoked, probe_error = False, str(error)
        probe = events[before:]
        divergences = [e for e in events if e["kind"] == "cursor-signal" and e.get("editor") and e["rootMatchesFocusWindow"] and e["logicalError"] > 1.]
        anchor_divergences = [e for e in events if e["kind"] == "anchor-signal" and e.get("editor") and e["rootMatchesFocusWindow"] and e["anchorError"] > 1.]
        foreign_publications = [e for e in events if e["kind"].endswith("signal") and e.get("editor") and not e["rootMatchesFocusWindow"]]
        peak_bytes = None
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            class ProcessMemory(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            *[(name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]]
            memory = ProcessMemory()
            memory.cb = ctypes.sizeof(memory)
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetCurrentProcess.restype = wintypes.HANDLE
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            psapi.GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessMemory), wintypes.DWORD)
            if psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(memory), memory.cb):
                peak_bytes = memory.PeakWorkingSetSize
                if peak_bytes > 4*1024**3: failures.append({"label": "memory-budget", "reason": "own process peak exceeded 4 GiB", "peakWorkingSetBytes": peak_bytes})
        diagnostic = {"enabled": os.environ.get("UMEKO_IME_TRACE") == "1"}
        if diagnostic["enabled"]:
            log_path = Path(os.environ["UMEKO_DATA_DIR"]) / "logs/ime-geometry.log"
            diagnostic["exists"] = log_path.is_file()
            if diagnostic["exists"]:
                text = log_path.read_text(encoding="utf-8")
                lines = text.splitlines()
                records = [json.loads(line) for line in lines]
                expected_keys = {"time", "editor", "window", "kind", "logical", "native", "dpr", "screen", "event"}
                geometry_only = all(set(row) == expected_keys and row["kind"] in ("cursor", "anchor")
                                    and len(row["logical"]) == 4 and (row["native"] is None or len(row["native"]) == 4)
                                    for row in records)
                contains_preedit = any(word in text for word in ("nihao", "nihaozhongguo", "你好", "fixture question", "streamed reply"))
                diagnostic.update(lines=len(lines), maxLineBytes=max((len(line.encode("utf-8")) for line in lines), default=0),
                                  geometryOnly=geometry_only, containsSyntheticInput=contains_preedit,
                                  compact=all("\n" not in line and not line.startswith(" ") for line in lines))
                if output:
                    Path(output).parent.mkdir(parents=True, exist_ok=True)
                    Path(output).with_suffix(".ime.log").write_text(text, encoding="utf-8")
                if not lines or not geometry_only or contains_preedit or not diagnostic["compact"]:
                    failures.append({"label": "diagnostic-log", "reason": "diagnostic log contract failed", "diagnostic": diagnostic})
            else:
                failures.append({"label": "diagnostic-log", "reason": "enabled diagnostic did not create its profile log"})
        result = {"source": str(source_root), "qtVersion": qVersion(), "qtScale": os.environ.get("QT_SCALE_FACTOR", "1"),
                  "fontScales": list(scales), "events": events, "observations": observations,
                  "failures": failures, "synchronousDivergences": divergences, "anchorDivergences": anchor_divergences,
                  "foreignRootGuard": guard, "foreignRootPublications": foreign_publications,
                  "peakWorkingSetBytes": peak_bytes, "callbackErrors": callback_errors, "diagnosticLog": diagnostic,
                  "nativeSlotProbe": {"invoked": bool(invoked), "signals": sum(e["kind"].endswith("signal") for e in probe),
                                      "pythonCalls": sum(e["kind"] == "python-update-before" for e in probe), "error": probe_error},
                  "coverage": sorted({o["label"] for o in observations}), "qmlWarnings": warnings,
                  "limits": ["Offscreen platform; Windows IMM/TSF, physical screens, real IME candidate rendering and OS focus are not exercised.",
                             "Ground truth is live preedit-aware TextArea/TextInput cursorRectangle mapped through the visual tree; QTextLayout preedit recorded when exposed. No independent glyph raster measurement.",
                             "All cursor/anchor signals captured synchronously; Python wrapper sees Python refresh only, not internal C++ update calls.",
                             "Sidebar/panel PID motion is snapped where geometry matters; animation speed is not a criterion."]}
        if output:
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
    finally:
        state["capturing"] = False
        backend.close()
        for extra in reversed(extra_windows):
            extra.close(); delete(extra)
        delete(window); delete(engine)
        app.processEvents()
        patches.close()
        sandbox.cleanup()


def assert_trace_geometry(case, trace):
    """The same geometry contract accepts live runs and rejects saved baselines."""
    case.assertFalse(trace.get("callbackErrors", []), trace.get("callbackErrors"))
    # Check publications before settled observations: an eventual correction
    # cannot retract a transient cursor rectangle already delivered to an IME.
    case.assertFalse(trace["synchronousDivergences"], trace["synchronousDivergences"][:3])
    case.assertFalse(trace["anchorDivergences"], trace["anchorDivergences"][:3])
    case.assertFalse(trace["failures"], trace["failures"])
    case.assertTrue(set(REQUIRED).issubset(trace["coverage"]))
    case.assertTrue(any(e.get("composing") for e in trace["events"]))
    case.assertTrue(any(e["kind"] == "cursor-signal" for e in trace["events"]))
    case.assertTrue(any(e["kind"] == "anchor-signal" for e in trace["events"]))
    case.assertTrue(all(e.get("queryError", 0.) <= 1. for e in trace["events"]))


class InputMethodGeometryTests(unittest.TestCase):
    def test_live_caret_publication_and_preedit_geometry(self):
        # All GUI imports and QApplication construction stay in the child.
        with tempfile.TemporaryDirectory(prefix="umeko-ime-test-") as temp:
            path = Path(temp) / "trace.json"
            env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", QT_SCALE_FACTOR="1")
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--trace", "--output", str(path)],
                                    cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                    timeout=90, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            trace = json.loads(path.read_text(encoding="utf-8"))
        assert_trace_geometry(self, trace)


if __name__ == "__main__":
    if "--trace" in sys.argv:
        def arg(name, default=None):
            return sys.argv[sys.argv.index(name)+1] if name in sys.argv else default
        trace = run_trace(arg("--source-root", ROOT), arg("--output"), "--exhaustive" in sys.argv)
        print(json.dumps({"events": len(trace["events"]), "observations": len(trace["observations"]),
                          "failures": len(trace["failures"]), "divergences": len(trace["synchronousDivergences"]),
                          "nativeSlotProbe": trace["nativeSlotProbe"]}), flush=True)
    else:
        unittest.main()
