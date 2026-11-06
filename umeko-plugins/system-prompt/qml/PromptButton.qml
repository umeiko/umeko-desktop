import QtQuick
import QtQuick.Controls
import "../../../app/qml" as Umeko

Button {
    id: root
    required property var sdk
    property bool primary: false
    property string iconName: ""
    font.family: Umeko.Theme.fontFamily
    implicitHeight: 29 * sdk.scale
    implicitWidth: Math.max(29 * sdk.scale, label.implicitWidth + 18 * sdk.scale)
    background: Rectangle {
        radius: 5 * root.sdk.scale
        color: root.primary && root.enabled ? root.sdk.colors.accentBg : root.hovered && root.enabled ? root.sdk.colors.hover : "transparent"
        border.color: root.primary && root.enabled ? root.sdk.colors.accent : root.sdk.colors.line
    }
    contentItem: Item {
        implicitWidth: root.iconName ? 14 * root.sdk.scale : label.implicitWidth
        implicitHeight: label.implicitHeight
        Umeko.Glyph {
            anchors.centerIn: parent
            visible: !!root.iconName
            name: root.iconName
            width: 14 * root.sdk.scale; height: width
            color: root.enabled ? root.sdk.colors.ink : root.sdk.colors.muted
        }
        Text {
        id: label
        anchors.fill: parent
        visible: !root.iconName
        text: root.text
        color: root.enabled ? root.sdk.colors.ink : root.sdk.colors.muted
        font.family: root.font.family
        font.pixelSize: Umeko.Theme.font(11)
        textFormat: Text.PlainText
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        }
    }
}
