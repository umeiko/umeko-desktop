import QtQuick
import QtQuick.Controls
import QtQuick.Window

Popup {
    id: root
    property bool desiredOpen: false
    property real fullWidth: 365
    property real fullHeight: 300
    property bool openBelow: false
    property bool alignRight: false
    readonly property bool animating: motion.moving
    readonly property real buttonWidth: parent ? parent.width : 180
    readonly property real buttonHeight: parent ? parent.height : 31
    property point anchorPosition: Qt.point(0,0)
    property bool resetBeforeOpen: true
    property rect collapsedRect: Qt.rect(0,openBelow ? buttonHeight+8 : -buttonHeight-8,buttonWidth,buttonHeight)
    readonly property var anchorWindow: parent ? parent.Window.window : null
    function refreshAnchor() { anchorPosition = parent && Overlay.overlay ? parent.mapToItem(Overlay.overlay,0,0) : Qt.point(0,0) }
    readonly property real expandedWidth: Math.max(1, Math.min(fullWidth, Overlay.overlay ? Overlay.overlay.width - 24 : fullWidth))
    readonly property real expandedHeight: Math.max(1, Math.min(fullHeight, Overlay.overlay ? (openBelow ? Overlay.overlay.height-anchorPosition.y-buttonHeight-20 : anchorPosition.y-20) : fullHeight))
    readonly property real openX: Math.max(12-anchorPosition.x, Math.min(alignRight ? buttonWidth-expandedWidth : 0, (Overlay.overlay ? Overlay.overlay.width : fullWidth)-12-anchorPosition.x-expandedWidth))
    readonly property real contentOpacity: Math.max(0, Math.min(1, ((height-buttonHeight)/Math.max(1,expandedHeight-buttonHeight)-0.15)/0.65))
    function toggle() { if (desiredOpen) close(); else open() }
    width: Math.max(1,motion.value.width); height: Math.max(1,motion.value.height)
    x: motion.value.x; y: motion.value.y
    margins: 12; padding: 10; focus: true
    closePolicy: desiredOpen ? Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent : Popup.NoAutoClose
    background: Rectangle { radius: 12; color: Theme.surface; border.color: Theme.line }
    enter: Transition {}
    exit: Transition { PauseAnimation { duration: 800 } }
    // Derived popups own their focus/search handlers. Keep geometry lifecycle
    // in connections so their signal handlers cannot replace this behavior.
    Connections {
        target: root
        function onAboutToShow() {
            root.refreshAnchor()
            if (root.resetBeforeOpen) motion.snapTo(root.collapsedRect)
            root.resetBeforeOpen = false
            root.desiredOpen = true
        }
        function onAboutToHide() { root.desiredOpen = false }
        function onClosed() { root.resetBeforeOpen = true; motion.snap() }
    }
    Connections {
        target: root.anchorWindow
        function onWidthChanged() { if (root.visible) Qt.callLater(root.refreshAnchor) }
        function onHeightChanged() { if (root.visible) Qt.callLater(root.refreshAnchor) }
    }
    PidMotion {
        id: motion
        targetRect: root.desiredOpen ? Qt.rect(root.openX, root.openBelow ? root.buttonHeight+8 : -root.expandedHeight-8, root.expandedWidth, root.expandedHeight)
                                    : root.collapsedRect
    }
}
