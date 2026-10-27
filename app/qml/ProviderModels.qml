import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: root
    spacing: 10
    property int count: entries.count
    property bool fixedModels: false
    function load(models) {
        entries.clear()
        models.forEach(m => entries.append({upstream:m.upstream, alias:m.alias || "", contextWindowText:String(m.contextWindow || ""), contextWindowAuto:m.contextWindowAuto !== false, providerContextWindow:Number(m.providerContextWindow || 0), compactionThresholdText:m.compactionThreshold === null || m.compactionThreshold === undefined ? "" : String(m.compactionThreshold), visionValue:m.vision === true, visionAuto:m.visionAuto !== false}))
        if (!entries.count && !fixedModels) addModel()
    }
    function addModel() { entries.append({upstream:"", alias:"", contextWindowText:"", contextWindowAuto:true, providerContextWindow:0, compactionThresholdText:"", visionValue:false, visionAuto:true}) }
    function json() {
        let rows = []
        for(let i = 0; i < entries.count; i++) {
            let item = entries.get(i)
            rows.push({upstream:item.upstream, alias:item.alias, contextWindow:item.contextWindowText, contextWindowAuto:item.contextWindowAuto, compactionThreshold:item.compactionThresholdText, vision:item.visionValue, visionAuto:item.visionAuto})
        }
        return JSON.stringify(rows)
    }
    ListModel { id: entries }
    RowLayout {
        Layout.fillWidth: true
        Text { text: I18n.t("模型"); color: Theme.ink; font.pixelSize: Theme.font(12) }
        Text { text: entries.count.toString(); color: Theme.muted; font.pixelSize: Theme.font(11) }
        HelpButton { help: I18n.t("一个供应商可以添加多个模型。模型 ID 填服务端名称，别名用于聊天选择和 API 代理服务；别名留空时使用模型 ID。") }
        Item { Layout.fillWidth: true }
        ActionButton { visible: !root.fixedModels; objectName: "addProviderModelButton"; text: I18n.t("添加模型"); glyph: "plus"; quiet: true; onClicked: root.addModel() }
    }
    RowLayout {
        Layout.fillWidth: true; spacing: 12
        Text { text: I18n.t("模型 ID"); color: Theme.muted; font.pixelSize: Theme.font(10); Layout.fillWidth: true; Layout.preferredWidth: 1 }
        Text { text: I18n.t("别名"); color: Theme.muted; font.pixelSize: Theme.font(10); Layout.fillWidth: true; Layout.preferredWidth: 1 }
        Item { Layout.preferredWidth: 32 }
    }
    Repeater {
        model: entries
        ColumnLayout {
            required property int index
            required property string upstream
            required property string alias
            required property string contextWindowText
            required property bool contextWindowAuto
            required property double providerContextWindow
            required property string compactionThresholdText
            required property bool visionValue
            required property bool visionAuto
            Layout.fillWidth: true; spacing: 4
            RowLayout {
                Layout.fillWidth: true; spacing: 12
                InputField { objectName: "providerModelId_" + index; readOnly: root.fixedModels; Layout.fillWidth: true; Layout.preferredWidth: 1; text: upstream; placeholderText: I18n.t("服务端模型 ID"); onTextEdited: entries.setProperty(index, "upstream", text) }
                InputField { objectName: "providerModelAlias_" + index; Layout.fillWidth: true; Layout.preferredWidth: 1; text: alias; placeholderText: I18n.t("与模型 ID 相同"); onTextEdited: entries.setProperty(index, "alias", text) }
                ActionButton { visible: !root.fixedModels; glyph: "trash"; width: Theme.control(32); quiet: true; enabled: entries.count > 1; onClicked: entries.remove(index) }
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                Text { text: I18n.t("上下文长度"); color: Theme.muted; font.pixelSize: Theme.font(11) }
                HelpButton { help: I18n.t("自动优先使用供应商提供的上下文长度；未提供时按原始模型名匹配，未知名称使用 128000 token。输入整数、256K 或 1M 可自定义；K=1024，M=1048576。供应商上限为只读信息，可在模型映射中刷新。") }
                ContextWindowField {
                    id: providerContext
                    objectName: "providerContext_" + index
                    Layout.preferredWidth: 190; Layout.fillWidth: false
                    modelName: upstream; customText: contextWindowText; automatic: contextWindowAuto; providerTokens: providerContextWindow
                    onEdited: (value, automatic) => { entries.setProperty(index, "contextWindowText", value); entries.setProperty(index, "contextWindowAuto", automatic) }
                }
                Text { text: I18n.t("压缩阈值"); color: Theme.muted; font.pixelSize: Theme.font(11); Layout.leftMargin: 12 }
                HelpButton { help: I18n.t("留空保持 Pi 原生压缩设置。设置阈值后，预留 token = 上下文长度 − 阈值；近期上下文最多保留 min(20000, floor(阈值/2)) token，Pi 原生机制可能保留更少。阈值至少为 1024 token，且不能超过供应商上限与当前上下文长度中的较小值。") }
                CompactionThresholdField {
                    objectName: "providerCompaction_" + index
                    Layout.preferredWidth: 155; Layout.fillWidth: false
                    customText: compactionThresholdText; contextTokens: providerContext.effectiveTokens; providerTokens: providerContextWindow
                    onEdited: value => entries.setProperty(index, "compactionThresholdText", value)
                }
                Item { Layout.fillWidth: true }
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                VisionField {
                    objectName: "providerVision_" + index
                    Layout.preferredWidth: 190; Layout.fillWidth: false
                    modelName: upstream; visionEnabled: visionValue; automatic: visionAuto
                    onEdited: (value, automatic) => { entries.setProperty(index, "visionValue", value); entries.setProperty(index, "visionAuto", automatic) }
                }
                Item { Layout.fillWidth: true }
            }
        }
    }
}
