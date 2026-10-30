import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "ToolCatalogData.js" as Catalog

SectionCard {
    id: root
    objectName: "toolCatalogPage"
    padding: 20
    property string section: "native"
    property string expandedName: ""
    property var resources: ({})
    property string resourceSignature: ""
    readonly property bool isTools: ["native", "mcp", "extensions"].indexOf(section) >= 0
    readonly property var rows: Catalog.entries(resources, section, search.text)
    readonly property var sections: [
        {key:"native", title:I18n.t("原生工具"), glyph:"terminal", description:I18n.t("Pi 内置的文件读写、搜索与命令工具。")},
        {key:"mcp", title:I18n.t("MCP 工具"), glyph:"server", description:I18n.t("来自 MCP 服务器的工具，标注服务器来源与调用状态。")},
        {key:"extensions", title:I18n.t("扩展工具"), glyph:"layers", description:I18n.t("内置及第三方扩展注册的工具，包括 codemode 和 tool_search。")},
        {key:"skills", title:"Skills", glyph:"spark", description:I18n.t("当前 Pi 配置与项目加载的 Skills。")},
        {key:"prompts", title:I18n.t("提示模板"), glyph:"file", description:I18n.t("当前可用的 Pi 提示模板。")},
        {key:"commands", title:I18n.t("命令"), glyph:"terminal", description:I18n.t("当前扩展注册的命令。")}
    ]
    readonly property var selected: sections.filter(s => s.key === section)[0]
    property bool ready: false
    function syncResources() {
        if (!visible) return
        const next = backend.agentResources
        const signature = JSON.stringify(next)
        // Unchanged status polls must preserve delegates, selection and scroll position.
        if (signature !== resourceSignature) { resourceSignature = signature; resources = next }
    }
    Component.onCompleted: { ready = true; if (visible) { syncResources(); backend.loadCapabilities() } }
    onVisibleChanged: if (ready && visible) { syncResources(); backend.loadCapabilities() }
    Connections { target: backend; function onChanged() { root.syncResources() } }
    onSectionChanged: { expandedName = ""; search.clear(); toolList.positionViewAtBeginning() }
    Timer { interval: 1500; repeat: true; running: root.visible; onTriggered: backend.pollCapabilities() }
    RowLayout {
        anchors.fill: parent; spacing: 20
        ColumnLayout {
            Layout.preferredWidth: root.width < 650 ? 126 : 158
            Layout.minimumWidth: Layout.preferredWidth
            Layout.maximumWidth: Layout.preferredWidth
            Layout.fillHeight: true; spacing: 6
            Text { Layout.leftMargin: 10; Layout.bottomMargin: 8; text: I18n.t("工具与资源"); color: Theme.muted; font.pixelSize: Theme.font(11) }
            Repeater {
                model: root.sections
                Button {
                    id: navButton
                    required property var modelData
                    required property int index
                    objectName: "toolCategory_" + modelData.key
                    Layout.fillWidth: true; Layout.preferredHeight: 42
                    Layout.topMargin: index === 3 ? 20 : 0
                    hoverEnabled: true
                    Accessible.name: modelData.title
                    onClicked: root.section = modelData.key
                    background: Rectangle { radius: 8; color: root.section === navButton.modelData.key ? Theme.accentBg : navButton.hovered ? Theme.hover : "transparent" }
                    contentItem: RowLayout {
                        spacing: 8
                        Glyph { name: navButton.modelData.glyph; Layout.leftMargin: 10; width: Theme.icon(16); height: Theme.icon(16) }
                        Text { Layout.fillWidth: true; text: navButton.modelData.title; color: root.section === navButton.modelData.key ? Theme.accent : Theme.ink; font.pixelSize: Theme.font(12) }
                        Text { Layout.rightMargin: 10; text: Catalog.entries(root.resources, navButton.modelData.key, "").length; color: Theme.muted; font.pixelSize: Theme.font(10) }
                    }
                }
            }
            Item { Layout.fillHeight: true }
        }
        Rectangle { Layout.fillHeight: true; width: 1; color: Theme.line }
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 12
            RowLayout {
                Layout.fillWidth: true
                Text { text: root.selected.title; color: Theme.ink; font.pixelSize: Theme.font(17); font.weight: Font.DemiBold }
                Text { objectName: "toolCatalogCount"; text: root.rows.length + I18n.t(" 项"); color: Theme.muted; font.pixelSize: Theme.font(11) }
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "refreshToolCatalogButton"; text: I18n.t("刷新"); glyph: "refresh"; quiet: true; enabled: !backend.busy && !backend.kernelBusy && !backend.piManagement.busy; onClicked: backend.loadCapabilities() }
            }
            Text { Layout.fillWidth: true; text: root.selected.description; color: Theme.muted; font.pixelSize: Theme.font(11); wrapMode: Text.Wrap }
            InputField { id: search; objectName: "toolCatalogSearch"; Layout.fillWidth: true; placeholderText: I18n.t("搜索名称、说明或来源…"); onTextChanged: { root.expandedName = ""; toolList.positionViewAtBeginning() } }
            Text { visible: backend.busy; Layout.fillWidth: true; text: backend.running ? I18n.t("任务进行中，显示当前已加载的能力。配置改动在任务结束后应用。") : I18n.t("正在同步 Pi 能力…"); color: Theme.muted; font.pixelSize: Theme.font(11); wrapMode: Text.Wrap }
            Flow {
                visible: root.section === "mcp"; Layout.fillWidth: true; spacing: 8
                Repeater {
                    model: root.resources.mcp || []
                    Text { required property var modelData; text: modelData.name + " · " + modelData.state; textFormat: Text.PlainText; color: Theme.muted; font.pixelSize: Theme.font(11) }
                }
            }
            InlineScrollView {
                id: catalogScroll
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                contentWidth: availableWidth
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                ListView {
                    id: toolList
                    objectName: "toolCatalogList"
                    width: catalogScroll.availableWidth
                    height: catalogScroll.availableHeight
                    clip: true; spacing: 8
                    model: root.rows
                    boundsBehavior: Flickable.StopAtBounds
                    WheelHandler {
                        enabled: catalogScroll.wheelActive
                        target: null
                        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                        onWheel: event => {
                            const delta = event.pixelDelta.y || event.angleDelta.y / 120 * 60
                            if (!delta) { event.accepted = false; return }
                            toolList.cancelFlick()
                            const start = toolList.originY
                            const end = start + Math.max(0, toolList.contentHeight - toolList.height)
                            toolList.contentY = Math.max(start, Math.min(end, toolList.contentY - delta))
                            event.accepted = true
                        }
                    }
                    delegate: Rectangle {
                        id: entry
                        required property var modelData
                        readonly property bool expanded: root.expandedName === modelData.name
                        width: toolList.width; height: entryBody.implicitHeight + 28
                        radius: 8; color: expanded ? Theme.bg : Theme.surface; border.color: Theme.line
                        ColumnLayout {
                            id: entryBody
                            x: 14; y: 14; width: parent.width - 28; spacing: 9
                            RowLayout {
                                Layout.fillWidth: true
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 4
                                    Text { Layout.fillWidth: true; text: (root.section === "commands" ? "/" : "") + entry.modelData.name; textFormat: Text.PlainText; elide: Text.ElideMiddle; color: Theme.ink; font.pixelSize: Theme.font(12); font.family: root.isTools || root.section === "commands" ? "Consolas" : "Microsoft YaHei UI" }
                                    Text { visible: root.section === "mcp"; Layout.fillWidth: true; text: Catalog.server(entry.modelData, root.resources); color: Theme.muted; font.pixelSize: Theme.font(10); elide: Text.ElideRight }
                                }
                                Text { visible: root.isTools; text: I18n.t(Catalog.status(entry.modelData)); color: entry.modelData.active ? Theme.accent : Theme.muted; font.pixelSize: Theme.font(10) }
                                Glyph { name: entry.expanded ? "chevron-down" : "chevron-right"; width: Theme.icon(13); height: Theme.icon(13) }
                            }
                            Text { visible: !entry.expanded && (entry.modelData.description || "") !== ""; Layout.fillWidth: true; text: entry.modelData.description || ""; textFormat: Text.PlainText; color: Theme.muted; font.pixelSize: Theme.font(11); elide: Text.ElideRight; maximumLineCount: 1 }
                            TextEdit { visible: entry.expanded; Layout.fillWidth: true; text: entry.modelData.description || I18n.t("暂无说明"); textFormat: TextEdit.PlainText; color: Theme.ink; font.pixelSize: Theme.font(12); wrapMode: TextEdit.Wrap; readOnly: true; selectByMouse: true }
                            TextEdit { visible: entry.expanded && (entry.modelData.source || entry.modelData.path || "") !== ""; Layout.fillWidth: true; text: I18n.t("来源：") + (entry.modelData.source || entry.modelData.path || ""); textFormat: TextEdit.PlainText; color: Theme.muted; font.pixelSize: Theme.font(11); wrapMode: TextEdit.Wrap; readOnly: true; selectByMouse: true }
                            Text { visible: entry.expanded && root.isTools; text: I18n.t("参数"); color: Theme.muted; font.pixelSize: Theme.font(11) }
                            TextEdit { visible: entry.expanded && root.isTools; Layout.fillWidth: true; text: entry.expanded && root.isTools ? JSON.stringify(entry.modelData.parameters || {}, null, 2) : ""; textFormat: TextEdit.PlainText; color: Theme.muted; font.family: "Consolas"; font.pixelSize: Theme.font(11); wrapMode: TextEdit.Wrap; readOnly: true; selectByMouse: true }
                        }
                        Button {
                            objectName: "toolEntry_" + entry.modelData.name
                            width: parent.width; height: entry.expanded ? 48 : parent.height
                            Accessible.name: (entry.expanded ? I18n.t("收起 ") : I18n.t("展开 ")) + entry.modelData.name
                            background: Item { }
                            onClicked: root.expandedName = entry.expanded ? "" : entry.modelData.name
                        }
                    }
                    Text {
                        visible: root.rows.length === 0
                        width: parent.width - 24; x: 12; y: 28
                        text: search.text.trim() ? I18n.t("没有匹配的项目") : backend.busy ? I18n.t("正在读取 Pi 能力…") : root.section === "mcp" ? I18n.t("尚未发现 MCP 工具。请在 Pi 配置中启用 builtin:mcp 并连接服务器。") : I18n.t("当前没有可用项目")
                        wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(12); horizontalAlignment: Text.AlignHCenter
                    }
                }
            }
        }
    }
}
