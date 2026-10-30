import QtQuick
import QtQuick.Window

MouseArea {
    id: drag
    required property var targetWindow
    property point pressPosition
    property real horizontalRatio: 0.5
    property bool movingWindow: false
    acceptedButtons: Qt.LeftButton
    onPressed: mouse => {
        pressPosition = mapToGlobal(mouse.x, mouse.y)
        horizontalRatio = Math.max(0, Math.min(1, (pressPosition.x - targetWindow.x) / targetWindow.width))
        movingWindow = false
    }
    onPositionChanged: mouse => {
        if (!pressed || movingWindow) return
        const position = mapToGlobal(mouse.x, mouse.y)
        if (Math.abs(position.x - pressPosition.x) + Math.abs(position.y - pressPosition.y) < Qt.styleHints.startDragDistance) return
        movingWindow = true
        // Restore through Qt before the native move loop so visibility and resize
        // handles follow the restored window on Windows as well.
        if (targetWindow.visibility === Window.Maximized) {
            const topOffset = Math.min(32, pressPosition.y - targetWindow.y)
            targetWindow.showNormal()
            targetWindow.x = position.x - horizontalRatio * targetWindow.width
            targetWindow.y = position.y - topOffset
        }
        targetWindow.startSystemMove()
    }
    onDoubleClicked: targetWindow.visibility === Window.Maximized ? targetWindow.showNormal() : targetWindow.showMaximized()
}
