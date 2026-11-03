import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Column {
    id: root
    objectName: "auxiliaryVisionSettings"
    property bool expanded: false
    signal openRequested()
    signal backRequested()
    readonly property var config: backend.config.auxiliaryVision
    readonly property var choices: [{providerId:"", model:"", label:I18n.t("不使用辅助视觉")}].concat(backend.auxiliaryVisionModels)
    readonly property int selectedIndex: Math.max(0, choices.findIndex(row => row.providerId === config.providerId && row.model === config.model))
    spacing: 18

    ItemDelegate {
        objectName: "multimodalSettingsEntry"
        visible: !root.expanded; width: parent.width
        implicitHeight: Math.max(60, entryContent.implicitHeight + 28)
        leftPadding: 20; rightPadding: 20
        background: Rectangle { radius: 10; color: parent.hovered ? Theme.hover : Theme.surface; border.color: Theme.line }
        contentItem: RowLayout {
            id: entryContent; spacing: 12
            Glyph { name: "image"; width: Theme.icon(20); height: Theme.icon(20); color: Theme.muted }
            Text { text: I18n.t("多模态模型选项"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(14); Layout.fillWidth: true; wrapMode: Text.Wrap }
            Text { visible: root.selectedIndex > 0 && root.width > Theme.control(560); text: root.choices[root.selectedIndex].label; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11); Layout.maximumWidth: root.width * 0.4; elide: Text.ElideRight }
            Glyph { name: "chevron-right"; width: Theme.icon(16); height: Theme.icon(16); color: Theme.muted }
        }
        onClicked: root.openRequested()
    }

    Column {
        visible: root.expanded; width: parent.width; spacing: 18
        RowLayout {
            width: parent.width; spacing: 8
            ActionButton { objectName: "backMultimodalSettings"; glyph: "arrow-left"; quiet: true; hint: I18n.t("返回"); onClicked: root.backRequested() }
            Text { text: I18n.t("多模态模型选项"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(14); font.weight: Font.DemiBold; Layout.fillWidth: true; wrapMode: Text.Wrap }
        }
        SectionCard {
            width: parent.width
            ColumnLayout {
                width: parent.width; spacing: 14
                RowLayout {
                    Layout.fillWidth: true
                    Text { text: I18n.t("默认多模态模型"); font.family: Theme.fontFamily; font.pixelSize: Theme.font(13); color: Theme.ink; Layout.fillWidth: true; wrapMode: Text.Wrap }
                    HelpButton { help: I18n.t("主模型不支持图片时，使用这里选择的模型识图。支持图片的主模型仍直接接收原图。图片会发送给所选供应商。") }
                }
                Picker {
                    id: models; objectName: "auxiliaryVisionModel"; Layout.fillWidth: true
                    model: root.choices.map(row => row.label)
                    function sync() { currentIndex = root.selectedIndex }
                    Component.onCompleted: Qt.callLater(sync)
                    onModelChanged: Qt.callLater(sync)
                    Connections { target: backend; function onChanged() { Qt.callLater(models.sync) } }
                    onActivated: index => backend.saveAuxiliaryVision(JSON.stringify({providerId:root.choices[index].providerId, model:root.choices[index].model}))
                }
            }
        }
        SectionCard {
            width: parent.width
            ColumnLayout {
                width: parent.width; spacing: 22
                RowLayout {
                    Layout.fillWidth: true; spacing: 8; enabled: root.selectedIndex > 0
                    Text { text: I18n.t("自动分析附图"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13); wrapMode: Text.Wrap; Layout.fillWidth: true }
                    HelpButton { help: I18n.t("自动分析附图并将观察结果加入本轮上下文，聊天原图仍保留。关闭后，Agent 可以按需调用识图工具。") }
                    Toggle { objectName: "auxiliaryVisionAutomatic"; checked: root.config.autoAnalyze
                        onClicked: { const value = checked; checked = Qt.binding(() => root.config.autoAnalyze); backend.saveAuxiliaryVision(JSON.stringify({autoAnalyze:value})) } }
                }
                RowLayout {
                    Layout.fillWidth: true; spacing: 8; enabled: root.selectedIndex > 0
                    Text { text: I18n.t("提供 analyze_image 工具"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13); wrapMode: Text.Wrap; Layout.fillWidth: true }
                    HelpButton { help: I18n.t("将识图工具归入 Umeko Desktop 工具包，允许 Agent 针对图片细节追问。工具也遵循会话的工具开关。") }
                    Toggle { objectName: "auxiliaryVisionTool"; checked: root.config.toolEnabled
                        onClicked: { const value = checked; checked = Qt.binding(() => root.config.toolEnabled); backend.saveAuxiliaryVision(JSON.stringify({toolEnabled:value})) } }
                }
            }
        }
        MultimodalSettings { width: parent.width }
    }
}
