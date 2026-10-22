import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "theme.js" as Colors

SectionCard {
    id: root
    readonly property var choices: [{id:"light",name:I18n.t("浅色"),base:"light"},{id:"dark",name:I18n.t("深色"),base:"dark"},{id:"yanami",name:I18n.t("八奈见 · 海盐蓝"),base:"yanami"}].concat(backend.customThemes)
    FileDialog { id: picker; title: I18n.t("导入主题"); nameFilters: [I18n.t("Umeko 主题 (*.umeko-theme.json *.json)")]; onAccepted: backend.importTheme(selectedFile.toString()) }
    ColumnLayout {
        width: parent.width; spacing: 18
        RowLayout {
            Layout.fillWidth: true
            Text { text: I18n.t("主题"); color: Theme.ink; font.pixelSize: Theme.font(14); font.weight: Font.DemiBold }
            Item { Layout.fillWidth: true }
            ActionButton { objectName: "copyThemePrompt"; glyph: "copy"; text: I18n.t("制作提示词"); quiet: true; hint: I18n.t("复制完整格式、示例与制作提示词"); onClicked: backend.copyThemePrompt() }
            ActionButton { objectName: "importThemeButton"; glyph: "plus"; text: I18n.t("导入主题"); onClicked: picker.open() }
        }
        GridLayout {
            Layout.fillWidth: true; columns: width < 640 ? 2 : 3; columnSpacing: 20; rowSpacing: 18
            Repeater {
                model: root.choices
                ColumnLayout {
                    id: choice
                    required property var modelData
                    readonly property var palette: Colors.palette(modelData.base, modelData.colors)
                    Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.minimumWidth: 0; spacing: 8
                    Rectangle {
                        objectName: "theme_" + choice.modelData.id
                        Layout.fillWidth: true; height: 160; radius: 10; color: choice.palette.bg
                        border.color: backend.config.theme === choice.modelData.id ? Theme.accent : hover.containsMouse ? Theme.accent : Theme.line
                        border.width: backend.config.theme === choice.modelData.id ? 2 : 1
                        Rectangle { x: 2; y: 2; width: parent.width * 0.22; height: parent.height - 4; radius: 8; color: choice.palette.sidebar }
                        Rectangle { x: parent.width * 0.32; y: 85; width: parent.width * 0.55; height: 40; radius: 6; color: choice.palette.surface; border.color: choice.palette.line
                            Rectangle { x: 12; y: 14; width: parent.width * 0.44; height: 3; radius: 1; color: choice.palette.muted }
                        }
                        Rectangle { visible: choice.modelData.base !== "yanami"; x: parent.width * 0.54; y: 37; width: 24; height: 24; radius: 8; color: choice.palette.button }
                        Image { visible: choice.modelData.base === "yanami"; source: "../icons/portraits/02.png"; x: parent.width * 0.42; y: 15; width: 65; height: 65; mipmap: true }
                        MouseArea { id: hover; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: backend.setTheme(choice.modelData.id) }
                    }
                    RowLayout {
                        Layout.fillWidth: true; spacing: 6
                        Text { text: choice.modelData.name; textFormat: Text.PlainText; color: Theme.ink; font.pixelSize: Theme.font(12); elide: Text.ElideRight; Layout.fillWidth: true }
                        Glyph { name: "check"; width: 15; height: 15; color: Theme.accent; visible: backend.config.theme === choice.modelData.id }
                        ActionButton { objectName: "deleteTheme_" + choice.modelData.id; glyph: "trash"; quiet: true; destructive: true; width: 24; height: 24; visible: choice.modelData.id.startsWith("custom:"); hint: I18n.t("删除主题"); onClicked: backend.removeTheme(choice.modelData.id) }
                    }
                }
            }
        }
    }
}
