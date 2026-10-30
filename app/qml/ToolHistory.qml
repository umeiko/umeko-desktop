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
    function action(name) { return ({read:I18n.t("读取"),write:I18n.t("写入"),edit:I18n.t("编辑"),bash:I18n.t("运行"),powershell:I18n.t("运行"),grep:I18n.t("搜索"),find:I18n.t("查找"),ls:I18n.t("浏览"),codemode:I18n.t("执行代码"),tool_search:I18n.t("查找工具"),submit_to_chatbox:I18n.t("展示附件"),subagent:I18n.t("子代理"),marketplace_search:I18n.t("搜索扩展包"),marketplace_detail:I18n.t("读取扩展包详情"),marketplace_audit:I18n.t("检查扩展包"),marketplace_install:I18n.t("安装扩展包")})[name] || name }
    function agentType(value) {
        return ({"general-purpose":I18n.t("通用"), Explore:I18n.t("探索"), Plan:I18n.t("规划")})[value] || value || I18n.t("子代理")
    }
    function agentState(value) {
        return ({queued:I18n.t("排队中"), running:I18n.t("运行中"), done:I18n.t("已完成"), completed:I18n.t("已完成"), error:I18n.t("出错"), interrupted:I18n.t("已中断"), aborted:I18n.t("已取消"), stopped:I18n.t("已停止")})[value] || value || ""
    }
    function agentMode(agent) { return agent.isBackground ? I18n.t("后台") : I18n.t("前台") }
    function agentActivity(value) { return value === "Continuing" ? I18n.t("继续执行中") : value || "" }
    function preview(tool) {
        const args = tool.arguments || {}
        if (tool.subagent) {
            const agent = tool.subagent
            return [agentType(agent.type || args.type), agentState(tool.state || agent.status), agentMode(agent), I18n.t("调用工具 %1 次").replace("%1", agent.toolUses || 0), agent.task || args.task || "", agentActivity(agent.activity)].filter(value => value !== "").join(" · ").replace(/\s+/g, " ").trim()
        }
        const value = args.command || args.code || args.pattern || args.query || args.path || ""
        return String(value).replace(/\s+/g, " ").trim()
    }
    function detail(tool) {
        if (tool.subagent) {
            const agent = tool.subagent
            const args = tool.arguments || {}
            const lines = [I18n.t("类型：") + agentType(agent.type || args.type),
                           I18n.t("任务：") + (agent.task || args.task || ""),
                           I18n.t("状态：") + agentState(tool.state || agent.status),
                           I18n.t("模式：") + agentMode(agent),
                           I18n.t("工具调用次数：") + (agent.toolUses || 0),
                           I18n.t("活动：") + agentActivity(agent.activity)]
            if (agent.continued) lines.push(I18n.t("已继续：是"))
            if (agent.error) lines.push(I18n.t("错误：") + I18n.t(agent.error))
            return lines.join("\n") + ((tool.result || agent.result) ? "\n\n" + (tool.result || agent.result) : "")
        }
        return JSON.stringify(tool.arguments || {}, null, 2) + (tool.result ? "\n\n" + tool.result : "")
    }
    Item {
        width: headerRow.implicitWidth; height: Theme.control(22)
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
                Glyph {
                    name: root.command(toolRow.tool.name) ? "terminal" : toolRow.tool.name === "edit" || toolRow.tool.name === "write" ? "edit" : "file"
                    width: Theme.icon(14); height: Theme.icon(14); anchors.verticalCenter: parent.verticalCenter
                }
                Text { id: verb; x: Theme.icon(14) + 8; text: root.action(toolRow.tool.name); color: Theme.muted; font.pixelSize: Theme.font(12); anchors.verticalCenter: parent.verticalCenter }
                Text {
                    id: pathLabel; objectName: "toolPath_" + toolRow.tool.id
                    x: verb.x + verb.width + 6; width: Math.max(0, parent.width - x - Theme.control(42))
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
                    x: verb.x + verb.width + 6; width: Math.max(0, parent.width - x - Theme.control(42)); visible: !pathLabel.visible
                    text: root.preview(toolRow.tool); elide: Text.ElideRight; color: Theme.muted; font.pixelSize: Theme.font(12); anchors.verticalCenter: parent.verticalCenter
                }
                Glyph { x: parent.width - width - Theme.control(22); width: Theme.icon(12); height: Theme.icon(12); name: toolRow.details ? "chevron-down" : "chevron-right"; anchors.verticalCenter: parent.verticalCenter }
                Glyph {
                    objectName: "toolState_" + toolRow.tool.id
                    x: parent.width - width; width: Theme.icon(14); height: width; anchors.verticalCenter: parent.verticalCenter
                    visible: ["running","queued","error","interrupted","aborted","stopped"].includes(toolRow.tool.state)
                    name: ["running","queued"].includes(toolRow.tool.state) ? "hourglass" : toolRow.tool.state === "error" ? "x" : "stop"
                    color: toolRow.tool.state === "error" ? Theme.danger : Theme.muted
                    Accessible.name: root.agentState(toolRow.tool.state)
                    HoverHandler { id: stateHover }
                    HoverTip { active: stateHover.hovered; text: root.agentState(toolRow.tool.state) }
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
