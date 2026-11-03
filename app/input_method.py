"""Publish the current editor's caret when keyboard focus changes."""
from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtQuick import QQuickItem


class InputMethodUpdates(QObject):
    """Refresh after Qt Quick has finished forwarding focus and laying out items.

    Qt can reuse an unchanged input-item transform without emitting a cursor
    rectangle signal. Windows input methods consume that signal, so querying a
    correct rectangle alone does not publish it after returning to an editor.
    This application-wide connection also covers editors loaded by Widgets.
    """

    def __init__(self, app):
        super().__init__(app)
        self._app = app
        self._items = ()
        self._connections = []
        self._pending = QTimer(self)
        self._pending.setSingleShot(True)
        self._pending.setInterval(0)
        self._pending.timeout.connect(self._update)
        app.focusObjectChanged.connect(self._schedule)
        app.focusWindowChanged.connect(self._schedule)

    def _schedule(self, *_):
        self._pending.start()

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
        # Use the application's focus window. QQuickItem.window() can attach
        # the window wrapper to the item in Python's ownership graph.
        transform, valid = focus.itemTransform(window.contentItem())
        if valid:
            # update() only publishes queries; it does not refresh a cached
            # transform when a ScrollView moves before the next scene sync.
            input_method.setInputItemTransform(transform)
        input_method.update(Qt.ImCursorRectangle | Qt.ImAnchorRectangle | Qt.ImEnabled)
