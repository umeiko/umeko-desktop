"""Opt-in geometry-only input-method diagnostics; never inspect input text."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QRectF

from .platform_support import data_directory


def native_rectangle(rectangle, factor):
    """Mirror Qt 6.10.2 QWindowsInputContext::cursorRectChanged (client pixels).

    cursorRectangle is already window-local. Windows scales all four values,
    then uses QRectF::toRect, including its origin-dependent size rounding:
    qtbase/src/plugins/platforms/windows/qwindowsinputcontext.cpp, lines 265-307.
    """
    return QRectF(rectangle.x() * factor, rectangle.y() * factor,
                  rectangle.width() * factor, rectangle.height() * factor).toRect()


def _values(rectangle):
    return [rectangle.x(), rectangle.y(), rectangle.width(), rectangle.height()]


class InputMethodTrace(QObject):
    """Append rectangle signals to the profile's logs/ime-geometry.log.

    Native pixels are the source-derived Windows IMM client coordinates, even
    on other Qt platforms. This observes Qt publications, not an IME's final
    candidate-window placement. Event names describe the latest relevant Qt
    event, or the application's explicit queued refresh.
    """

    _events = frozenset((QEvent.InputMethod, QEvent.FocusIn, QEvent.FocusOut,
                         QEvent.Move, QEvent.Resize, QEvent.LayoutRequest,
                         QEvent.Show, QEvent.Hide, QEvent.WindowActivate,
                         QEvent.WindowDeactivate, QEvent.ScreenChangeInternal,
                         QEvent.DevicePixelRatioChange))

    @classmethod
    def install(cls, app):
        if os.environ.get("UMEKO_IME_TRACE") != "1":
            return None
        return cls(app)

    def __init__(self, app):
        super().__init__(app)
        self._app = app
        profile = Path(os.environ["UMEKO_DATA_DIR"]) if os.environ.get("UMEKO_DATA_DIR") else data_directory()
        self.path = profile / "logs" / "ime-geometry.log"
        self._event = "startup"
        self._failed = False
        app.installEventFilter(self)
        app.focusObjectChanged.connect(lambda *_: self.note("focusObjectChanged"))
        app.focusWindowChanged.connect(lambda *_: self.note("focusWindowChanged"))
        method = app.inputMethod()
        method.cursorRectangleChanged.connect(lambda: self._record("cursor"))
        method.anchorRectangleChanged.connect(lambda: self._record("anchor"))

    def note(self, event):
        self._event = event

    def eventFilter(self, receiver, event):
        if event.type() in self._events:
            self.note(event.type().name)
        return False

    def _record(self, kind):
        if self._failed:
            return
        app = self._app
        method = app.inputMethod()
        rectangle = method.cursorRectangle() if kind == "cursor" else method.anchorRectangle()
        window = app.focusWindow()
        factor = window.devicePixelRatio() if window is not None else None
        screen = window.screen() if window is not None else None
        focus = app.focusObject()
        record = dict(time=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                      editor=hex(id(focus)) if focus is not None else None,
                      window=hex(id(window)) if window is not None else None,
                      kind=kind, logical=_values(rectangle),
                      native=_values(native_rectangle(rectangle, factor)) if factor is not None else None,
                      dpr=factor, screen=screen.name() if screen is not None else None,
                      event=self._event)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")
        except OSError:
            # An unavailable diagnostic destination must not break typing.
            self._failed = True
