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
        models.forEach(m => entries.append({upstream:m.upstream, alias:m.alias || "", contextWindowText:String(m.contextWindow || ""), contextWindowAuto:m.contextWindowAuto !== false, visionValue:m.vision === true, visionAuto:m.visionAuto !== false}))
        if (!entries.count && !fixedModels) addModel()
    }
    function addModel() { entries.append({upstream:"", alias:"", contextWindowText:"", contextWindowAuto:true, visionValue:false, visionAuto:true}) }
    function json() {
        let rows = []
        for(let i = 0; i < entries.count; i++) {
            let item = entries.get(i)
            rows.push({upstream:item.upstream, alias:item.alias, contextWindow:item.contextWindowText, contextWindowAuto:item.contextWindowAuto, vision:item.visionValue, visionAuto:item.visionAuto})
        }
        return JSON.stringify(rows)
    }
    ListModel { id: entries }
    RowLayout {
        Layout.fillWidth: true
        Text { text: "模型"; color: Theme.ink; font.pixelSize: 12 }
        Text { text: entries.count.toString(); color: Theme.muted; font.pixelSize: 11 }
        HelpButton { help: "一个供应商可以添加多个模型。模型 ID 填服务端名称，别名用于聊天选择和 API 代理服务；别名留空时使用模型 ID。" }
        Item { Layout.fillWidth: true }
        ActionButton { visible: !root.fixedModels; objectName: "addProviderModelButton"; text: "添加模型"; glyph: "plus"; quiet: true; onClicked: root.addModel() }
    }
    RowLayout {
        Layout.fillWidth: true; spacing: 12
        Text { text: "模型 ID"; color: Theme.muted; font.pixelSize: 10; Layout.fillWidth: true; Layout.preferredWidth: 1 }
        Text { text: "别名"; color: Theme.muted; font.pixelSize: 10; Layout.fillWidth: true; Layout.preferredWidth: 1 }
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
            required property bool visionValue
            required property bool visionAuto
            Layout.fillWidth: true; spacing: 4
            RowLayout {
                Layout.fillWidth: true; spacing: 12
                InputField { objectName: "providerModelId_" + index; readOnly: root.fixedModels; Layout.fillWidth: true; Layout.preferredWidth: 1; text: upstream; placeholderText: "服务端模型 ID"; onTextEdited: entries.setProperty(index, "upstream", text) }
                InputField { objectName: "providerModelAlias_" + index; Layout.fillWidth: true; Layout.preferredWidth: 1; text: alias; placeholderText: "与模型 ID 相同"; onTextEdited: entries.setProperty(index, "alias", text) }
                ActionButton { visible: !root.fixedModels; glyph: "trash"; width: 32; quiet: true; enabled: entries.count > 1; onClicked: entries.remove(index) }
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                Text { text: "上下文长度"; color: Theme.muted; font.pixelSize: 11 }
                HelpButton { help: "自动按原始模型名匹配，未知名称使用 128000 token。输入整数、256K 或 1M 可自定义；K=1024，M=1048576。恢复自动后跟随模型名。请按供应商实际额度填写。" }
                ContextWindowField {
                    objectName: "providerContext_" + index
                    Layout.preferredWidth: 190; Layout.fillWidth: false
                    modelName: upstream; customText: contextWindowText; automatic: contextWindowAuto
                    onEdited: (value, automatic) => { entries.setProperty(index, "contextWindowText", value); entries.setProperty(index, "contextWindowAuto", automatic) }
                }
                VisionField {
                    objectName: "providerVision_" + index
                    Layout.leftMargin: 12; Layout.preferredWidth: 190; Layout.fillWidth: false
                    modelName: upstream; visionEnabled: visionValue; automatic: visionAuto
                    onEdited: (value, automatic) => { entries.setProperty(index, "visionValue", value); entries.setProperty(index, "visionAuto", automatic) }
                }
                Item { Layout.fillWidth: true }
            }
        }
    }
}
