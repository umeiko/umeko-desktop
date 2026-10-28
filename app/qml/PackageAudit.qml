import QtQuick
import QtQuick.Controls
import "PackageText.js" as PackageText

SettingsFold {
    id: root
    property var value: ""
    readonly property var audit: backend.piManagement.auditPresentation(value)
    readonly property string summary: PackageText.auditSummary(audit, I18n.t)
    title: I18n.t("检查备注：") + summary
    nested: true
    wrapTitle: true
    Text {
        width: parent.width
        text: I18n.t("检查仅匹配源码模式，不代表安全保证。")
        textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(10)
    }
    Repeater {
        model: root.opened ? root.audit.findings : []
        Text {
            required property var modelData
            width: parent.width; text: PackageText.finding(modelData, I18n.t)
            textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(10)
        }
    }
    Text {
        width: parent.width; visible: !!root.audit.note; text: I18n.t(root.audit.note || "")
        textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(10)
    }
}
