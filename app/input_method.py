"""Publish the current editor's caret when keyboard focus changes."""
from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtQuick import QQuickItem, QQuickWindow
from shiboken6 import isValid


class InputMethodUpdates(QObject):
    """Keep queries current and publish after focus and layout changes.

    Qt can reuse an unchanged input-item transform without emitting a cursor
    rectangle signal. Windows input methods consume that signal, so querying a
    correct rectangle alone does not publish it after returning to an editor.
    This application-wide connection also covers editors loaded by Widgets.
    """

    def __init__(self, app):
        super().__init__(app)
        self._app = app
        from .ime_trace import InputMethodTrace
        self._trace = InputMethodTrace.install(app)
        self._syncing = False
        self._focus_editor = None
        self._items = ()
        self._connections = []
        self._pending = QTimer(self)
        self._pending.setSingleShot(True)
        self._pending.setInterval(0)
        self._pending.timeout.connect(self._update)
        app.focusObjectChanged.connect(self._focus_changed)
        app.focusWindowChanged.connect(self._schedule)
        self._focus_changed()

    def _focus_changed(self, *_):
        previous = self._focus_editor
        self._focus_editor = None
        if previous is not None and isValid(previous):
            previous.removeEventFilter(self)
        focus = self._app.focusObject()
        if (isinstance(focus, QQuickItem) and isValid(focus)
                and focus.flags() & QQuickItem.ItemAcceptsInputMethod):
            focus.installEventFilter(self)
            self._focus_editor = focus
        self._schedule()

    def _schedule(self, *_):
        self._pending.start()

    def eventFilter(self, receiver, event):
        if (event.type() == QEvent.InputMethodQuery
                and event.queries() & (Qt.ImCursorRectangle | Qt.ImAnchorRectangle)
                and receiver == self._app.focusObject()):
            self._synchronize_transform(receiver, self._app.focusWindow())
        return False

    def _synchronize_transform(self, focus, window):
        if (self._syncing or not isinstance(window, QQuickWindow) or not isinstance(focus, QQuickItem)
                or not focus.flags() & QQuickItem.ItemAcceptsInputMethod):
            return False
        root = window.contentItem()
        ancestor = focus
        while ancestor is not None and ancestor != root:
            ancestor = ancestor.parentItem()
        if ancestor != root:
            return False
        # Qt Quick may publish a cursor change before its next polish pass
        # updates inputItemTransform. QInputMethod sends the query event before
        # mapping its result, so update the transform before that mapping, too.
        # Use the focus window: item.window() can alter Python ownership.
        # itemTransform(other) reports success even for separate windows. The
        # ancestry check prevents a queued old-editor/new-window combination.
        # None includes the scene root's transform, like Qt's own updater.
        transform, valid = focus.itemTransform(None)
        if not valid:
            return False
        method = self._app.inputMethod()
        if transform != method.inputItemTransform():
            if self._trace is not None:
                self._trace.note("transform-sync")
            # setInputItemTransform stores the new value before emitting its
            # rectangle signals. Nested queries therefore use the new value.
            self._syncing = True
            try:
                method.setInputItemTransform(transform)
            finally:
                self._syncing = False
        return True

    def _update(self):
        # Read the current focus, rather than retaining a potentially deleted
        # delegate or an editor from the previously active window.
        focus = self._app.focusObject()
        editor = (isinstance(focus, QQuickItem)
                  and bool(focus.flags() & QQuickItem.ItemAcceptsInputMethod))
        items = []
        item = focus if editor else None
        while isinstance(item, QQuickItem):
            items.append(item)
            item = item.parentItem()
        items = tuple(items)
        if items != self._items:
            for connection in self._connections:
                QObject.disconnect(connection)
            self._connections.clear()
            self._items = items
            # Flickable scrolls move its contentItem. Observe the visual parent
            # chain as well as the editor, including reparenting into popups.
            for item in items:
                for signal in (item.xChanged, item.yChanged, item.widthChanged,
                               item.heightChanged, item.scaleChanged,
                               item.rotationChanged, item.transformOriginChanged,
                               item.parentChanged):
                    self._connections.append(signal.connect(self._schedule))
        window = self._app.focusWindow()
        if window is None or not editor:
            return
        input_method = self._app.inputMethod()
        if self._trace is not None:
            self._trace.note("queued-refresh")
        if not self._synchronize_transform(focus, window):
            return
        input_method.update(Qt.ImCursorRectangle | Qt.ImAnchorRectangle | Qt.ImEnabled)
