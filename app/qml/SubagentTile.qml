import QtQuick

Rectangle {
    id: root
    property var agent: ({})
    property bool showStatus: false
    property var selectionController: null
    signal activated()
    width: 300; height: Math.max(Theme.control(70), summary.implicitHeight + Theme.control(22))
    radius: 9; clip: true
    color: hit.pressed ? Theme.accentBg : hit.interactionHovered ? Theme.hover : Theme.surface
    border.color: hit.interactionHovered ? Qt.alpha(Theme.accent,0.5) : Theme.line
    SubagentAvatar { id: avatar; x: Theme.control(10); anchors.verticalCenter: parent.verticalCenter; width: Theme.icon(39); height: width; slot: root.agent.avatarSlot || 0 }
    Column {
        id: summary
        x: avatar.x+avatar.width+Theme.control(12); width: Math.max(0,parent.width-x-Theme.control(28))
        anchors.verticalCenter: parent.verticalCenter; spacing: 5
        Text { font.family: Theme.fontFamily;
            objectName: "subagentTitle_" + (root.agent.id || "")
            width: parent.width; text: (root.agent.name || I18n.t("子代理")) + (root.showStatus ? " · " + I18n.t(root.agent.status === "queued" ? "排队中" : "运行中") : "")
            textFormat: Text.PlainText; color: Theme.ink; font.pixelSize: Theme.font(12)
            maximumLineCount: 1; wrapMode: Text.NoWrap; elide: Text.ElideRight
        }
        Text { font.family: Theme.fontFamily;
            objectName: "subagentSummary_" + (root.agent.id || "")
            width: parent.width; text: String(root.showStatus ? root.agent.activity || root.agent.task || root.agent.type || "" : root.agent.task || root.agent.type || "").replace(/\s+/g," ")
            textFormat: Text.PlainText; color: Theme.muted; font.pixelSize: Theme.font(10)
            maximumLineCount: 1; wrapMode: Text.NoWrap; elide: Text.ElideRight
        }
    }
    Glyph { anchors.right: parent.right; anchors.rightMargin: Theme.control(9); anchors.verticalCenter: parent.verticalCenter; width: Theme.icon(12); height: width; name: "chevron-right" }
    ChatHitArea { id: hit; anchors.fill: parent; selectionController: root.selectionController; onClicked: root.activated() }
    Accessible.role: Accessible.Button
    Accessible.name: (agent.name || I18n.t("子代理")) + " · " + (agent.task || "")
}
