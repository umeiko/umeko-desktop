import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: root
    spacing: 4
    property string customText: ""
    property double contextTokens: 0
    property double providerTokens: 0
    readonly property double maximumTokens: providerTokens > 0 ? Math.min(contextTokens, providerTokens) : contextTokens
    readonly property bool valid: !customText.trim().length || (/^\d+$/.test(customText.trim()) && Number(customText) >= 1024 && Number(customText) <= maximumTokens)
    signal edited(string value)

    InputField {
        objectName: root.objectName + "_input"
        Layout.fillWidth: true
        Layout.minimumWidth: 100
        leftPadding: 9; rightPadding: 9
        text: root.customText
        placeholderText: I18n.t("默认")
        onTextEdited: root.edited(text)
        background: Rectangle {
            radius: 8; color: Theme.surface
            border.color: !root.valid ? Theme.danger : parent.activeFocus ? Theme.accent : Theme.line
        }
    }
    Text {
        text: root.maximumTokens > 0 ? "1024–" + root.maximumTokens + " tokens" : I18n.t("请先设置有效的上下文长度")
        color: root.valid ? Theme.muted : Theme.danger
        font.pixelSize: Theme.font(10)
    }
}
