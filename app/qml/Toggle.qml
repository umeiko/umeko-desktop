import QtQuick
import QtQuick.Controls
Switch {
    id: control
    implicitWidth: 42; implicitHeight: 24
    padding: 0
    opacity: enabled ? 1 : 0.45
    indicator: Rectangle {
        width: 38; height: 22; radius: 11
        color: control.checked ? Theme.button : Theme.line
        Behavior on color { ColorAnimation { duration: 140 } }
        Rectangle { width: 16; height: 16; radius: 8; y: 3; x: control.checked ? 19 : 3; color: "white"
            Behavior on x { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } } }
    }
}
