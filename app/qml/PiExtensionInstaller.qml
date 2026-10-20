import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: root
    objectName: "piExtensionInstaller"
    parent: Overlay.overlay
    readonly property var manager: backend.piManagement
    readonly property bool commandIsLocal: /(^|\s)(--local|-l)(\s|$)/.test(command.text)
    width: Math.min(620, parent.width - 48)
    height: Math.min(parent.height - 48, installColumn.implicitHeight + 48)
    x: (parent.width - width) / 2; y: (parent.height - height) / 2
    padding: 24; modal: true; focus: true
    onOpened: { manager.resetInstall(); command.forceActiveFocus() }
    background: Rectangle { radius: 13; color: Theme.surface; border.color: Theme.line }
    Overlay.modal: Rectangle { color: "#50000000" }
    ScrollView {
        anchors.fill: parent; contentWidth: availableWidth; clip: true
        ColumnLayout {
            id: installColumn; width: parent.width; spacing: 18
            Text { text: "安装 Pi 扩展"; color: Theme.ink; font.pixelSize: 19; font.weight: Font.Medium }
            Text { text: "粘贴 Pi 安装命令，或直接输入 npm、Git、本地路径来源。"; Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: 12 }
            InputField {
                id: command; objectName: "piInstallCommand"; Layout.fillWidth: true
                placeholderText: "pi install npm:billion-context"; font.family: "Consolas"
                enabled: !root.manager.busy && !backend.kernelBusy
                onTextChanged: if (/(^|\s)(--local|-l)(\s|$)/.test(text)) scope.currentIndex = 1
                onTextEdited: root.manager.resetInstall()
                onAccepted: if (installButton.enabled) installButton.clicked()
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 15
                Text { text: "安装范围"; color: Theme.ink; font.pixelSize: 12 }
                Picker { id: scope; objectName: "piInstallScope"; Layout.fillWidth: true; model: ["全局 · 所有项目", "项目 · " + backend.workspaceName]; enabled: !root.manager.busy && !backend.kernelBusy && !root.commandIsLocal }
            }
            Text { text: root.commandIsLocal ? "命令中的 --local / -l 已选择项目范围，移除此参数后可切换范围。" : scope.currentIndex === 1 ? "写入当前项目的 .pi/settings.json。" : "写入当前 Pi 配置目录的 settings.json。"; Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: 11 }
            RowLayout {
                Layout.fillWidth: true; visible: root.manager.installMessage.length > 0
                BusyIndicator { visible: root.manager.installState === "installing"; running: visible; implicitWidth: 24; implicitHeight: 24 }
                Text { objectName: "piInstallResult"; Layout.fillWidth: true; text: root.manager.installMessage; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: root.manager.installState === "failed" ? Theme.danger : Theme.accent; font.pixelSize: 12 }
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "closePiInstallButton"; text: root.manager.installState === "installing" ? "后台继续" : "关闭"; quiet: true; onClicked: root.close() }
                ActionButton {
                    id: installButton; objectName: "confirmPiInstallButton"
                    text: root.manager.installState === "installing" ? "正在安装…" : "安装"; primary: true
                    enabled: command.text.trim().length > 0 && !root.manager.busy && !backend.kernelBusy
                    onClicked: root.manager.installExtension(command.text, scope.currentIndex === 1)
                }
            }
        }
    }
}
