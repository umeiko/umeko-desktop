import QtQuick
import QtQuick.Controls
import "../../../app/qml" as Umeko

ScrollBar {
    id: control
    padding: 2
    implicitWidth: 8
    minimumSize: 0.08
    contentItem: Rectangle {
        implicitWidth: 4
        radius: 2
        color: control.pressed ? Umeko.Theme.accent : Umeko.Theme.muted
        opacity: control.active || control.hovered ? 0.65 : 0.22
        Behavior on opacity { NumberAnimation { duration: 140 } }
    }
}
