import QtQuick
import QtQuick.Controls

Column {
    id: root
    default property alias content: body.data
    property string title: ""
    property string searchTerms: ""
    property string query: ""
    property bool nested: false
    property bool expanded: false
    property bool searchExpanded: true
    readonly property bool matches: !query.trim() || query.trim().toLowerCase().split(/\s+/).every(word => (title + " " + searchTerms).toLowerCase().includes(word))
    readonly property bool opened: query.trim() ? searchExpanded : expanded
    onQueryChanged: searchExpanded = true
    visible: matches
    spacing: 10
    data: [Rectangle {
        width: root.width; height: Theme.control(root.nested ? 36 : 44); radius: 8
        color: area.containsMouse ? Theme.hover : root.nested ? "transparent" : Theme.surface
        border.color: root.nested ? "transparent" : Theme.line
        Glyph { x: 12; anchors.verticalCenter: parent.verticalCenter; name: "chevron-right"; width: Theme.icon(14); height: Theme.icon(14); rotation: root.opened ? 90 : 0; Behavior on rotation { NumberAnimation { duration: 120 } } }
        Text { font.family: Theme.fontFamily; x: 22 + Theme.icon(14); anchors.verticalCenter: parent.verticalCenter; text: root.title; color: Theme.ink; font.pixelSize: Theme.font(root.nested ? 12 : 14, visible); font.weight: root.nested ? Font.Medium : Font.DemiBold }
        MouseArea { id: area; objectName: root.objectName + "Toggle"; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { if (root.query.trim()) root.searchExpanded = !root.searchExpanded; else root.expanded = !root.expanded } }
        Accessible.role: Accessible.Button; Accessible.name: root.title
    },
    Column { id: body; x: root.nested ? 0 : 12; width: root.width - x; spacing: 12; visible: root.opened }]
}
