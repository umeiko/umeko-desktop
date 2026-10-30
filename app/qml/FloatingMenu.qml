import QtQuick
import QtQuick.Controls

Menu {
    id: root
    property bool desiredOpen: false
    readonly property bool animating: motion.moving
    padding: 6; margins: 10
    readonly property real widestAction: {
        let widest = 0
        for (let i = 0; i < count; i++) {
            const action = itemAt(i)
            if (action && action.visible) widest = Math.max(widest, action.implicitWidth)
        }
        return widest
    }
    implicitWidth: Math.ceil(Math.max(Theme.control(184), widestAction + leftPadding + rightPadding))
    width: Math.min(implicitWidth, Overlay.overlay ? Math.max(0, Overlay.overlay.width - margins * 2) : implicitWidth)
    height: Math.min(implicitHeight, Overlay.overlay ? Math.max(0, Overlay.overlay.height - margins * 2) : implicitHeight)
    function fitToWindow() {
        if (!visible || !parent || !Overlay.overlay) return
        const point = parent.mapToItem(Overlay.overlay, x, y)
        const edge = margins
        x += Math.max(edge, Math.min(point.x, Overlay.overlay.width - width - edge)) - point.x
        y += Math.max(edge, Math.min(point.y, Overlay.overlay.height - height - edge)) - point.y
    }
    onWidthChanged: Qt.callLater(fitToWindow)
    onHeightChanged: Qt.callLater(fitToWindow)
    onOpened: Qt.callLater(fitToWindow)
    transformOrigin: Popup.TopLeft
    opacity: Math.max(0,Math.min(1,motion.value.width/100))
    scale: 0.9 + motion.value.width/1000
    enter: Transition {}
    exit: Transition {}
    onAboutToShow: desiredOpen = true
    onAboutToHide: desiredOpen = false
    onClosed: motion.snap()
    property PidMotion motion: PidMotion { parent: root.contentItem; targetRect: Qt.rect(0,0,root.desiredOpen ? 100 : 1,1) }
    background: Item {
        Repeater {
            model: 24
            Rectangle {
                required property int index
                readonly property real spread: (index+1)*0.32
                x: -spread; y: 4-spread; width: parent.width+spread*2; height: parent.height+spread*2
                radius: 10+spread; color: "#02000000"; antialiasing: true
            }
        }
        Rectangle { anchors.fill: parent; radius: 10; color: Theme.surface; border.color: Theme.line }
    }
}
