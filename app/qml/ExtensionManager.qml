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
        Flow { Layout.fillWidth: true; spacing: 8
            ActionButton { objectName: root.namePrefix + "InstallButton"; text: I18n.t("安装扩展"); glyph: "plus"; primary: true; enabled: !root.manager.busy && !backend.kernelBusy; onClicked: installer.open() }
            ActionButton { objectName: root.namePrefix + "CatalogButton"; text: I18n.t("查看在线扩展"); glyph: "external-link"; quiet: true; onClicked: root.manager.openCatalog() }
            ActionButton { objectName: root.namePrefix + "RefreshButton"; text: I18n.t("刷新"); glyph: "refresh"; enabled: !root.manager.busy; onClicked: root.manager.refresh() }
        }
        Text { Layout.fillWidth: true; text: I18n.t(root.manager.status); visible: text.length > 0; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(11) }
        Text { visible: backend.config.agent.safeMode; Layout.fillWidth: true; text: I18n.t("恢复模式仅加载内置能力，第三方扩展暂不加载。"); color: Theme.accent; wrapMode: Text.Wrap; font.pixelSize: Theme.font(11) }
        Repeater { model: root.manager.extensions
            ColumnLayout { required property var modelData; Layout.fillWidth: true; spacing: 8
                RowLayout { Layout.fillWidth: true; spacing: 12
                    ActionButton {
                        id: detailsButton
                        objectName: root.namePrefix + "Details_" + modelData.id
                        Layout.fillWidth: true; Layout.preferredHeight: 54; quiet: true
                        hint: I18n.t("查看扩展详情")
                        onClicked: { details.extensionId = modelData.id; details.open(); backend.loadCapabilities() }
                        contentItem: ColumnLayout { spacing: 5
                            RowLayout { Layout.fillWidth: true
                                Text { Layout.fillWidth: true; text: modelData.name; textFormat: Text.PlainText; elide: Text.ElideRight; color: Theme.ink; font.pixelSize: Theme.font(12) }
                                Text { text: ((modelData.info || {}).origin === "community" ? I18n.t("社区扩展 · ") : modelData.source === "builtin" ? I18n.t("内置 · ") : "") + (modelData.scope === "project" ? I18n.t("项目") : I18n.t("全局")); color: Theme.muted; font.pixelSize: Theme.font(10) }
                                Glyph { name: "chevron-right"; width: Theme.icon(12); height: width }
                            }
                            Text { Layout.fillWidth: true; text: modelData.path; textFormat: Text.PlainText; elide: Text.ElideMiddle; color: Theme.muted; font.pixelSize: Theme.font(10) }
                        }
                    }
                    Text { text: modelData.enabled ? I18n.t("已启用") : I18n.t("已停用"); color: modelData.enabled ? Theme.accent : Theme.muted; font.pixelSize: Theme.font(11) }
                    Toggle { objectName: root.namePrefix + "Toggle_" + modelData.id; checked: modelData.enabled; enabled: !root.manager.busy && !backend.config.agent.safeMode; onClicked: { const nextState = checked; checked = Qt.binding(() => modelData.enabled); root.manager.setExtensionEnabled(modelData.id, nextState) } }
                }
                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
            }
        }
        BusyIndicator { visible: root.manager.busy; running: visible; Layout.alignment: Qt.AlignHCenter; implicitWidth: 24; implicitHeight: 24 }
        Text { visible: !root.manager.busy && root.manager.extensions.length === 0; text: I18n.t("暂无扩展，点击「安装扩展」粘贴 Pi 安装命令。"); Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(11) }
    }
    PiExtensionInstaller { id: installer }
    ExtensionDetails { id: details; manager: root.manager }
}
