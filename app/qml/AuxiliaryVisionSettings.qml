import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Column {
    id: root
    objectName: "auxiliaryVisionSettings"
    readonly property var config: backend.auxiliaryVisionSettings
    readonly property var choices: [{providerId:"", model:"", label:I18n.t("不使用辅助视觉")}].concat(backend.auxiliaryVisionModels)
    readonly property int selectedIndex: Math.max(0, choices.findIndex(row => row.providerId === config.providerId && row.model === config.model))
    onSelectedIndexChanged: Qt.callLater(() => models.sync())
    spacing: 18

    SectionCard {
        width: parent.width
        ColumnLayout {
            width: parent.width; spacing: 14
            RowLayout {
                Layout.fillWidth: true
                Text { text: I18n.t("默认模型"); font.family: Theme.fontFamily; font.pixelSize: Theme.font(13); color: Theme.ink; Layout.fillWidth: true; wrapMode: Text.Wrap }
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
}
