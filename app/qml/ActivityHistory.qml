import QtQuick

Column {
    id: root
    property var activity: []
    property var selectionController: null
    property int messageIndex: -1
    property var expansionStates: ({})
    function expansionState(key) {
        if (!expansionStates[key]) expansionStates[key] = {expanded:false, details:({})}
        return expansionStates[key]
    }
    Connections { target: backend; function onViewChanged() { root.expansionStates = ({}) } }
    spacing: 4
    visible: activity.length > 0
    Repeater {
        // Streamed replacements update delegates in place. Explicit state also
        // survives count changes, which cause QML's numeric Repeater to rebuild.
        model: root.activity.length
        Column {
            id: step
            required property int index
            property var entry: root.activity[index] || ({kind:"", blockOffset:0})
            property var fold: root.expansionState(entry.kind + ":" + entry.blockOffset)
            width: root.width
            MessageBody {
                width: parent.width; visible: step.entry.kind === "text"
                text: visible ? (step.entry.error ? I18n.t(step.entry.text || "") : step.entry.text || "") : ""
                markdown: !step.entry.error; textColor: step.entry.error ? Theme.danger : Theme.ink
                compact: step.index < root.activity.length - 1
                selectionController: root.selectionController; messageIndex: root.messageIndex; blockOffset: step.entry.blockOffset
            }
            ThinkingHistory {
                width: parent.width; visible: step.entry.kind === "thinking"
                text: visible ? step.entry.text || "" : ""
                expansionState: step.fold
                selectionController: root.selectionController; messageIndex: root.messageIndex; blockOffset: step.entry.blockOffset
            }
            ToolHistory {
                width: parent.width; visible: step.entry.kind === "tools"
                tools: visible ? step.entry.tools || [] : []
                expansionState: step.fold
                selectionController: root.selectionController; messageIndex: root.messageIndex; blockOffset: step.entry.blockOffset
            }
            ChatboxMedia {
                width: parent.width; visible: step.entry.kind === "media"
                items: visible ? step.entry.items || [] : []; toolId: step.entry.toolId || ""
                expansionState: step.fold
                selectionController: root.selectionController; messageIndex: root.messageIndex; blockOffset: step.entry.blockOffset
            }
            SubagentCards {
                width: parent.width; visible: step.entry.kind === "subagents"
                agents: visible ? step.entry.agents || [] : []
                selectionController: root.selectionController
            }
        }
    }
}
