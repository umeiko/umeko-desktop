import QtQuick
import QtQuick.Controls
TextField {
    implicitHeight: 42
    selectByMouse: true
    color: Theme.ink
    placeholderTextColor: Theme.muted
    font.pixelSize: 13
    leftPadding: 13; rightPadding: 13
    background: Rectangle {
        radius: 8; color: Theme.surface
        border.color: parent.activeFocus ? Theme.accent : Theme.line
        Behavior on border.color { ColorAnimation { duration: 150 } }
    }
}
