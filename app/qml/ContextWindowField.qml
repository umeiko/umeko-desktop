import QtQuick
import QtQuick.Layouts

RowLayout {
    id: root
    spacing: 4
    property string modelName: ""
    property string customText: ""
    property bool automatic: true
    property var suggestion: backend.contextWindowSuggestion(modelName)
    signal edited(string value, bool automatic)

    InputField {
        objectName: root.objectName + "_input"
        Layout.fillWidth: true
        Layout.minimumWidth: 86
        leftPadding: 9; rightPadding: 9
        text: root.automatic ? root.suggestion.tokens.toString() : root.customText
        placeholderText: "256K / 1M"
        onTextEdited: root.edited(text, false)
    }
    ActionButton {
        objectName: root.objectName + "_reset"
        Layout.preferredWidth: 66
        text: root.automatic ? "自动" : "恢复自动"
        quiet: true
        hint: root.automatic ? (root.suggestion.matched ? "按模型名匹配；输入数值可自定义" : "未匹配模型名，使用 128000 token；可自定义") : "恢复按原始模型名自动匹配"
        onClicked: root.edited(root.suggestion.tokens.toString(), true)
    }
}
