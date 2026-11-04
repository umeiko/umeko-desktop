"""Geometry-only logging is opt-in and never serializes editor or event text."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QEvent, QObject, QRectF, Signal

from app.ime_trace import InputMethodTrace, native_rectangle


class Method(QObject):
    cursorRectangleChanged = Signal()
    anchorRectangleChanged = Signal()

    def cursorRectangle(self):
        return QRectF(1.1, 2.1, 1, 10)

    def anchorRectangle(self):
        return QRectF(21, 22, 1, 10)


class Screen:
    def name(self):
        return "display-1"


class Window:
    def devicePixelRatio(self):
        return 1.5

    def screen(self):
        return Screen()


class Application(QObject):
    focusObjectChanged = Signal(object)
    focusWindowChanged = Signal(object)

    def __init__(self):
        super().__init__()
        self.method = Method(self)
        self.editor = QObject(self)
        self.editor.setObjectName("private typed content")
        self.window = Window()

    def inputMethod(self):
        return self.method

    def focusObject(self):
        return self.editor

    def focusWindow(self):
        return self.window


class InputMethodTraceTests(unittest.TestCase):
    def test_disabled_does_not_create_log(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"UMEKO_DATA_DIR": folder, "UMEKO_IME_TRACE": "0"}):
                self.assertIsNone(InputMethodTrace.install(Application()))
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_each_rectangle_signal_appends_geometry_and_event_only(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"UMEKO_DATA_DIR": folder, "UMEKO_IME_TRACE": "1"}):
                app = Application()
                trace = InputMethodTrace.install(app)
                trace.eventFilter(app.editor, QEvent(QEvent.InputMethod))
                app.method.cursorRectangleChanged.emit()
                trace.note("queued-refresh")
                app.method.anchorRectangleChanged.emit()
                app.method.cursorRectangleChanged.emit()
                raw = trace.path.read_text(encoding="utf-8")
                rows = [json.loads(line) for line in raw.splitlines()]
                self.assertEqual(len(rows), 3)
                self.assertEqual([row["kind"] for row in rows], ["cursor", "anchor", "cursor"])
                self.assertEqual(rows[0]["logical"], [1.1, 2.1, 1, 10])
                self.assertEqual(rows[0]["native"], [2, 3, 1, 15])
                self.assertEqual(rows[0]["dpr"], 1.5)
                self.assertEqual(rows[0]["screen"], "display-1")
                self.assertEqual(rows[0]["event"], "InputMethod")
                self.assertEqual(rows[1]["event"], "queued-refresh")
                self.assertEqual(rows[0]["editor"], hex(id(app.editor)))
                self.assertEqual(set(rows[0]), {"time", "editor", "window", "kind", "logical", "native", "dpr", "screen", "event"})
                self.assertNotIn("private typed content", raw)
                self.assertEqual(trace.path, Path(folder) / "logs" / "ime-geometry.log")

    def test_windows_rounding_uses_origin_residual(self):
        # Independent component rounding would incorrectly give a 2px width.
        rect = native_rectangle(QRectF(1.1, 2.1, 1, 10), 1.5)
        self.assertEqual((rect.x(), rect.y(), rect.width(), rect.height()), (2, 3, 1, 15))


if __name__ == "__main__":
    unittest.main()
