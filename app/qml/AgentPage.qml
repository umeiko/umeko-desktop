import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Column {
    id: root
    property bool piOpen: false
    property bool toolsOpen: false
    property real availableHeight: 600
    signal navigated()
    spacing: 18
    onPiOpenChanged: { if (!piOpen) toolsOpen = false; navigated() }
    onToolsOpenChanged: navigated()
    onVisibleChanged: if (!visible) piOpen = false
    Button {
        id: piCard
        objectName: "openPiSettingsButton"
        width: parent.width; implicitHeight: 96; visible: !root.piOpen
        padding: 20; hoverEnabled: true
        Accessible.name: "配置 Pi Coding Agent"
        HoverHandler { cursorShape: Qt.PointingHandCursor }
        background: Rectangle { radius: 12; color: piCard.hovered ? Theme.hover : Theme.surface; border.color: piCard.activeFocus ? Theme.accent : Theme.line }
        contentItem: Item {
            Rectangle {
                id: piIcon
                width: 48; height: 48; radius: 10; color: Theme.accentBg
                anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                Image { anchors.fill: parent; source: "../icons/pi.svg"; sourceSize: Qt.size(96,96) }
            }
            Column {
                anchors.left: piIcon.right; anchors.leftMargin: 16
                anchors.right: piAction.left; anchors.rightMargin: 24
                anchors.verticalCenter: parent.verticalCenter; spacing: 7
                Row { spacing: 10
                    Text { text: "Pi Coding Agent"; color: Theme.ink; font.pixelSize: 16; font.weight: Font.DemiBold }
                    Text { text: "v" + backend.kernelVersion; color: Theme.muted; font.pixelSize: 11; anchors.verticalCenter: parent.verticalCenter }
                }
                Text { width: parent.width; text: "能力、扩展、MCP 与运行配置"; color: Theme.muted; font.pixelSize: 12; elide: Text.ElideRight }
            }
            Row {
                id: piAction; spacing: 7
                anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                Text { text: "配置"; color: Theme.accent; font.pixelSize: 12 }
                Glyph { name: "chevron-right"; width: 14; height: 14; anchors.verticalCenter: parent.verticalCenter }
            }
        }
        onClicked: root.piOpen = true
    }
    Column {
        width: parent.width; visible: root.piOpen && !root.toolsOpen; spacing: 18
        RowLayout { width: parent.width; spacing: 8
            ActionButton { objectName: "backToAgentButton"; text: "Agent"; glyph: "arrow-left"; quiet: true; onClicked: root.piOpen = false }
            Glyph { name: "chevron-right"; width: 13; height: 13 }
            Text { text: "Pi 配置"; color: Theme.ink; font.pixelSize: 14; font.weight: Font.Medium }
            Item { Layout.fillWidth: true }
            ActionButton { text: "GitHub"; glyph: "external-link"; quiet: true; onClicked: backend.openPiGithub() }
        }
        PiVersionCard { width: parent.width }
        PiNpmSettings { width: parent.width }
        SectionCard {
            width: parent.width
            RowLayout {
                width: parent.width; spacing: 16
                Glyph { name: "layers"; width: 22; height: 22 }
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 6
                    Text { text: "工具与资源"; color: Theme.ink; font.pixelSize: 14; font.weight: Font.DemiBold }
                    Text { Layout.fillWidth: true; text: "按来源查看原生工具、MCP、扩展和其他资源"; color: Theme.muted; font.pixelSize: 12; wrapMode: Text.Wrap }
                }
                ActionButton { objectName: "openToolCatalogButton"; text: "查看工具"; glyph: "chevron-right"; enabled: !backend.piManagement.busy && !backend.kernelBusy; onClicked: root.toolsOpen = true }
            }
        }
        ExtensionManager { width: parent.width; namePrefix: "agentExtensions" }
        McpSettings { width: parent.width }
        AgentSettings { width: parent.width; enabled: !backend.busy; opacity: enabled ? 1 : 0.6 }
        PiKernelManagement { width: parent.width }
    }
    Column {
        width: parent.width; visible: root.piOpen && root.toolsOpen; spacing: 14
        RowLayout {
            width: parent.width; spacing: 8
            ActionButton { objectName: "backToPiButton"; text: "Pi 配置"; glyph: "arrow-left"; quiet: true; onClicked: root.toolsOpen = false }
            Glyph { name: "chevron-right"; width: 13; height: 13 }
            Text { text: "工具与资源"; color: Theme.ink; font.pixelSize: 14; font.weight: Font.Medium }
            Item { Layout.fillWidth: true }
        }
        ToolCatalog { width: parent.width; height: Math.max(360, root.availableHeight - 64) }
    }
}
