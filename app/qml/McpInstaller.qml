import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: root
    objectName: "mcpInstaller"
    parent: Overlay.overlay
    readonly property var manager: backend.piManagement
    property bool submitted: false
    signal added()
    width: Math.min(650, parent.width - 48)
    height: Math.min(parent.height - 48, content.implicitHeight + 48)
    x: (parent.width - width) / 2; y: (parent.height - height) / 2
    padding: 24; modal: true; focus: true
    onOpened: { submitted = false; manager.resetInstall(); command.forceActiveFocus() }
    Connections { target: root.manager; function onChanged() { if (root.submitted && root.manager.installState === "succeeded") { root.submitted = false; root.added() } } }
    background: Rectangle { radius: 13; color: Theme.surface; border.color: Theme.line }
    Overlay.modal: Rectangle { color: "#50000000" }
    ScrollView {
        anchors.fill: parent; contentWidth: availableWidth; clip: true
        ColumnLayout {
            id: content; width: parent.width; spacing: 18
            Text { font.family: Theme.fontFamily; text: I18n.t("添加 MCP 服务器"); color: Theme.ink; font.pixelSize: Theme.font(19, visible); font.weight: Font.Medium }
            Text { font.family: Theme.fontFamily; text: I18n.t("粘贴 pi mcp add 命令，或服务器 JSON 配置。"); Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(12, visible) }
            ScrollView {
                Layout.fillWidth: true; Layout.preferredHeight: 110; contentWidth: availableWidth; clip: true
                TextArea {
                    id: command; objectName: "mcpInstallCommand"
                    textFormat: TextEdit.PlainText; color: Theme.ink; font.family: "Consolas"; font.pixelSize: Theme.font(12, visible)
                    selectByMouse: true; wrapMode: TextEdit.Wrap; padding: 14
                    placeholderText: "pi mcp add tools -- npx -y @example/mcp-server"
                    enabled: !root.manager.busy && !backend.kernelBusy
                    onTextChanged: root.manager.resetInstall()
                    background: Rectangle { radius: 8; color: Theme.bg; border.color: command.activeFocus ? Theme.accent : Theme.line }
                }
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 15
                Text { font.family: Theme.fontFamily; text: I18n.t("添加范围"); color: Theme.ink; font.pixelSize: Theme.font(12, visible) }
                Picker { id: scope; objectName: "mcpInstallScope"; Layout.fillWidth: true; model: [I18n.t("全局 · 所有项目"), I18n.t("项目 · ") + backend.workspaceName]; enabled: !root.manager.busy && !backend.kernelBusy }
            }
            Text { font.family: Theme.fontFamily; text: scope.currentIndex === 1 ? I18n.t("写入当前项目的 .pi/mcp.json。") : I18n.t("写入当前 Pi 配置目录的 mcp.json。"); Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(11, visible) }
            RowLayout {
                Layout.fillWidth: true; visible: root.manager.installMessage.length > 0
                BusyIndicator { visible: root.manager.installState === "installing"; running: visible; implicitWidth: 24; implicitHeight: 24 }
                Text { font.family: Theme.fontFamily; objectName: "mcpInstallResult"; Layout.fillWidth: true; text: root.manager.installMessage; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: root.manager.installState === "failed" ? Theme.danger : Theme.accent; font.pixelSize: Theme.font(12, visible) }
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "closeMcpInstallButton"; text: I18n.t("关闭"); quiet: true; onClicked: root.close() }
                ActionButton {
                    objectName: "confirmMcpInstallButton"; text: root.manager.installState === "installing" ? I18n.t("正在添加…") : I18n.t("添加"); primary: true
                    enabled: command.text.trim().length > 0 && !root.manager.busy && !backend.kernelBusy && (scope.currentIndex === 0 || backend.config.workspace !== "")
                    onClicked: { root.submitted = true; root.manager.addMcp(command.text, scope.currentIndex === 1) }
                }
            }
        }
    }
}
