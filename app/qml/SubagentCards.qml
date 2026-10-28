import QtQuick

Column {
    id: root
    property var agents: []
    property var selectionController: null
    spacing: 8
    Repeater {
        model: root.agents.length
        Rectangle {
            id: card
            required property int index
            property var agent: root.agents[index] || ({})
            readonly property var current: backend.subagents.agents.find(row => row.id === agent.id) || agent
            objectName: "subagentCard_" + agent.id
            width: Math.min(root.width, 300); height: Theme.control(65); radius: 9
            color: hit.pressed ? Theme.accentBg : hit.interactionHovered ? Theme.hover : Theme.surface
            border.color: hit.interactionHovered ? Qt.alpha(Theme.accent,0.5) : Theme.line
            SubagentAvatar { x: 10; anchors.verticalCenter: parent.verticalCenter; width: 41; height: 41; slot: card.current.avatarSlot || 0 }
            Column {
                x: 62; anchors.verticalCenter: parent.verticalCenter; width: Math.max(0,parent.width-x-29); spacing: 5
                Text { width: parent.width; text: card.current.name || I18n.t("子代理"); textFormat: Text.PlainText; color: Theme.ink; font.pixelSize: Theme.font(12); elide: Text.ElideRight }
                Text { width: parent.width; text: card.current.task || card.agent.task || card.current.type || ""; textFormat: Text.PlainText; color: Theme.muted; font.pixelSize: Theme.font(10); elide: Text.ElideRight }
            }
            Glyph { anchors.right: parent.right; anchors.rightMargin: 9; anchors.verticalCenter: parent.verticalCenter; width: Theme.icon(12); height: width; name: "chevron-right" }
            ChatHitArea { id: hit; anchors.fill: parent; selectionController: root.selectionController; onClicked: backend.subagents.open(card.agent.id) }
            Accessible.role: Accessible.Button
            Accessible.name: (current.name || I18n.t("子代理")) + " · " + (current.task || agent.task || "")
        }
    }
}
