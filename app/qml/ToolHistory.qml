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
    readonly property string summary: (running ? (commandsOnly ? "正在运行 " : "正在执行 ") : (commandsOnly ? "运行了 " : "执行了 ")) + tools.length + (commandsOnly ? " 条命令" : " 项操作") + (failures ? "（" + failures + " 失败）" : "")
    spacing: 2
    visible: tools.length > 0
    onExpandedChanged: if (!expanded && selectionController) selectionController.hideDetails(messageIndex, blockOffset + 1, tools.length)
    function command(name) { return name === "bash" || name === "powershell" }
    function action(name) { return ({read:"读取",write:"写入",edit:"编辑",bash:"运行",powershell:"运行",grep:"搜索",find:"查找",ls:"浏览",codemode:"执行代码",tool_search:"查找工具"})[name] || name }
    function preview(tool) {
        const args = tool.arguments || {}
        const value = args.command || args.code || args.pattern || args.query || args.path || ""
        return String(value).replace(/\s+/g, " ").trim()
    }
    Item {
        width: headerRow.implicitWidth; height: 22
        Row {
            id: headerRow; height: parent.height; spacing: 7
            ActivitySpinner { visible: root.running; width: 12; height: 12; anchors.verticalCenter: parent.verticalCenter }
            Text { text: root.summary; color: headerMouse.containsMouse ? Theme.ink : Theme.muted; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
            Glyph { name: root.expanded ? "chevron-down" : "chevron-right"; width: 12; height: 12; anchors.verticalCenter: parent.verticalCenter }
        }
        MouseArea {
            id: headerMouse; objectName: "toggleTools_" + root.messageIndex + "_" + root.blockOffset
            anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
            onClicked: { root.expanded = !root.expanded; root.expansionState.expanded = root.expanded }
        }
        Accessible.role: Accessible.Button; Accessible.name: root.summary; Accessible.description: root.expanded ? "已展开" : "已折叠"
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
                width: parent.width; height: 25
                Rectangle { anchors.fill: parent; radius: 4; color: rowMouse.containsMouse ? Theme.hover : "transparent" }
                MouseArea {
                    id: rowMouse; objectName: "toggleToolDetail_" + toolRow.tool.id
                    anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                    onClicked: { toolRow.details = !toolRow.details; root.expansionState.details[toolRow.tool.id] = toolRow.details }
                }
                ActivitySpinner { width: 14; height: 14; visible: toolRow.tool.state === "running"; anchors.verticalCenter: parent.verticalCenter }
                Glyph {
                    name: root.command(toolRow.tool.name) ? "terminal" : toolRow.tool.name === "edit" || toolRow.tool.name === "write" ? "edit" : "file"
                    width: 14; height: 14; visible: toolRow.tool.state !== "running"; anchors.verticalCenter: parent.verticalCenter
                }
                Text { id: verb; x: 22; text: root.action(toolRow.tool.name); color: Theme.muted; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                Text {
                    id: pathLabel; objectName: "toolPath_" + toolRow.tool.id
                    x: verb.x + verb.width + 6; width: Math.max(0, parent.width - x - 38)
                    visible: !!toolRow.tool.path
                    text: toolRow.tool.path ? toolRow.tool.path.split(/[\\/]/).pop() || toolRow.tool.path : ""
                    elide: Text.ElideMiddle; color: pathMouse.containsMouse ? Theme.accent : Theme.muted; font.pixelSize: 12; font.underline: true; anchors.verticalCenter: parent.verticalCenter
                    MouseArea {
                        id: pathMouse; width: Math.min(parent.width, parent.implicitWidth); height: parent.height
                        hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: backend.copy(toolRow.tool.path)
                    }
                    ToolTip.visible: pathMouse.containsMouse; ToolTip.text: (toolRow.tool.path || "") + "\n点击复制路径"
                }
                Text {
                    x: verb.x + verb.width + 6; width: Math.max(0, parent.width - x - 38); visible: !pathLabel.visible
                    text: root.preview(toolRow.tool); elide: Text.ElideRight; color: Theme.muted; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter
                }
                Glyph { x: parent.width - 30; width: 12; height: 12; name: toolRow.details ? "chevron-down" : "chevron-right"; anchors.verticalCenter: parent.verticalCenter }
                Text {
                    x: parent.width - 14; width: 14; text: toolRow.tool.state === "error" ? "×" : toolRow.tool.state === "interrupted" ? "!" : ""
                    color: Theme.danger; font.pixelSize: 16; anchors.verticalCenter: parent.verticalCenter
                }
                Accessible.role: Accessible.Button; Accessible.name: root.action(toolRow.tool.name) + " " + root.preview(toolRow.tool); Accessible.description: toolRow.details ? "已展开" : "已折叠"
            }
            Item {
                visible: toolRow.details; width: parent.width; height: detailText.implicitHeight + 12
                Rectangle { x: 6; y: 4; width: 1; height: parent.height - 8; color: Theme.line }
                SelectableText {
                    id: detailText; objectName: "toolDetail_" + toolRow.tool.id
                    x: 23; y: 6; width: parent.width - x; textFormat: TextEdit.PlainText; wrapMode: TextEdit.WrapAnywhere
                    selectionController: root.selectionController; messageIndex: root.messageIndex; blockIndex: root.blockOffset + toolRow.index + 1
                    conditionalSelection: true
                    text: JSON.stringify(toolRow.tool.arguments || {}, null, 2) + (toolRow.tool.result ? "\n\n" + toolRow.tool.result : "")
                    font.family: "Consolas"; font.pixelSize: 11; color: Theme.muted
                }
            }
        }
    }
}
