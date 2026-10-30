import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

SectionCard {
    id: root
    objectName: "mcpSettingsCard"
    readonly property var manager: backend.piManagement
    readonly property var extension: {
        const rows = manager.extensions
        for (let i = 0; i < rows.length; i++)
            if (rows[i].path === "builtin:mcp") return rows[i]
        return null
    }
    readonly property bool mcpEnabled: extension !== null && extension.enabled === true
    readonly property bool configurable: mcpEnabled && !manager.busy && !backend.kernelBusy
    McpInstaller { id: mcpInstaller; onAdded: { if (!mcpPanel.dirty) mcpPanel.load(); root.expanded = true; backend.loadCapabilities() } }
    property bool expanded: false
    Timer { interval: 1500; repeat: true; running: root.visible && root.expanded && root.configurable; onTriggered: backend.loadCapabilities() }
    ColumnLayout {
        width: parent.width; spacing: 14
        RowLayout {
            Layout.fillWidth: true; spacing: 10
            Text { text: "MCP"; color: Theme.ink; font.pixelSize: Theme.font(14); font.weight: Font.DemiBold }
            Text { objectName: "mcpAvailability"; text: root.manager.busy ? I18n.t("正在读取扩展状态…") : root.extension === null ? I18n.t("未检测到 builtin:mcp") : root.mcpEnabled ? I18n.t("已启用") : I18n.t("已停用"); color: root.mcpEnabled ? Theme.accent : Theme.muted; font.pixelSize: Theme.font(11) }
            Item { Layout.fillWidth: true }
            ActionButton { objectName: "addMcpButton"; text: I18n.t("添加服务器"); glyph: "plus"; enabled: root.configurable; onClicked: mcpInstaller.open() }
            ActionButton {
                objectName: "configureMcpButton"; text: root.expanded ? I18n.t("收起配置") : I18n.t("配置服务器")
                glyph: root.expanded ? "chevron-down" : "server"
                enabled: root.configurable
                onClicked: { root.expanded = !root.expanded; if (root.expanded) backend.loadCapabilities() }
            }
        }
        Text {
            objectName: "mcpDisabledReason"; Layout.fillWidth: true
            text: !root.mcpEnabled ? I18n.t("请先在插件管理 Widget 中启用 builtin:mcp，再配置 MCP 服务器。已有配置会保留。") : I18n.t("连接外部工具与资源，支持全局和当前项目的 Pi 原生配置。")
            color: Theme.muted; font.pixelSize: Theme.font(12); wrapMode: Text.Wrap
        }
        McpPanel { id: mcpPanel; Layout.fillWidth: true; visible: root.expanded; enabled: root.configurable; opacity: enabled ? 1 : 0.45 }
    }
}
