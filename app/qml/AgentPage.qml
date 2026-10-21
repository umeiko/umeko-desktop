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
    onPiOpenChanged: { if (!piOpen) toolsOpen = false; else backend.piManagement.scan(); navigated() }
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
        InputField { id: search; objectName: "piSettingsSearch"; width: parent.width; placeholderText: "搜索 Pi 配置、工具、扩展…" }
        SettingsFold {
            objectName: "piFold_kernel"; width: parent.width; title: "内核与连接"; expanded: true; query: search.text
            searchTerms: "版本 更新 version kernel npm 镜像 网络 证书 registry CA npmrc " + JSON.stringify(backend.piManagement.npmConfig)
            SettingsFold { objectName: "piFold_version"; width: parent.width; title: "版本与更新"; nested: true; expanded: true; query: search.text; searchTerms: "version kernel 内核 升级"; PiVersionCard { width: parent.width } }
            SettingsFold { objectName: "piFold_npm"; width: parent.width; title: "npm 与网络"; nested: true; query: search.text; searchTerms: "镜像 源 证书 registry CA npmrc 连接 " + JSON.stringify(backend.piManagement.npmConfig); PiNpmSettings { width: parent.width } }
        }
        SettingsFold {
            objectName: "piFold_extensions"; width: parent.width; title: "扩展与工具"; query: search.text
            searchTerms: "安装 Skills MCP 服务器 builtin extensions 工具 资源 " + JSON.stringify(backend.piManagement.extensions) + JSON.stringify(backend.agentResources)
            SettingsFold { objectName: "piFold_packages"; width: parent.width; title: "Pi 扩展"; nested: true; query: search.text; searchTerms: "安装 扩展包 extensions builtin " + JSON.stringify(backend.piManagement.extensions); ExtensionManager { width: parent.width; namePrefix: "agentExtensions" } }
            SettingsFold { objectName: "piFold_mcp"; width: parent.width; title: "MCP 服务器"; nested: true; query: search.text; searchTerms: "builtin:mcp 全局 项目 配置服务器 JSON"; McpSettings { width: parent.width } }
            SettingsFold { objectName: "piFold_tools"; width: parent.width; title: "工具与资源"; nested: true; query: search.text; searchTerms: "原生 工具 Skills 提示模板 命令 资源 " + JSON.stringify(backend.agentResources)
                SectionCard { width: parent.width; ActionButton { objectName: "openToolCatalogButton"; text: "查看工具与资源"; glyph: "layers"; enabled: !backend.piManagement.busy && !backend.kernelBusy; onClicked: root.toolsOpen = true } }
            }
        }
        SettingsFold {
            objectName: "piFold_runtime"; width: parent.width; title: "运行与资源"; query: search.text
            searchTerms: "上下文 自动压缩 compaction 资源 路径 Skills 提示词 自定义指令 instructions token 回答 上限 运行 " + [backend.config.agent.agentDir, backend.config.agent.instructions, ...(backend.config.agent.skillPaths || []), ...(backend.config.agent.extensionPaths || [])].join(" ")
            AgentSettings { width: parent.width; query: search.text; enabled: !backend.busy; opacity: enabled ? 1 : 0.6 }
        }
        SettingsFold {
            objectName: "piFold_management"; width: parent.width; title: "管理与恢复"; query: search.text; searchTerms: "终端 terminal 恢复出厂 备份 reset 恢复模式"
            SettingsFold { objectName: "piFold_recovery"; width: parent.width; title: "终端与恢复"; nested: true; query: search.text; searchTerms: "管理 terminal 恢复出厂 备份 reset 恢复模式"; PiKernelManagement { width: parent.width } }
        }

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
