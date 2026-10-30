import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

SectionCard {
    id: root
    property string namePrefix: "kernelExtensions"
    readonly property var manager: backend.piManagement
    property bool ready: false
    Component.onCompleted: { ready = true; if (visible) manager.scan() }
    onVisibleChanged: if (ready && visible) manager.scan()
    ColumnLayout { width: parent.width; spacing: 16
        RowLayout { Layout.fillWidth: true
            Text { text: I18n.t("Pi 扩展"); color: Theme.ink; font.pixelSize: Theme.font(14); font.weight: Font.DemiBold }
            HelpButton { help: I18n.t("显示 Pi 原生发现的内置、全局、项目和扩展包资源，包括已停用的扩展。开关写入 Pi 自身设置，与 pi config 共用。运行中的任务继续使用已加载的能力，完成后应用更改。扫描不会执行扩展或自动下载扩展包。") }
            Item { Layout.fillWidth: true }
        }
        PackagePermission { Layout.fillWidth: true; namePrefix: root.namePrefix }
        Flow { Layout.fillWidth: true; spacing: 8
            ActionButton { objectName: root.namePrefix + "InstallButton"; text: I18n.t("安装扩展"); glyph: "plus"; primary: true; enabled: !root.manager.busy && !backend.kernelBusy; onClicked: installer.open() }
            ActionButton { objectName: root.namePrefix + "CatalogButton"; text: I18n.t("查看在线扩展"); glyph: "external-link"; quiet: true; onClicked: root.manager.openCatalog() }
            ActionButton { objectName: root.namePrefix + "RefreshButton"; text: I18n.t("刷新"); glyph: "refresh"; enabled: !root.manager.busy; onClicked: root.manager.refresh() }
        }
        Text { visible: backend.config.agent.safeMode; Layout.fillWidth: true; text: I18n.t("恢复模式仅加载内置能力，第三方扩展暂不加载。"); color: Theme.accent; wrapMode: Text.Wrap; font.pixelSize: Theme.font(11) }
        PackageList {
            Layout.fillWidth: true; namePrefix: root.namePrefix; thirdPartyOnly: false; showDetails: true
            onDetailsRequested: extensionId => { details.extensionId = extensionId; details.open(); backend.loadCapabilities() }
        }
    }
    PiExtensionInstaller { id: installer }
    ExtensionDetails { id: details; manager: root.manager }
}
