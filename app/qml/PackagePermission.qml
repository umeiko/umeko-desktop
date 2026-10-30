import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: root
    property string namePrefix: "package"
    readonly property var manager: backend.piManagement
    spacing: 8
    Text { objectName: root.namePrefix + "PermissionTitle"; text: I18n.t("扩展包安装权限"); color: Theme.ink; font.pixelSize: Theme.font(12); font.weight: Font.DemiBold }
    RowLayout {
        Layout.fillWidth: true; spacing: 8
        ActionButton { objectName: root.namePrefix + "PermissionAsk"; text: I18n.t("安装前询问（默认）"); Layout.fillWidth: true; primary: root.manager.installPermission === "ask"; quiet: true; onClicked: root.manager.setInstallPermission("ask") }
        ActionButton { objectName: root.namePrefix + "PermissionAutomatic"; text: I18n.t("自动安装"); Layout.fillWidth: true; primary: root.manager.installPermission === "automatic"; quiet: true; onClicked: root.manager.setInstallPermission("automatic") }
    }
    Text { Layout.fillWidth: true; text: root.manager.installPermission === "automatic" ? I18n.t("Agent 可自动安装扩展包；来源检查和安装记录仍会保留。") : I18n.t("Agent 找到扩展后会先请求你的确认，再安装。"); wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(10) }
}
