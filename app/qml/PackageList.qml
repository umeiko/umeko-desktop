import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: root
    property string namePrefix: "package"
    property bool thirdPartyOnly: true
    readonly property var manager: backend.piManagement
    readonly property var rows: manager.packages.filter(row => !thirdPartyOnly || row.removable)
    spacing: 12
    Text {
        objectName: root.namePrefix + "Progress"
        Layout.fillWidth: true; visible: text.length > 0
        text: root.manager.marketplaceProgress.message || root.manager.status
        textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Theme.accent; font.pixelSize: Theme.font(11)
    }
    Repeater {
        model: root.rows
        ColumnLayout {
            required property var modelData
            Layout.fillWidth: true; spacing: 7
            RowLayout {
                Layout.fillWidth: true
                Text { Layout.fillWidth: true; text: modelData.name + (modelData.version ? "  " + modelData.version : ""); textFormat: Text.PlainText; elide: Text.ElideRight; color: Theme.ink; font.pixelSize: Theme.font(12); font.weight: Font.DemiBold }
                Text { text: modelData.scope === "project" ? I18n.t("项目") : I18n.t("全局"); color: Theme.muted; font.pixelSize: Theme.font(10) }
                ActionButton { objectName: root.namePrefix + "Remove_" + modelData.id; visible: modelData.removable; text: I18n.t("卸载"); glyph: "trash"; quiet: true; enabled: !root.manager.busy && !backend.config.agent.safeMode; onClicked: root.manager.uninstallPackage(modelData.id) }
            }
            Text { Layout.fillWidth: true; visible: modelData.removable; text: I18n.t("安装者：") + (modelData.installedBy === "agent" ? "Agent" : modelData.installedBy === "user" ? I18n.t("用户") : I18n.t("未知（已有安装）")) + " · " + I18n.t("使用次数：") + modelData.useCount + " · " + I18n.t("最近使用：") + (modelData.lastUsed || I18n.t("暂无记录")); textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(10) }
            Text { Layout.fillWidth: true; visible: !!modelData.reason; text: I18n.t("安装原因：") + modelData.reason; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(10) }
            Text { Layout.fillWidth: true; visible: !!modelData.audit; text: I18n.t("检查备注：") + modelData.audit; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(10) }
            Repeater {
                model: modelData.extensions
                RowLayout {
                    required property var modelData
                    Layout.fillWidth: true; spacing: 10
                    Text { Layout.fillWidth: true; text: modelData.path; textFormat: Text.PlainText; elide: Text.ElideMiddle; color: Theme.muted; font.pixelSize: Theme.font(10) }
                    Text { text: modelData.enabled ? I18n.t("已启用") : I18n.t("已停用"); color: modelData.enabled ? Theme.accent : Theme.muted; font.pixelSize: Theme.font(10) }
                    Toggle { objectName: root.namePrefix + "Toggle_" + modelData.id; checked: modelData.enabled; enabled: !root.manager.busy && !backend.config.agent.safeMode; onClicked: { const state = checked; checked = Qt.binding(() => modelData.enabled); root.manager.setExtensionEnabled(modelData.id, state) } }
                }
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
        }
    }
    BusyIndicator { visible: root.manager.busy; running: visible; Layout.alignment: Qt.AlignHCenter; implicitWidth: 24; implicitHeight: 24 }
    Text { visible: !root.manager.busy && root.rows.length === 0; text: I18n.t("暂无已发现的扩展包"); Layout.fillWidth: true; color: Theme.muted; font.pixelSize: Theme.font(11) }
}
