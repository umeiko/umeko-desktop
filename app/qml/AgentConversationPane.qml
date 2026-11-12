import QtQuick
import QtQuick.Controls
import QtQuick.Window

Item {
    id: root
    property var controller: backend
    property string viewName: "agentConversation"
    property string messagePrefix: "widget"
    property string assistantName: ""
    property url portrait: ""
    property url replyPortrait: ""
    property int roleSlot: -1
    property bool active: visible
    property alias view: chat.view
    property alias selection: chat.selection
    ConversationPane {
        id: chat
        anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12
        controller: root.controller
        viewKey: root.controller ? root.controller.viewKey : ""
        viewName: root.viewName; messagePrefix: root.messagePrefix
        assistantName: root.assistantName; portrait: root.portrait; replyPortrait: root.replyPortrait
        roleSlot: root.roleSlot
        blocked: !root.active
        messageModel: root.controller.messageModel
        window: root.Window.window
        requestInspector: inspector
        highlightRow: -1
        Component.onCompleted: activate()

    }
    Connections { target: root.controller; function onViewChanged() { chat.selection.clear(); chat.view.restoreViewport() } }
    Column {
        anchors.centerIn: parent; width: parent.width - 40; spacing: 12
        visible: !!root.controller.loading || !!root.controller.error
        ActivitySpinner { anchors.horizontalCenter: parent.horizontalCenter; visible: !!root.controller.loading }
        Text { width: parent.width; text: root.controller.error || I18n.t("正在加载历史…"); wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible) }
    }
    QuestionNavigator {
        objectName: root.viewName + "Questions"
        anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom; z: 20
        view: chat.view; messageModel: root.controller.messageModel; enabled: root.active
    }
    ActionButton {
        objectName: root.viewName + "Latest"
        readonly property bool offered: chat.view.visible && !chat.view.followTail && !chat.view.restoring && chat.view.contentHeight - chat.view.height + chat.view.originY - chat.view.contentY > chat.view.height * 0.65
        anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 8; z: 30
        glyph: "arrow-down"; text: I18n.t("最新消息"); visible: offered; onClicked: chat.view.jumpToLatest()
    }
    Shortcut { sequences: [StandardKey.Copy]; enabled: chat.selection.activeFocus && chat.selection.hasSelection; onActivated: chat.selection.copy() }
    Shortcut { sequences: [StandardKey.SelectAll]; enabled: chat.selection.activeFocus; onActivated: chat.selection.selectAll() }
    QtObject { id: inspector; function show(id) { backend.showRequestDetails(id) } }
}
