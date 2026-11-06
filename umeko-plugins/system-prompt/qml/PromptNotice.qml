import QtQuick
import QtQuick.Layouts
import "../../../app/qml" as Umeko

// Inline status line under the segment title.
Rectangle {
    id: root
    required property var sdk
    property string text: ""
    property color accent: sdk.colors.muted
    Layout.fillWidth: true
    implicitHeight: label.implicitHeight + 10 * sdk.scale
    radius: 4 * sdk.scale
    color: sdk.colors.bg
    Rectangle {
        width: 3 * root.sdk.scale
        anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
        radius: 2
        color: root.accent
    }
    Text {
        id: label
        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 10 * root.sdk.scale; rightMargin: 8 * root.sdk.scale }
        text: root.text
        wrapMode: Text.Wrap
        color: root.accent
        font.family: Umeko.Theme.fontFamily
        font.pixelSize: Umeko.Theme.font(10)
    }
}
