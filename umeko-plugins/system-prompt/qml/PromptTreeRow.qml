import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../../app/qml" as Umeko
import "../../file-tree/qml" as FileTree

// One file-manager style row: chevron, checkbox, folder/file icon, name, state tag.
Rectangle {
    id: root
    required property var sdk
    required property var entry
    property bool selected: false
    property bool available: true
    property color changedColor: "#d7b65b"
    property color changedBg: "transparent"
    property bool dark: true
    readonly property bool active: !!entry.enabled && !entry.shadowed
    signal selectedLeaf(string identifier)
    signal fold(string identifier)
    signal toggled(string identifier, bool value)
    height: (entry.hint ? 24 : 28) * sdk.scale
    radius: 4 * sdk.scale
    color: entry.hint ? "transparent" : selected ? sdk.colors.accentBg : entry.changed ? changedBg : hover.hovered ? sdk.colors.hover : "transparent"
    HoverHandler { id: hover; enabled: !root.entry.hint }
    TapHandler {
        enabled: !root.entry.hint
        onTapped: root.entry.folder ? root.fold(root.entry.id) : root.selectedLeaf(root.entry.id)
    }
    Rectangle {
        // Yellow edge keeps a changed row visible even while it is selected.
        visible: !!root.entry.changed && !root.entry.hint
        width: 3 * root.sdk.scale; radius: width / 2
        anchors { left: parent.left; top: parent.top; bottom: parent.bottom; topMargin: 4 * root.sdk.scale; bottomMargin: 4 * root.sdk.scale }
        color: root.changedColor
    }
    Text {
        visible: !!root.entry.hint
        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter
            leftMargin: (31 + root.entry.depth * 16) * root.sdk.scale; rightMargin: 6 * root.sdk.scale }
        text: root.entry.label || ""
        elide: Text.ElideRight
        color: root.sdk.colors.muted
        font.family: Umeko.Theme.fontFamily
        font.pixelSize: Umeko.Theme.font(10)
        font.italic: true
    }
    RowLayout {
        visible: !root.entry.hint
        anchors.fill: parent
        anchors.leftMargin: (6 + root.entry.depth * 16) * root.sdk.scale
        anchors.rightMargin: 6 * root.sdk.scale
        spacing: 4 * root.sdk.scale
        Umeko.Glyph {
            Layout.preferredWidth: 10 * root.sdk.scale
            Layout.preferredHeight: 10 * root.sdk.scale
            name: root.entry.folder ? root.entry.expanded ? "chevron-down" : "chevron-right" : ""
            color: root.sdk.colors.muted
        }
        PromptCheckBox {
            objectName: "systemPromptCheck_" + root.entry.id
            Layout.preferredWidth: 22 * root.sdk.scale
            Layout.preferredHeight: 24 * root.sdk.scale
            sdk: root.sdk
            sourceState: root.entry.checkState || 0
            enabled: root.available && !root.entry.empty && !root.entry.hint
            onChangedTo: value => root.toggled(root.entry.id, value)
            Accessible.name: root.entry.label || root.entry.name || ""
        }
        FileTree.FileIcon {
            fileName: root.entry.folder ? "" : String(root.entry.name || "").indexOf(".") > 0 ? root.entry.name : "prompt.txt"
            directory: !!root.entry.folder
            expanded: !!root.entry.expanded
            uiScale: root.sdk.scale
            dark: root.dark
            folderColor: root.entry.changed ? root.changedColor : root.sdk.colors.muted
            opacity: root.active ? 1 : 0.45
        }
        Text {
            objectName: "systemPromptName_" + root.entry.id
            Layout.fillWidth: true
            text: root.entry.label || root.entry.name || ""
            textFormat: Text.PlainText
            elide: Text.ElideRight
            color: root.entry.changed ? root.changedColor : root.active ? root.sdk.colors.ink : root.sdk.colors.muted
            font.family: Umeko.Theme.fontFamily
            font.pixelSize: Umeko.Theme.font(11)
            font.weight: root.entry.folder && root.entry.depth === 0 ? Font.DemiBold : Font.Normal
            font.strikeout: !root.entry.enabled && !root.entry.folder
            opacity: root.active || root.entry.changed ? 1 : 0.7
        }
        Text {
            // Plain state words instead of a bare dot.
            visible: text !== ""
            text: !root.entry.enabled ? root.t("已停用", "Off")
                : root.entry.shadowed ? root.t("被覆盖", "Replaced")
                : root.entry.modified && !root.entry.folder ? root.t("已编辑", "Edited") : ""
            color: root.entry.changed ? root.changedColor : root.sdk.colors.muted
            font.family: Umeko.Theme.fontFamily
            font.pixelSize: Umeko.Theme.font(9)
        }
    }
    function t(zh, en) { return sdk.language.indexOf("zh") === 0 ? zh : en }
}
