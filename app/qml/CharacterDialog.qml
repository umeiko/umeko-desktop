import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import QtCore

PidPopup {
    id: root
    objectName: "characterDialog"
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(600, parent.width - 32)
    height: Math.min(560, parent.height - 32, grid.implicitHeight + heading.implicitHeight + description.implicitHeight + actions.implicitHeight + content.spacing * 3 + padding * 2 + 2)
    property var removal: ({})
    FileDialog {
        id: importPicker
        title: I18n.t("导入人设包")
        nameFilters: [I18n.t("Umeko 人设包 (*.zip)"), I18n.t("形象清单 (manifest.json)")]
        onAccepted: backend.importCharacter(selectedFile.toString())
    }
    FileDialog {
        id: skillPicker
        title: I18n.t("导出角色制作 Skill")
        fileMode: FileDialog.SaveFile
        defaultSuffix: "zip"
        currentFolder: StandardPaths.writableLocation(StandardPaths.DownloadLocation)
        nameFilters: ["ZIP (*.zip)"]
        onAccepted: backend.exportCharacterSkill(selectedFile.toString())
    }
    PidPopup {
        id: confirmRemoval
        objectName: "removeCharacterDialog"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(380, parent.width - 32)
        height: removalContent.implicitHeight + padding * 2
        ColumnLayout {
            id: removalContent
            width: parent.width; spacing: 18
            Text { font.family: Theme.fontFamily; Layout.fillWidth: true; text: I18n.t("删除角色") + " · " + (root.removal.name || ""); textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Theme.ink; font.pixelSize: Theme.font(15, visible) }
            Text { font.family: Theme.fontFamily; Layout.fillWidth: true; text: I18n.t("删除当前角色后，将恢复八奈见。原始 ZIP 文件会保留。"); wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(12, visible) }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                ActionButton { text: I18n.t("取消"); quiet: true; onClicked: confirmRemoval.close() }
                ActionButton { objectName: "confirmRemoveCharacter"; text: I18n.t("删除"); destructive: true; onClicked: { if (backend.removeCharacter(root.removal.id)) confirmRemoval.close() } }
            }
        }
    }
    // Keep the PID timer item outside the layout so it adds no phantom spacing.
    contentItem: Item {
      ColumnLayout {
        anchors.fill: parent
        id: content
        spacing: 16
        RowLayout {
            id: heading
            Layout.fillWidth: true
            Text { font.family: Theme.fontFamily; text: I18n.t("主角色"); color: Theme.ink; font.pixelSize: Theme.font(18, visible); font.weight: Font.DemiBold; Layout.fillWidth: true }
            ActionButton { objectName: "closeCharacterDialog"; glyph: "x"; quiet: true; hint: I18n.t("关闭"); onClicked: root.close() }
        }
        Text { font.family: Theme.fontFamily; id: description; text: I18n.t("独立于主题，即时切换形象与互动台词。"); color: Theme.muted; font.pixelSize: Theme.font(12, visible); Layout.fillWidth: true; wrapMode: Text.Wrap }
        Flickable {
            id: scroll
            objectName: "characterList"
            Layout.fillWidth: true; Layout.fillHeight: true
            contentHeight: grid.implicitHeight; clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}
            GridLayout {
                id: grid
                width: scroll.width - 12; columns: scroll.width < 420 ? 2 : 3
                columnSpacing: 12; rowSpacing: 16
                Repeater {
                    model: backend.characterPacks
                    ColumnLayout {
                        id: entry
                        required property var modelData
                        Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.minimumWidth: 0
                        spacing: 7
                        Button {
                            id: choice
                            objectName: "character_" + entry.modelData.id
                            Layout.fillWidth: true; implicitHeight: Theme.control(130)
                            padding: 12; hoverEnabled: true
                            Accessible.name: entry.modelData.name
                            onClicked: backend.selectCharacter(entry.modelData.id)
                            HoverHandler { cursorShape: Qt.PointingHandCursor }
                            background: Rectangle {
                                radius: 10; color: choice.hovered ? Theme.hover : Theme.bg
                                border.width: backend.characterStyle.id === entry.modelData.id ? 2 : 1
                                border.color: backend.characterStyle.id === entry.modelData.id || choice.activeFocus ? Theme.accent : Theme.line
                            }
                            contentItem: Image {
                                source: entry.modelData.portrait; sourceSize: Qt.size(192,192)
                                asynchronous: true; fillMode: Image.PreserveAspectFit; smooth: false
                            }
                            Glyph { anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 8; name: "check"; width: 16; height: 16; color: Theme.accent; visible: backend.characterStyle.id === entry.modelData.id }
                        }
                        RowLayout {
                            Layout.fillWidth: true; spacing: 4
                            Text { font.family: Theme.fontFamily; text: I18n.t(entry.modelData.name); textFormat: Text.PlainText; color: Theme.ink; font.pixelSize: Theme.font(12, visible); elide: Text.ElideRight; Layout.fillWidth: true }
                            Text { font.family: Theme.fontFamily; visible: entry.modelData.builtin; text: I18n.t("内置"); color: Theme.muted; font.pixelSize: Theme.font(10, visible) }
                            ActionButton { objectName: "deleteCharacter_" + entry.modelData.id; visible: !entry.modelData.builtin; glyph: "trash"; quiet: true; destructive: true; implicitWidth: 24; implicitHeight: 24; hint: I18n.t("删除角色"); onClicked: { root.removal = entry.modelData; confirmRemoval.open() } }
                        }
                    }
                }
            }
        }
        RowLayout {
            id: actions
            Layout.fillWidth: true; spacing: 8
            ActionButton { objectName: "exportCharacterSkill"; text: I18n.t("制作角色 Skill"); glyph: "download"; quiet: true; onClicked: { skillPicker.selectedFile = String(skillPicker.currentFolder) + "/create-umeko-character.zip"; skillPicker.open() } }
            Item { Layout.fillWidth: true }
            ActionButton { objectName: "importCharacterButton"; text: I18n.t("导入人设包"); glyph: "plus"; onClicked: importPicker.open() }
        }
    }
    }
}
