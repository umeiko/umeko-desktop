import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

MenuItem {
    id: control
    property string glyph: ""
    property bool destructive: false
    implicitWidth: 222; implicitHeight: 34
    height: visible ? implicitHeight : 0
    leftPadding: 11; rightPadding: 11
    opacity: enabled ? 1 : 0.4
    contentItem: RowLayout {
        spacing: 11
        Glyph { name: control.glyph; width: 16; height: 16 }
        Text { text: control.text; Layout.fillWidth: true; color: control.destructive ? Theme.danger : Theme.ink; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter }
    }
    background: Rectangle { radius: 6; color: control.highlighted ? Theme.hover : "transparent" }
}
