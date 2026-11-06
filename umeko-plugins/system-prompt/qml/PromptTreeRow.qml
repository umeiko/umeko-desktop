import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../../app/qml" as Umeko
import "../../file-tree/qml" as FileTree

Rectangle {
    id: root
    required property var sdk
    required property var entry
    property bool selected: false
    property bool available: true
    property color changedColor: "#d7b65b"
    signal selectedLeaf(string identifier)
    signal fold(string identifier)
    signal toggled(string identifier, bool value)
    height: 34 * sdk.scale
    color: selected ? sdk.colors.accentBg : hover.hovered ? sdk.colors.hover : "transparent"
    radius: 4 * sdk.scale
    HoverHandler { id: hover }
    TapHandler { onTapped: root.entry.folder ? root.fold(root.entry.id) : root.selectedLeaf(root.entry.id) }
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: (7 + root.entry.depth * 16) * root.sdk.scale
        anchors.rightMargin: 5 * root.sdk.scale
        spacing: 5 * root.sdk.scale
        Umeko.Glyph {
            Layout.preferredWidth: 10 * root.sdk.scale
            Layout.preferredHeight: 10 * root.sdk.scale
            name: root.entry.folder ? root.entry.expanded ? "chevron-down" : "chevron-right" : ""
            color: root.sdk.colors.muted
        }
        CheckBox {
            id: box
            objectName: "systemPromptCheck_" + root.entry.id
            Layout.preferredWidth: 23 * root.sdk.scale
            Layout.preferredHeight: 29 * root.sdk.scale
            enabled: root.available
            tristate: true
            checkState: root.entry.checkState === 1 ? Qt.PartiallyChecked : root.entry.checkState === 2 ? Qt.Checked : Qt.Unchecked
            nextCheckState: function() { return checkState === Qt.Checked ? Qt.Unchecked : Qt.Checked }
            onClicked: root.toggled(root.entry.id, checkState === Qt.Checked)
            Accessible.name: root.entry.name
            indicator: Rectangle {
                width: 14 * root.sdk.scale; height: width
                anchors.centerIn: parent
                radius: 3 * root.sdk.scale
                color: box.checkState !== Qt.Unchecked ? root.sdk.colors.accent : "transparent"
                border.color: box.enabled ? box.checkState !== Qt.Unchecked ? root.sdk.colors.accent : root.sdk.colors.muted : root.sdk.colors.line
                opacity: box.enabled ? 1 : 0.5
                Umeko.Glyph {
                    anchors.centerIn: parent
                    name: "check"
                    visible: box.checkState === Qt.Checked
                    width: 12 * root.sdk.scale; height: width
                    color: root.sdk.colors.surface
                }
                Rectangle {
                    anchors.centerIn: parent
                    visible: box.checkState === Qt.PartiallyChecked
                    width: 8 * root.sdk.scale; height: 2 * root.sdk.scale
                    color: root.sdk.colors.surface
                }
            }
            contentItem: Item {}
        }
        FileTree.FileIcon {
            fileName: root.entry.name
            directory: root.entry.folder
            expanded: root.entry.expanded
            uiScale: root.sdk.scale
            dark: root.sdk.colors.surface.toString().toLowerCase() !== "#ffffff"
            folderColor: root.entry.changed ? root.changedColor : root.sdk.colors.muted
            opacity: root.entry.enabled && !root.entry.shadowed ? 1 : 0.45
        }
        Text {
            objectName: "systemPromptName_" + root.entry.id
            Layout.fillWidth: true
            text: root.entry.name
            textFormat: Text.PlainText
            elide: Text.ElideRight
            color: root.entry.changed ? root.changedColor : root.entry.enabled && !root.entry.shadowed ? root.sdk.colors.ink : root.sdk.colors.muted
            font.family: Umeko.Theme.fontFamily
            font.pixelSize: Umeko.Theme.font(11)
            font.weight: root.entry.folder ? Font.DemiBold : Font.Normal
            opacity: root.entry.enabled || root.entry.changed ? 1 : 0.65
        }
        Text {
            visible: root.entry.changed
            text: "•"
            color: root.changedColor
            font.pixelSize: Umeko.Theme.font(14)
        }
    }
}
