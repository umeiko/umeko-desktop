import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Column {
    id: root
    property bool piOpen: false
    property bool toolsOpen: false
    property bool pluginsOpen: false
    property real availableHeight: 600
    signal navigated()
    function openExtensions() {
        search.clear()
        pluginsOpen = false
        piOpen = true
        toolsOpen = false
        extensionsFold.expanded = true
        packagesFold.expanded = true
    }
    readonly property Item extensionManagement: extensionManager
    function openPlugins(identifier) { piOpen = false; pluginsOpen = true; if(identifier)pluginManager.selectedId=identifier }
    spacing: 18
    onPiOpenChanged: { if (!piOpen) toolsOpen = false; else { pluginsOpen = false; backend.piManagement.scan() }; navigated() }
    onToolsOpenChanged: navigated()
    onPluginsOpenChanged: navigated()
    onVisibleChanged: if (!visible) { piOpen = false; pluginsOpen = false }
    Button {
        id: piCard
        objectName: "openPiSettingsButton"
        width: parent.width; implicitHeight: Theme.control(96); visible: !root.piOpen && !root.pluginsOpen
        padding: 20; hoverEnabled: true
        Accessible.name: I18n.t("配置 Pi Coding Agent")
        HoverHandler { cursorShape: Qt.PointingHandCursor }
        background: Rectangle { radius: 12; color: piCard.hovered ? Theme.hover : Theme.surface; border.color: piCard.activeFocus ? Theme.accent : Theme.line }
        contentItem: Item {
            Rectangle {
                id: piIcon
                width: Theme.icon(48); height: Theme.icon(48); radius: 10; color: Theme.accentBg
                anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                Image { anchors.fill: parent; source: "../icons/pi.svg"; sourceSize: Qt.size(96,96) }
            }
            Column {
                anchors.left: piIcon.right; anchors.leftMargin: 16
                anchors.right: piAction.left; anchors.rightMargin: 24
                anchors.verticalCenter: parent.verticalCenter; spacing: 7
                Row { spacing: 10
                    Text { text: "Pi Coding Agent"; color: Theme.ink; font.pixelSize: Theme.font(16); font.weight: Font.DemiBold }
                    Text { text: "v" + backend.kernelVersion; color: Theme.muted; font.pixelSize: Theme.font(11); anchors.verticalCenter: parent.verticalCenter }
                }
                Text { width: parent.width; text: I18n.t("能力、扩展、MCP 与运行配置"); color: Theme.muted; font.pixelSize: Theme.font(12); elide: Text.ElideRight }
            }
            Row {
                id: piAction; spacing: 7
                anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                Text { text: I18n.t("配置"); color: Theme.accent; font.pixelSize: Theme.font(12) }
                Glyph { name: "chevron-right"; width: Theme.icon(14); height: Theme.icon(14); anchors.verticalCenter: parent.verticalCenter }
            }
        }
        onClicked: root.piOpen = true
    }
    Button {
        id: pluginsCard
        objectName: "openDesktopPluginsButton"
        width: parent.width; implicitHeight: Theme.control(72); visible: !root.piOpen && !root.pluginsOpen
        padding: 20; hoverEnabled: true
        Accessible.name: I18n.t("插件管理")
        HoverHandler { cursorShape: Qt.PointingHandCursor }
        background: Rectangle { radius: 12; color: pluginsCard.hovered ? Theme.hover : Theme.surface; border.color: pluginsCard.activeFocus ? Theme.accent : Theme.line }
        contentItem: RowLayout {
            spacing: 16
            Rectangle {
                Layout.preferredWidth: Theme.icon(40); Layout.preferredHeight: Theme.icon(40)
                radius: 10; color: "transparent"
                Image { objectName: "pluginManagerArtwork"; anchors.centerIn: parent; source: "../icons/fluent/plugin-manager.png"; width: Theme.icon(42); height: Theme.icon(42); sourceSize: Qt.size(128,128); fillMode: Image.PreserveAspectFit; mipmap: true }
            }
            Text { text: I18n.t("插件管理"); color: Theme.ink; font.pixelSize: Theme.font(16); font.weight: Font.DemiBold; Layout.fillWidth: true }
            Glyph { name: "chevron-right"; width: Theme.icon(16); height: Theme.icon(16); color: Theme.muted }
        }
        onClicked: root.openPlugins()
    }
    Column {
        width: parent.width; visible: root.pluginsOpen; spacing: 14
        RowLayout {
            width: parent.width; spacing: 8
            ActionButton { objectName: "backFromDesktopPluginsButton"; text: "Agent"; glyph: "arrow-left"; quiet: true; onClicked: root.pluginsOpen = false }
            Glyph { name: "chevron-right"; width: Theme.icon(13); height: Theme.icon(13) }
            Text { text: I18n.t("插件管理"); color: Theme.ink; font.pixelSize: Theme.font(14); font.weight: Font.Medium }
            Item { Layout.fillWidth: true }
        }
        DesktopPluginsPage { id:pluginManager; width: parent.width; height: Math.max(360, root.availableHeight - 64) }
    }
    Column {
        width: parent.width; visible: root.piOpen && !root.toolsOpen; spacing: 18
        RowLayout { width: parent.width; spacing: 8
            ActionButton { objectName: "backToAgentButton"; text: "Agent"; glyph: "arrow-left"; quiet: true; onClicked: root.piOpen = false }
            Glyph { name: "chevron-right"; width: Theme.icon(13); height: Theme.icon(13) }
            Text { text: I18n.t("Pi 配置"); color: Theme.ink; font.pixelSize: Theme.font(14); font.weight: Font.Medium }
            Item { Layout.fillWidth: true }
            ActionButton { text: "GitHub"; glyph: "external-link"; quiet: true; onClicked: backend.openPiGithub() }
        }
        InputField { id: search; objectName: "piSettingsSearch"; width: parent.width; placeholderText: I18n.t("搜索 Pi 配置、工具、扩展…") }
        SettingsFold {
            objectName: "piFold_kernel"; width: parent.width; title: I18n.t("内核与连接"); expanded: true; query: search.text
            searchTerms: I18n.t("版本 更新 version kernel npm 镜像 网络 证书 registry CA npmrc ") + JSON.stringify(backend.piManagement.npmConfig)
            SettingsFold { objectName: "piFold_version"; width: parent.width; title: I18n.t("版本与更新"); nested: true; expanded: true; query: search.text; searchTerms: I18n.t("version kernel 内核 升级"); PiVersionCard { width: parent.width } }
            SettingsFold { objectName: "piFold_npm"; width: parent.width; title: I18n.t("npm 与网络"); nested: true; query: search.text; searchTerms: I18n.t("镜像 源 证书 registry CA npmrc 连接 ") + JSON.stringify(backend.piManagement.npmConfig); PiNpmSettings { width: parent.width } }
        }
        SettingsFold {
            id: extensionsFold
            objectName: "piFold_extensions"; width: parent.width; title: I18n.t("扩展与工具"); query: search.text
            searchTerms: I18n.t("安装 Skills MCP 服务器 builtin extensions 工具 资源 ") + JSON.stringify(backend.piManagement.extensions) + JSON.stringify(backend.agentResources)
            SettingsFold { id: packagesFold; objectName: "piFold_packages"; width: parent.width; title: I18n.t("Pi 扩展"); nested: true; query: search.text; searchTerms: I18n.t("安装 扩展包 extensions builtin ") + JSON.stringify(backend.piManagement.extensions); ExtensionManager { id: extensionManager; objectName: "agentExtensionsManager"; width: parent.width; namePrefix: "agentExtensions" } }
            SettingsFold { objectName: "piFold_mcp"; width: parent.width; title: I18n.t("MCP 服务器"); nested: true; query: search.text; searchTerms: I18n.t("builtin:mcp 全局 项目 配置服务器 JSON"); McpSettings { width: parent.width } }
            SettingsFold { objectName: "piFold_tools"; width: parent.width; title: I18n.t("工具与资源"); nested: true; query: search.text; searchTerms: I18n.t("原生 工具 Skills 提示模板 命令 资源 ") + JSON.stringify(backend.agentResources)
                SectionCard { width: parent.width; ActionButton { objectName: "openToolCatalogButton"; text: I18n.t("查看工具与资源"); glyph: "layers"; enabled: !backend.piManagement.busy && !backend.kernelBusy; onClicked: root.toolsOpen = true } }
            }
        }
        SettingsFold {
            objectName: "piFold_runtime"; width: parent.width; title: I18n.t("运行与资源"); query: search.text
            searchTerms: I18n.t("上下文 自动压缩 compaction 资源 路径 Skills 提示词 自定义指令 instructions token 回答 上限 运行 ") + [backend.config.agent.agentDir, backend.config.agent.instructions, ...(backend.config.agent.skillPaths || []), ...(backend.config.agent.extensionPaths || [])].join(" ")
            AgentSettings { width: parent.width; query: search.text; enabled: !backend.busy; opacity: enabled ? 1 : 0.6 }
        }
        SettingsFold {
            objectName: "piFold_management"; width: parent.width; title: I18n.t("管理与恢复"); query: search.text; searchTerms: I18n.t("终端 terminal 恢复出厂 备份 reset 恢复模式")
            SettingsFold { objectName: "piFold_recovery"; width: parent.width; title: I18n.t("终端与恢复"); nested: true; query: search.text; searchTerms: I18n.t("管理 terminal 恢复出厂 备份 reset 恢复模式"); PiKernelManagement { width: parent.width } }
        }

    }
    Column {
        width: parent.width; visible: root.piOpen && root.toolsOpen; spacing: 14
        RowLayout {
            width: parent.width; spacing: 8
            ActionButton { objectName: "backToPiButton"; text: I18n.t("Pi 配置"); glyph: "arrow-left"; quiet: true; onClicked: root.toolsOpen = false }
            Glyph { name: "chevron-right"; width: Theme.icon(13); height: Theme.icon(13) }
            Text { text: I18n.t("工具与资源"); color: Theme.ink; font.pixelSize: Theme.font(14); font.weight: Font.Medium }
            Item { Layout.fillWidth: true }
        }
        ToolCatalog { width: parent.width; height: Math.max(360, root.availableHeight - 64) }
    }
}
