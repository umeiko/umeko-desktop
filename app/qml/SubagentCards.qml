import QtQuick
import QtQuick.Window

Column {
    id: root
    property var agents: []
    property var selectionController: null
    readonly property bool grouped: agents.length > 4
    spacing: 8
    function current(agent) { return backend.subagents.agents.find(row => row.id === agent.id) || agent }
    Rectangle {
        id: group; objectName: "subagentGroupCard"
        width: Math.min(root.width, Theme.control(340)); height: Theme.control(78); radius: 10
        visible: root.grouped; color: groupHit.interactionHovered ? Theme.hover : Theme.surface; border.color: Theme.line; clip: true
        Row {
            id: faces; x: Theme.control(12); anchors.verticalCenter: parent.verticalCenter; spacing: -Theme.icon(15)
            Repeater { model: root.grouped ? Math.min(3,root.agents.length) : 0
                SubagentAvatar { required property int index; width: Theme.icon(34); height: width; slot: root.current(root.agents[index]).avatarSlot || 0 }
            }
        }
        Column { x: faces.x+faces.width+Theme.control(12); width: Math.max(0,parent.width-x-Theme.control(28)); anchors.verticalCenter: parent.verticalCenter; spacing: 5
            Text { font.family: Theme.fontFamily; width: parent.width; text: I18n.t("%1 个子智能体").replace("%1",root.agents.length); font.pixelSize: Theme.font(12); color: Theme.ink; elide: Text.ElideRight }
            Text { font.family: Theme.fontFamily; width: parent.width; text: I18n.t("查看全部"); font.pixelSize: Theme.font(10); color: Theme.muted; elide: Text.ElideRight }
        }
        Glyph { anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter; name: "grid"; width: Theme.icon(16); height: width }
        ChatHitArea { id: groupHit; anchors.fill: parent; selectionController: root.selectionController
            onClicked: if (root.Window.window) root.Window.window.showSubagentGroup(root.agents,group)
        }
    }
    Repeater {
        model: root.grouped ? 0 : root.agents.length
        SubagentTile {
            required property int index
            property var original: root.agents[index] || ({})
            objectName: "subagentCard_" + original.id
            width: Math.min(root.width, Theme.control(300)); agent: root.current(original)
            selectionController: root.selectionController
            onActivated: backend.subagents.open(original.id)
        }
    }
}
