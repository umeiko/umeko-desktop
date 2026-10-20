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
    property bool expanded: false
    Timer { interval: 1500; repeat: true; running: root.visible && root.expanded && root.configurable; onTriggered: backend.loadCapabilities() }
    ColumnLayout {
        width: parent.width; spacing: 14
        RowLayout {
            Layout.fillWidth: true; spacing: 10
            Text { text: "MCP"; color: Theme.ink; font.pixelSize: 14; font.weight: Font.DemiBold }
            Text { objectName: "mcpAvailability"; text: root.manager.busy ? "正在读取扩展状态…" : root.extension === null ? "未检测到 builtin:mcp" : root.mcpEnabled ? "已启用" : "已停用"; color: root.mcpEnabled ? Theme.accent : Theme.muted; font.pixelSize: 11 }
            Item { Layout.fillWidth: true }
            ActionButton {
                objectName: "configureMcpButton"; text: root.expanded ? "收起配置" : "配置服务器"
                glyph: root.expanded ? "chevron-down" : "server"
                enabled: root.configurable
                onClicked: { root.expanded = !root.expanded; if (root.expanded) backend.loadCapabilities() }
            }
        }
        Text {
            objectName: "mcpDisabledReason"; Layout.fillWidth: true
            text: !root.mcpEnabled ? "请先在上方「Pi 扩展」中启用 builtin:mcp，再配置 MCP 服务器。已有配置会保留。" : "连接外部工具与资源，支持全局和当前项目的 Pi 原生配置。"
            color: Theme.muted; font.pixelSize: 12; wrapMode: Text.Wrap
        }
        McpPanel { Layout.fillWidth: true; visible: root.expanded; enabled: root.configurable; opacity: enabled ? 1 : 0.45 }
    }
}
