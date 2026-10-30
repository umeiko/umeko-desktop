import QtQuick
import QtQuick.Controls
ToolButton {
    id: control
    property string iconName: "ellipsis"
    property string hint: ""
    property real uiScale: 1
    property color foreground: "#cccccc"
    property color hoverColor: "#28ffffff"
    implicitWidth: 22 * uiScale; implicitHeight: 22 * uiScale
    padding: 0; hoverEnabled: true
    Accessible.name: hint
    HoverHandler { cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }
    contentItem: Item {
        VsIcon { anchors.centerIn: parent; name: control.iconName; size: 16 * control.uiScale; color: control.foreground; opacity: control.enabled ? 1 : 0.4 }
    }
    background: Rectangle { radius: 3; color: control.down || control.hovered ? control.hoverColor : "transparent" }
    ToolTip.visible: hovered && !!hint; ToolTip.text: hint; ToolTip.delay: 500
}
