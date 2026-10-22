import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

MenuItem {
    id: control
    property string glyph: ""
    property bool destructive: false
    implicitWidth: Theme.control(190); implicitHeight: Theme.control(32)
    height: visible ? implicitHeight : 0
    leftPadding: 11; rightPadding: 11
    opacity: enabled ? 1 : 0.4
    hoverEnabled: true
    HoverHandler { cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }
    contentItem: RowLayout {
        spacing: control.glyph ? 8 : 0
        Glyph { name: control.glyph; color: control.destructive ? Theme.danger : Theme.ink; visible: !!control.glyph; width: control.glyph ? Theme.icon(14) : 0; height: Theme.icon(14) }
        Text { text: control.text; Layout.fillWidth: true; color: control.destructive ? Theme.danger : Theme.ink; font.pixelSize: Theme.font(12); verticalAlignment: Text.AlignVCenter }
    }
    background: Rectangle { radius: 6; color: control.down ? Theme.accentBg : control.highlighted || control.hovered ? Theme.hover : "transparent"; Behavior on color { ColorAnimation { duration: 90 } } }
}
