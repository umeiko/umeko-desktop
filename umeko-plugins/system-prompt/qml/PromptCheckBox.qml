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

    contentItem: Item {}
}
