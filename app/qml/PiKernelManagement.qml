import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

SectionCard {
    id: root
    readonly property var manager: backend.piManagement
    ColumnLayout { width: parent.width; spacing: 18
        Text { font.family: Theme.fontFamily; text: I18n.t("管理与恢复"); color: Theme.ink; font.pixelSize: Theme.font(14); font.weight: Font.DemiBold }
        Text { font.family: Theme.fontFamily; text: I18n.t("在本机终端打开内嵌 Pi 的原生配置界面。退出配置后，可继续使用 pi install、pi list、pi remove 等命令。"); Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(12) }
        RowLayout { Layout.fillWidth: true
            ActionButton { objectName: "openPiTerminalButton"; text: I18n.t("在终端中管理 Pi"); glyph: "terminal"; primary: true; enabled: !root.manager.busy && !backend.kernelBusy; onClicked: root.manager.openTerminal() }
            Item { Layout.fillWidth: true }
            ActionButton { objectName: "factoryResetPiButton"; text: I18n.t("恢复出厂内核"); glyph: "refresh"; destructive: true; enabled: !root.manager.busy && !backend.kernelBusy; onClicked: factoryDialog.open() }
        }
        RowLayout { Layout.fillWidth: true; visible: root.manager.busy
            BusyIndicator { running: visible; implicitWidth: 24; implicitHeight: 24 }
            Text { font.family: Theme.fontFamily; text: root.manager.status; textFormat: Text.PlainText; Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(11) }
        }
        RowLayout { Layout.fillWidth: true
            Text { font.family: Theme.fontFamily; text: I18n.t("恢复模式：仅加载内置能力"); color: Theme.ink; font.pixelSize: Theme.font(12) }
            HelpButton { help: I18n.t("暂时跳过个人与项目中的第三方扩展、Skills、提示模板、主题和项目指令，便于从损坏的配置中恢复。关闭后可逐步重新启用扩展。原文件始终保留。") }
            Item { Layout.fillWidth: true }
            Toggle { objectName: "piRecoveryModeToggle"; checked: backend.config.agent.safeMode; enabled: !root.manager.busy && !backend.kernelBusy; onClicked: { const nextState = checked; checked = Qt.binding(() => backend.config.agent.safeMode); root.manager.setRecoveryMode(nextState) } }
        }
        ActionButton { objectName: "openPiBackupButton"; visible: root.manager.backupPath.length > 0; text: I18n.t("打开配置备份"); glyph: "folder"; quiet: true; onClicked: root.manager.openBackup() }
    }
    Popup {
        id: factoryDialog; objectName: "factoryResetPiDialog"; parent: Overlay.overlay
        modal: true; focus: true; padding: 24; width: Math.min(510, parent.width - 48); height: factoryColumn.implicitHeight + 48
        x: (parent.width - width) / 2; y: (parent.height - height) / 2
        background: Rectangle { radius: 13; color: Theme.surface; border.color: Theme.line }
        Overlay.modal: Rectangle { color: "#50000000" }
        ColumnLayout { id: factoryColumn; width: parent.width; spacing: 20
            Text { font.family: Theme.fontFamily; text: I18n.t("恢复 Pi 出厂内核"); color: Theme.ink; font.pixelSize: Theme.font(18) }
            Text { font.family: Theme.fontFamily; text: I18n.t("将备份当前 Pi 设置，恢复随应用附带的内核，并启用一套干净的配置。第三方和项目扩展暂不加载。\n\n项目文件、聊天记录、供应商及 API Key 会保留，原 Pi 配置目录与扩展文件也会保留。恢复后需重新打开 Pi 管理终端。\n\n请等待所有任务完成后再恢复。"); Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(12) }
            RowLayout { Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                ActionButton { text: I18n.t("取消"); quiet: true; onClicked: factoryDialog.close() }
                ActionButton { objectName: "confirmFactoryResetPiButton"; text: I18n.t("备份并恢复"); destructive: true; enabled: !root.manager.busy; onClicked: { factoryDialog.close(); root.manager.restoreFactory() } }
            }
        }
    }
}
