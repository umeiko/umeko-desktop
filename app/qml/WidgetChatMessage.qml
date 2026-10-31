import QtQuick

// Widgets use the same prose, code, thinking and tool components as Main.qml.
Column {
    id: root
    objectName: "widgetChatMessage_" + messageIndex
    property var message: ({})
    property int messageIndex: -1
    property string assistantName: ""
    property url portrait: ""
    property url replyPortrait: ""
    property bool busy: false
    property bool last: false
    readonly property bool user: message.role === "user"
    spacing: 10
    Row {
        visible: !root.user; spacing: 9; width: root.width
        CharacterArt {
            objectName: "widgetAssistantAvatar_" + root.messageIndex
            artwork: root.portrait; fallbackSource: "../icons/avatars/smile.webp"
            width: Theme.icon(40); height: width; sourceSize: Qt.size(96,96)
            fillMode: Image.PreserveAspectFit; smooth: false
        }
        Text { font.family: Theme.fontFamily;
            anchors.verticalCenter: parent.verticalCenter
            width: Math.max(0,root.width-Theme.icon(40)-9);elide: Text.ElideRight
            text: root.message.role === "custom" ? I18n.t("智能体总线") : root.assistantName
            textFormat: Text.PlainText; color: Theme.ink
            font.pixelSize: Theme.font(11, visible); font.weight: Font.DemiBold
        }
    }
    Rectangle {
        readonly property string prose: root.message.text || ""
        width: root.user ? (prose.length>512 ? root.width*0.82 : Math.min(root.width*0.82,Math.max(64,userBody.implicitWidth+28))) : root.width-33
        x: root.user ? root.width-width : 33
        height: body.implicitHeight + (root.user ? 22 : root.message.error ? 28 : 4)
        radius: root.user ? 13 : 8
        color: root.user ? Theme.userBubble : root.message.error ? Theme.accentBg : "transparent"
        Column {
            id: body; x: root.user || root.message.error ? 14 : 0
            y: root.user ? 11 : root.message.error ? 14 : 0
            width: parent.width-x*2; spacing: 10
            ActivityHistory { width: parent.width; activity: root.user ? [] : root.message.activity || []; messageIndex: root.messageIndex }
            UserMessageBody { id: userBody; width: parent.width; visible: root.user; text: root.user ? root.message.text || "" : ""; attachments: root.message.attachments || []; messageIndex: root.messageIndex }
            MessageBody {
                width: parent.width; messageIndex: root.messageIndex
                text: !root.user && !(root.message.activity || []).length ? root.message.text || "" : ""
                visible: text.length>0; markdown: root.message.role === "assistant" && !root.message.error
                textColor: root.message.error ? Theme.danger : Theme.ink
            }
            ActivitySpinner { visible: !root.user && root.last && root.busy && !(root.message.activity || []).length && !(root.message.text || "").length; width: Theme.icon(14); height: width }
        }
    }
    ActionButton {
        objectName: "widgetCopyMessage_" + root.messageIndex
        x: root.user ? root.width-width : 33
        glyph: "copy"; quiet: true; width: Theme.control(22); height: Theme.control(22)
        hint: I18n.t("复制消息")
        visible: !!(root.message.text || "") || (root.message.activity || []).some(step=>step.kind==="text")
        onClicked: {
            const prose=(root.message.activity || []).filter(step=>step.kind==="text").map(step=>step.text).join("\n\n")
            backend.copy(prose || root.message.text || "")
        }
    }
    ReplyMascot {
        objectName: "widgetReplyMascot_" + root.messageIndex
        x: 33; portraitSource: root.replyPortrait || root.portrait; interactionLabel: root.assistantName
        tapLines: []; celebrationLine: ""
        visible: root.last && !root.busy && root.message.role === "assistant" && !root.message.error && !!(root.message.text || "").trim()
    }
}
