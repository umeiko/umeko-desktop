import QtQuick
import QtQuick.Controls
import "../../../app/qml" as Umeko

// Tri-state source checkbox: a directory with mixed children shows a dash.
CheckBox {
    id: box
    required property var sdk
    property int sourceState: 2
    signal changedTo(bool value)
    tristate: true
    padding: 0
    checkState: sourceState === 1 ? Qt.PartiallyChecked : sourceState === 2 ? Qt.Checked : Qt.Unchecked
    nextCheckState: function() { return checkState === Qt.Checked ? Qt.Unchecked : Qt.Checked }
    onClicked: box.changedTo(checkState === Qt.Checked)
    indicator: Rectangle {
        width: 14 * box.sdk.scale; height: width
        anchors.centerIn: parent
        radius: 3 * box.sdk.scale
        color: box.checkState !== Qt.Unchecked ? box.sdk.colors.accent : "transparent"
        border.width: Math.max(1, box.sdk.scale)
        border.color: box.checkState !== Qt.Unchecked ? box.sdk.colors.accent
            : box.hovered && box.enabled ? box.sdk.colors.ink : box.sdk.colors.muted
        opacity: box.enabled ? 1 : 0.45
        Umeko.Glyph {
            anchors.centerIn: parent
            name: "check"
            visible: box.checkState === Qt.Checked
            width: 12 * box.sdk.scale; height: width
            color: box.sdk.colors.surface
        }
        Rectangle {
            anchors.centerIn: parent
            visible: box.checkState === Qt.PartiallyChecked
            width: 8 * box.sdk.scale; height: Math.max(2, 2 * box.sdk.scale); radius: 1
            color: box.sdk.colors.surface
        }
    }
    contentItem: Item {}
}
