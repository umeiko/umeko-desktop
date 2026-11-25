import QtQuick

Column {
    id: root
    property var activity: []
    property var selectionController: null
    property int messageIndex: -1
    property var expansionStates: ({})
    property bool layoutExpanded: false
    function updateLayoutState() {
        layoutExpanded = Object.values(expansionStates).some(
            state => state.expanded || Object.values(state.details).some(Boolean))
    }
    function expansionState(key) {
        if (!expansionStates[key]) expansionStates[key] = {expanded:false, details:({})}
        return expansionStates[key]
    }
    Connections { target: backend; function onViewChanged() { if (!root.selectionController || !root.selectionController.retainedView) root.expansionStates = ({}) } }
    spacing: 4
    visible: activity.length > 0
    Repeater {
        // Streamed replacements update delegates in place. Explicit state also
        // survives count changes, which cause QML's numeric Repeater to rebuild.
        model: root.activity.length
        Loader {
            id: step
            required property int index
            property var entry: root.activity[index] || ({kind:"", blockOffset:0})
            property var fold: root.expansionState(entry.kind + ":" + entry.blockOffset)
            width: root.width
            sourceComponent: ({text: prose, thinking: thinking, tools: tools, media: media, subagents: subagents})[entry.kind] || null

            Component {
                id: prose
                MessageBody {
                    text: step.entry.error ? I18n.t(step.entry.text || "") : step.entry.text || ""
                    markdown: !step.entry.error; textColor: step.entry.error ? Theme.danger : Theme.ink
                    preparedBlocks: step.entry._rendered || null
                    compact: step.index < root.activity.length - 1
                    selectionController: root.selectionController; messageIndex: root.messageIndex; blockOffset: step.entry.blockOffset
                }
            }
            Component {
                id: thinking
                ThinkingHistory {
                    text: step.entry.text || ""
                    expansionState: step.fold
                    onFoldChanged: root.updateLayoutState()
                    selectionController: root.selectionController; messageIndex: root.messageIndex; blockOffset: step.entry.blockOffset
                }
            }
            Component {
                id: tools
                ToolHistory {
                    tools: step.entry.tools || []
                    expansionState: step.fold
                    onFoldChanged: root.updateLayoutState()
                    selectionController: root.selectionController; messageIndex: root.messageIndex; blockOffset: step.entry.blockOffset
                }
            }
            Component {
                id: media
                ChatboxMedia {
                    items: step.entry.items || []; toolId: step.entry.toolId || ""
                    expansionState: step.fold
                    selectionController: root.selectionController; messageIndex: root.messageIndex; blockOffset: step.entry.blockOffset
                }
            }
            Component {
                id: subagents
                SubagentCards {
                    agents: step.entry.agents || []
                    selectionController: root.selectionController
                }
            }
        }
    }
}
