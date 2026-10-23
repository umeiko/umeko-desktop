import QtQuick
import QtQuick.Controls
import QtQuick.Window

ToolTip {
    id: root
    property bool active: false
    property string heading: ""
    visible: active && text.length > 0 && !(parent && parent.Window.window && parent.Window.window.mediaOverlayActive)
    delay: 500; timeout: -1
    padding: 12; margins: 12
    width: Math.min(360, Overlay.overlay ? Overlay.overlay.width - 24 : 360, Math.max(120, details.implicitWidth + padding * 2))
    x: Math.max(0, (parent.width - width) / 2)
    y: -height - 8
    contentItem: Column {
        objectName: "hoverTipContent_" + root.objectName
        spacing: 5
        Text {
            width: parent.width; visible: root.heading.length > 0
            text: root.heading; textFormat: Text.PlainText
            color: Theme.ink; font.pixelSize: Theme.font(12); font.weight: Font.DemiBold
            elide: Text.ElideMiddle
        }
        Text {
            id: details
            width: parent.width; text: root.text; textFormat: Text.PlainText
            color: Theme.muted; font.pixelSize: Theme.font(11); lineHeight: 1.3
            wrapMode: Text.WrapAnywhere; maximumLineCount: 6; elide: Text.ElideRight
        }
    }
    background: Item {
        Repeater {
            model: 12
            Rectangle {
                required property int index
                readonly property real spread: (index + 1) * 0.4
                x: -spread; y: 3 - spread
                width: parent.width + spread * 2; height: parent.height + spread * 2
                radius: 9 + spread; color: "#02000000"
            }
        }
        Rectangle { anchors.fill: parent; radius: 9; color: Theme.surface; border.color: Theme.line }
    }
    enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 100 } }
    exit: Transition { NumberAnimation { property: "opacity"; to: 0; duration: 80 } }
}
