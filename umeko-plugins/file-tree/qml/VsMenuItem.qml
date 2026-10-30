import QtQuick
import QtQuick.Controls
MenuItem {
    id: control
    property var colors
    property real uiScale: 1
    property string shortcutText: ""
    implicitHeight: 26 * uiScale
    leftPadding: 12 * uiScale; rightPadding: 20 * uiScale
    font.family: "Segoe UI"; font.pixelSize: 13 * uiScale
    contentItem: Item {
        opacity:control.enabled?1:0.4
        implicitWidth:label.implicitWidth+shortcut.implicitWidth+(control.shortcutText?20*control.uiScale:0)
        implicitHeight:Math.max(label.implicitHeight,shortcut.implicitHeight)
        Text {id:label;anchors.left:parent.left;anchors.verticalCenter:parent.verticalCenter;width:parent.width-(control.shortcutText?shortcut.width+20*control.uiScale:0);text:control.text;textFormat:Text.PlainText;color:control.colors.ink;font:control.font;elide:Text.ElideRight}
        Text {id:shortcut;anchors.right:parent.right;anchors.verticalCenter:parent.verticalCenter;text:control.shortcutText;color:control.colors.muted;font:control.font}
    }
    background: Rectangle { radius: 3; color: control.highlighted ? control.colors.hover : "transparent" }
}
