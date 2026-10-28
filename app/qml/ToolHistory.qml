import QtQuick
import QtQuick.Controls

Column {
    id: root
    property var tools: []
    property var expansionState: ({expanded:false, details:({})})
    property bool expanded: expansionState.expanded
    onExpansionStateChanged: expanded = expansionState.expanded
    property var selectionController: null
    property int messageIndex: -1
    property int blockOffset: 0
    readonly property bool running: tools.some(tool => tool.state === "running")
    readonly property int failures: tools.filter(tool => tool.state === "error").length
    readonly property bool commandsOnly: tools.length > 0 && tools.every(tool => command(tool.name))
    readonly property string summary: (running ? (commandsOnly ? I18n.t("正在运行 ") : I18n.t("正在执行 ")) : (commandsOnly ? I18n.t("运行了 ") : I18n.t("执行了 "))) + tools.length + (commandsOnly ? I18n.t(" 条命令") : I18n.t(" 项操作")) + (failures ? "（" + failures + I18n.t(" 失败）") : "")
    spacing: 2
    visible: tools.length > 0
    onExpandedChanged: if (!expanded && selectionController) selectionController.hideDetails(messageIndex, blockOffset + 1, tools.length)
    function command(name) { return name === "bash" || name === "powershell" }
    function action(name) { return ({read:I18n.t("读取"),write:I18n.t("写入"),edit:I18n.t("编辑"),bash:I18n.t("运行"),powershell:I18n.t("运行"),grep:I18n.t("搜索"),find:I18n.t("查找"),ls:I18n.t("浏览"),codemode:I18n.t("执行代码"),tool_search:I18n.t("查找工具"),submit_to_chatbox:I18n.t("展示附件")})[name] || name }
    function preview(tool) {
        const args = tool.arguments || {}
        if (tool.subagent) {
            const agent = tool.subagent
            return [agent.type || args.type || "subagent", agent.task || args.task || "", tool.state || agent.status || "", agent.isBackground ? "background" : "foreground", String(agent.toolUses || 0) + " tool uses", agent.activity || ""].filter(value => value !== "").join(" · ")
        }
        const value = args.command || args.code || args.pattern || args.query || args.path || ""
        return String(value).replace(/\s+/g, " ").trim()
    }
    function detail(tool) {
        if (tool.subagent) {
            const agent = tool.subagent
            const args = tool.arguments || {}
            return "Type: " + (agent.type || args.type || "subagent") + "\nTask: " + (agent.task || args.task || "") + "\nState: " + (tool.state || agent.status || "") + "\nMode: " + (agent.isBackground ? "background" : "foreground") + "\nTool uses: " + (agent.toolUses || 0) + "\nActivity: " + (agent.activity || "") + (agent.continued ? "\nContinued: yes" : "") + (agent.error ? "\nError: " + agent.error : "") + ((tool.result || agent.result) ? "\n\n" + (tool.result || agent.result) : "")
        }
        return JSON.stringify(tool.arguments || {}, null, 2) + (tool.result ? "\n\n" + tool.result : "")
    }
    Item {
        width: headerRow.implicitWidth; height: 22
        Row {
            id: headerRow; height: parent.height; spacing: 7
            ActivitySpinner { visible: root.running; width: Theme.icon(12); height: Theme.icon(12); anchors.verticalCenter: parent.verticalCenter }
            Text { text: root.summary; color: headerMouse.interactionHovered ? Theme.ink : Theme.muted; font.pixelSize: Theme.font(12); anchors.verticalCenter: parent.verticalCenter }
            Glyph { name: root.expanded ? "chevron-down" : "chevron-right"; width: Theme.icon(12); height: Theme.icon(12); anchors.verticalCenter: parent.verticalCenter }
        }
        ChatHitArea {
            id: headerMouse; objectName: "toggleTools_" + root.messageIndex + "_" + root.blockOffset
            anchors.fill: parent; selectionController: root.selectionController
            onClicked: { root.expanded = !root.expanded; root.expansionState.expanded = root.expanded }
        }
        Accessible.role: Accessible.Button; Accessible.name: root.summary; Accessible.description: root.expanded ? I18n.t("已展开") : I18n.t("已折叠")
    }
    Repeater {
        model: root.expanded ? root.tools.length : 0
        Column {
            id: toolRow
            required property int index
            property var tool: root.tools[index] || ({})
            property bool details: !!root.expansionState.details[tool.id]
            Connections { target: root; function onExpansionStateChanged() { toolRow.details = !!root.expansionState.details[toolRow.tool.id] } }
            width: root.width; spacing: 4
            Item {
                width: parent.width; height: Theme.control(25)
                Rectangle { anchors.fill: parent; radius: 4; color: rowMouse.interactionHovered ? Theme.hover : "transparent" }
                ChatHitArea {
                    id: rowMouse; objectName: "toggleToolDetail_" + toolRow.tool.id
                    anchors.fill: parent; selectionController: root.selectionController
                    onClicked: { toolRow.details = !toolRow.details; root.expansionState.details[toolRow.tool.id] = toolRow.details }
                }
                ActivitySpinner { width: Theme.icon(14); height: Theme.icon(14); visible: toolRow.tool.state === "running"; anchors.verticalCenter: parent.verticalCenter }
                Glyph {
                    name: root.command(toolRow.tool.name) ? "terminal" : toolRow.tool.name === "edit" || toolRow.tool.name === "write" ? "edit" : "file"
                    width: Theme.icon(14); height: Theme.icon(14); visible: toolRow.tool.state !== "running"; anchors.verticalCenter: parent.verticalCenter
                }
                Text { id: verb; x: Theme.icon(14) + 8; text: root.action(toolRow.tool.name); color: Theme.muted; font.pixelSize: Theme.font(12); anchors.verticalCenter: parent.verticalCenter }
                Text {
                    id: pathLabel; objectName: "toolPath_" + toolRow.tool.id
                    x: verb.x + verb.width + 6; width: Math.max(0, parent.width - x - 38)
                    visible: !!toolRow.tool.path
                    text: toolRow.tool.path ? toolRow.tool.path.split(/[\\/]/).pop() || toolRow.tool.path : ""
                    elide: Text.ElideMiddle; color: pathMouse.interactionHovered ? Theme.accent : Theme.muted; font.pixelSize: Theme.font(12); font.underline: true; anchors.verticalCenter: parent.verticalCenter
                    ChatHitArea {
                        id: pathMouse; width: Math.min(parent.width, parent.implicitWidth); height: parent.height
                        selectionController: root.selectionController; interactionPriority: 10; onClicked: backend.copy(toolRow.tool.path)
                    }
                    HoverTip { active: pathMouse.interactionHovered; text: (toolRow.tool.path || "") + I18n.t("\n点击复制路径") }
                }
                Text {
                    x: verb.x + verb.width + 6; width: Math.max(0, parent.width - x - 38); visible: !pathLabel.visible
                    text: root.preview(toolRow.tool); elide: Text.ElideRight; color: Theme.muted; font.pixelSize: Theme.font(12); anchors.verticalCenter: parent.verticalCenter
                }
                Glyph { x: parent.width - width - 18; width: Theme.icon(12); height: Theme.icon(12); name: toolRow.details ? "chevron-down" : "chevron-right"; anchors.verticalCenter: parent.verticalCenter }
                Text {
                    x: parent.width - 14; width: 14; text: toolRow.tool.state === "error" ? "×" : toolRow.tool.state === "interrupted" ? "!" : ""
                    color: Theme.danger; font.pixelSize: Theme.font(16); anchors.verticalCenter: parent.verticalCenter
                }
                Accessible.role: Accessible.Button; Accessible.name: root.action(toolRow.tool.name) + " " + root.preview(toolRow.tool); Accessible.description: toolRow.details ? I18n.t("已展开") : I18n.t("已折叠")
            }
            Item {
                visible: toolRow.details; width: parent.width; height: detailText.implicitHeight + 12
                Rectangle { x: 6; y: 4; width: 1; height: parent.height - 8; color: Theme.line }
                SelectableText {
                    id: detailText; objectName: "toolDetail_" + toolRow.tool.id
                    x: 23; y: 6; width: parent.width - x; textFormat: TextEdit.PlainText; wrapMode: TextEdit.WrapAnywhere
                    selectionController: root.selectionController; messageIndex: root.messageIndex; blockIndex: root.blockOffset + toolRow.index + 1
                    conditionalSelection: true
                    text: root.detail(toolRow.tool)
                    font.family: "Consolas"; font.pixelSize: Theme.font(11); color: Theme.muted
                }
            }
        }
    }
}
