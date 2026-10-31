import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

MenuItem {
    id: control
    property string glyph: ""
    property bool destructive: false
    implicitWidth: Math.ceil(Math.max(Theme.control(190), label.implicitWidth + leftPadding + rightPadding + (glyph ? Theme.icon(14) + 8 : 0)))
    implicitHeight: Math.max(Theme.control(32), row.implicitHeight + topPadding + bottomPadding)
    height: visible ? implicitHeight : 0
    leftPadding: 11; rightPadding: 11; topPadding: 7; bottomPadding: 7
    opacity: enabled ? 1 : 0.4
    hoverEnabled: true
    HoverHandler { cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }
    contentItem: RowLayout {
        id: row
        spacing: control.glyph ? 8 : 0
        Glyph { name: control.glyph; color: control.destructive ? Theme.danger : Theme.ink; visible: !!control.glyph; Layout.preferredWidth: control.glyph ? Theme.icon(14) : 0; Layout.preferredHeight: Theme.icon(14) }
        Text { font.family: Theme.fontFamily; id: label; objectName: control.objectName + "Label"; text: control.text; Layout.fillWidth: true; wrapMode: Text.Wrap; color: control.destructive ? Theme.danger : Theme.ink; font.pixelSize: Theme.font(12, visible); verticalAlignment: Text.AlignVCenter }
    }
    background: Rectangle { radius: 6; color: control.down ? Theme.accentBg : control.highlighted || control.hovered ? Theme.hover : "transparent"; Behavior on color { ColorAnimation { duration: 90 } } }
}
