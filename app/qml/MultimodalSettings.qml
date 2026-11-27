import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Column {
    id: root
    property bool expanded: false
    property string kind: ""
    signal openRequested()
    signal backRequested()
    signal routeChanged()
    readonly property var categories: [
        {id: "vision", label: I18n.t("图像理解"), glyph: "eye"},
        {id: "image", label: I18n.t("图像生成"), glyph: "image"},
        {id: "speech", label: I18n.t("语音生成"), glyph: "voice"},
        {id: "video", label: I18n.t("视频生成"), glyph: "video"}
    ]
    readonly property var category: categories.find(row => row.id === kind)
    spacing: 16
    onExpandedChanged: if (!expanded) kind = ""
    onKindChanged: routeChanged()

    component MenuRow: ItemDelegate {
        id: row
        required property string label
        required property string glyph
        implicitHeight: Math.max(58, rowContent.implicitHeight + 24)
        leftPadding: 20; rightPadding: 20
        Accessible.name: label
        background: Rectangle {
            radius: 10; color: row.hovered ? Theme.hover : Theme.surface
            border.color: row.activeFocus ? Theme.accent : Theme.line
        }
        contentItem: RowLayout {
            id: rowContent
            spacing: 12
            Glyph { name: row.glyph; width: Theme.icon(20); height: width; color: Theme.muted }
            Text {
                Layout.fillWidth: true
                text: row.label; color: Theme.ink; font.family: Theme.fontFamily
                font.pixelSize: Theme.font(14, visible); wrapMode: Text.Wrap
            }
            Glyph { name: "chevron-right"; width: Theme.icon(16); height: width; color: Theme.muted }
        }
    }

    MenuRow {
        objectName: "multimodalSettingsEntry"
        visible: !root.expanded; width: parent.width
        label: I18n.t("多模态模型选项"); glyph: "image"
        onClicked: root.openRequested()
    }

    Column {
        objectName: "multimodalSettings"
        visible: root.expanded; width: parent.width; spacing: 16
        RowLayout {
            width: parent.width; spacing: 8
            ActionButton {
                objectName: "backMultimodalSettings"
                glyph: "arrow-left"; quiet: true; hint: I18n.t("返回")
                Accessible.name: hint
                onClicked: {
                    if (root.kind) root.kind = ""
                    else root.backRequested()
                }
            }
            Text {
                Layout.fillWidth: true
                text: root.category ? root.category.label : I18n.t("多模态模型选项")
                color: Theme.ink; font.family: Theme.fontFamily
                font.pixelSize: Theme.font(16, visible); font.weight: Font.DemiBold
                wrapMode: Text.Wrap
            }
        }
        Column {
            visible: root.kind === ""; width: parent.width; spacing: 10
            Repeater {
                model: root.categories
                MenuRow {
                    required property var modelData
                    objectName: "multimodalCategory_" + modelData.id
                    width: parent.width
                    label: modelData.label; glyph: modelData.glyph
                    onClicked: root.kind = modelData.id
                }
            }
        }
        Loader {
            width: parent.width; active: root.expanded && root.kind !== ""
            sourceComponent: root.kind === "vision" ? visionPage : root.kind ? generationPage : null
        }
    }
    Component { id: visionPage; AuxiliaryVisionSettings {} }
    Component {
        id: generationPage
        Column {
            spacing: 16
            GenerationSettingsCard {
                id: defaults
                width: parent.width
                kind: root.kind; title: root.category ? root.category.label : ""
            }
            GenerationProviders {
                width: parent.width; kind: defaults.kind; accounts: defaults.accounts
            }
        }
    }
}
