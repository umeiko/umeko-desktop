import QtQuick
import QtQuick.Controls
Switch {
    id: control
    implicitWidth: Theme.control(42); implicitHeight: Theme.control(24)
    padding: 0
    opacity: enabled ? 1 : 0.45
    indicator: Rectangle {
        width: Theme.control(38); height: Theme.control(22); radius: Theme.control(11)
        color: control.checked ? Theme.button : Theme.line
        Behavior on color { ColorAnimation { duration: 140 } }
        Rectangle { width: Theme.control(16); height: Theme.control(16); radius: Theme.control(8); y: Theme.control(3); x: control.checked ? Theme.control(19) : Theme.control(3); color: "white"
            Behavior on x { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } } }
    }
}
