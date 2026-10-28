import QtQuick
import QtQuick.Controls

Popup {
    id: root
    property bool desiredOpen: false
    readonly property bool animating: motion.moving
    readonly property real animationProgress: Math.max(0, Math.min(1, (motion.value.width - 1) / 99))
    modal: true; focus: true; padding: Theme.control(24)
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    transformOrigin: Popup.Center
    opacity: animationProgress
    scale: 0.96 + animationProgress * 0.04
    // Keep the popup alive while the PID motion fades it out.
    enter: Transition { PauseAnimation { duration: 320 } }
    exit: Transition { PauseAnimation { duration: 260 } }
    onAboutToShow: desiredOpen = true
    onAboutToHide: desiredOpen = false
    onClosed: motion.snap()
    property PidMotion motion: PidMotion {
        parent: root.contentItem
        targetRect: Qt.rect(0, 0, root.desiredOpen ? 100 : 1, 1)
    }
    background: Rectangle {
        radius: 16; color: Theme.surface; border.color: Theme.line
        Rectangle { anchors.fill: parent; anchors.margins: -1; radius: 17; color: "transparent"; border.color: Theme.line; opacity: 0.35; z: -1 }
    }
    Overlay.modal: Rectangle { color: "#32000000" }
}
