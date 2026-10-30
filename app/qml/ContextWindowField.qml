import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: root
    spacing: 4
    property string modelName: ""
    property string customText: ""
    property bool automatic: true
    property double providerTokens: 0
    property var suggestion: backend.contextWindowSuggestion(modelName)
    readonly property double automaticTokens: providerTokens > 0 ? providerTokens : suggestion.tokens
    signal edited(string value, bool automatic)
    RowLayout {
        Layout.fillWidth: true; spacing: 4
        InputField {
            objectName: root.objectName + "_input"
            Layout.fillWidth: true
            Layout.minimumWidth: 86
            leftPadding: 9; rightPadding: 9
            text: root.automatic ? root.automaticTokens.toString() : root.customText
            placeholderText: "256K / 1M"
            onTextEdited: root.edited(text, false)
        }
        ActionButton {
            objectName: root.objectName + "_reset"
            Layout.preferredWidth: 66
            text: root.automatic ? I18n.t("自动") : I18n.t("恢复自动")
            quiet: true
            hint: root.providerTokens > 0 ? I18n.t("自动使用供应商提供的上下文长度；输入数值可自定义") : root.automatic ? (root.suggestion.matched ? I18n.t("按模型名匹配；输入数值可自定义") : I18n.t("未匹配模型名，使用 128000 token；可自定义")) : I18n.t("恢复按原始模型名自动匹配")
            onClicked: root.edited(root.automaticTokens.toString(), true)
        }
    }
    Text {
        visible: root.providerTokens > 0
        text: I18n.t("供应商上限：") + root.providerTokens + " tokens"
        color: Theme.muted; font.pixelSize: Theme.font(10)
    }
}
