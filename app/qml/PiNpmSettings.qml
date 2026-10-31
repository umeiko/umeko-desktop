import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

SectionCard {
    id: root
    readonly property var manager: backend.piManagement
    function save() {
        return manager.saveNpmConfig(JSON.stringify({npmRegistry: registry.text, npmUserconfig: userconfig.text, npmCafile: cafile.text}))
    }
    ColumnLayout {
        width: parent.width; spacing: 12
        RowLayout {
            Layout.fillWidth: true
            Text { font.family: Theme.fontFamily; text: I18n.t("npm 与扩展安装"); color: Theme.ink; font.pixelSize: Theme.font(14, visible); font.weight: Font.DemiBold }
            HelpButton { help: I18n.t("扩展安装、Pi 内核检查/更新和新打开的管理终端共用此配置。留空沿用 npm 的 .npmrc 和环境配置。只影响 Umeko 启动的进程，不修改系统 npm 设置。登录令牌、代理、scoped registry 等高级配置可写在指定的 .npmrc 中。") }
            Item { Layout.fillWidth: true }
        }
        Text { font.family: Theme.fontFamily; text: I18n.t("npm 镜像源"); color: Theme.ink; font.pixelSize: Theme.font(12, visible) }
        InputField { id: registry; objectName: "piNpmRegistry"; Layout.fillWidth: true; text: root.manager.npmConfig.npmRegistry || ""; placeholderText: I18n.t("填写公司 npm 源的完整 HTTP(S) 地址；留空继承 npm 配置") }
        Text { font.family: Theme.fontFamily; text: registry.text.trim() ? I18n.t("本应用指定的 npm 源") : I18n.t("当前沿用 npm 原生配置；检测连接可查看实际使用的源"); color: Theme.muted; font.pixelSize: Theme.font(11, visible); Layout.fillWidth: true; wrapMode: Text.Wrap }
        Text { font.family: Theme.fontFamily; text: I18n.t(".npmrc 配置文件（可选）"); color: Theme.ink; font.pixelSize: Theme.font(12, visible) }
        InputField { id: userconfig; objectName: "piNpmUserconfig"; Layout.fillWidth: true; text: root.manager.npmConfig.npmUserconfig || ""; placeholderText: I18n.t("已有 .npmrc 文件的完整路径，可包含登录与代理配置") }
        Text { font.family: Theme.fontFamily; text: I18n.t("CA 证书文件（可选）"); color: Theme.ink; font.pixelSize: Theme.font(12, visible) }
        InputField { id: cafile; objectName: "piNpmCafile"; Layout.fillWidth: true; text: root.manager.npmConfig.npmCafile || ""; placeholderText: I18n.t("公司 npm 源使用的 PEM 证书文件路径") }
        Text { font.family: Theme.fontFamily; visible: text.length > 0; text: root.manager.npmStatus; color: Theme.muted; font.pixelSize: Theme.font(11, visible); Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.PlainText }
        RowLayout {
            Layout.fillWidth: true; spacing: 8
            ActionButton { objectName: "resetPiNpmConfig"; text: I18n.t("沿用 npm 配置"); quiet: true; enabled: !root.manager.busy && !backend.kernelBusy; onClicked: { registry.text = ""; userconfig.text = ""; cafile.text = ""; root.save() } }
            Item { Layout.fillWidth: true }
            BusyIndicator { visible: root.manager.busy; running: visible; implicitWidth: 22; implicitHeight: 22 }
            ActionButton { objectName: "testPiNpmConfig"; text: I18n.t("保存并检测"); enabled: !root.manager.busy && !backend.kernelBusy; onClicked: { if (root.save()) root.manager.testNpmConfig() } }
            ActionButton { objectName: "savePiNpmConfig"; text: I18n.t("保存"); primary: true; enabled: !root.manager.busy && !backend.kernelBusy; onClicked: root.save() }
        }
    }
}
