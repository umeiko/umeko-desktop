import QtQuick
import QtQuick.Controls
TextField {
    implicitHeight: Math.max(42, font.pixelSize + 22)
    selectByMouse: true
    color: Theme.ink
    placeholderTextColor: Theme.muted
    font.pixelSize: Theme.font(13)
    leftPadding: 13; rightPadding: 13
    background: Rectangle {
        radius: 8; color: Theme.surface
        border.color: parent.activeFocus ? Theme.accent : Theme.line
        Behavior on border.color { ColorAnimation { duration: 150 } }
    }
}
