import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
FocusScope {
    id: root
    objectName: "desktopPluginSurface"
    clip: true
    property var manager: backend.desktopPlugins
    property bool live: true
    readonly property var page: manager.page
    QtObject {
        id: bridge
        readonly property var session: root.manager.session
        readonly property var config: root.page.config || ({})
        readonly property var colors: ({bg:Theme.bg,surface:Theme.surface,ink:Theme.ink,muted:Theme.muted,line:Theme.line,hover:Theme.hover,accent:Theme.accent,accentBg:Theme.accentBg,danger:Theme.danger,dark:Theme.dark})
        readonly property real scale: Theme.fontScale
        readonly property string language: I18n.language
        readonly property string revealPath: root.page.selection || ""
        readonly property bool active: root.live
        readonly property var hostCapabilities: root.manager.hostServices.capabilities
        readonly property Component chatMessageComponent: chatMessageRenderer
        readonly property Component queuedMessagesComponent: queueRenderer
        signal response(string request, var value)
        signal hostResponse(string request, var value)
        signal event(string topic, var data)
        function call(method,args) { return root.manager.call(method,JSON.stringify(args || {})) }
        function requestHost(operation,args) { return root.manager.requestHost(operation,JSON.stringify(args || {})) }
        function copyText(text) { backend.copy(text) }
    }
    Component { id: chatMessageRenderer; WidgetChatMessage {} }
    Component { id: queueRenderer; QueuedMessages {} }
    Connections {target:root.manager;function onResponse(request,value) {bridge.response(request,value)}function onEvent(topic,data){bridge.event(topic,data)}}
    Connections {target:root.manager;function onHostResponse(widget,request,value) {if (widget===root.page.id) bridge.hostResponse(request,value)}}
    Loader {
        id: content; objectName: "desktopPluginPageLoader"
        anchors { left: parent.left; right: parent.right; top: parent.top; bottom: panelConfirmation.visible ? panelConfirmation.top : parent.bottom }
        asynchronous: true
        enabled: !panelConfirmation.visible
        visible: !root.page.error
        Component.onCompleted: if (root.page.url) setSource(root.page.url,{sdk:bridge})
        Connections {target:root.manager;function onPageChanged() {
            if (!root.page.url) content.source=""
            else if (String(content.source)!==root.page.url) content.setSource(root.page.url,{sdk:bridge})
        }}
    }
    Rectangle {
        id: panelConfirmation; objectName: "widgetPanelConfirmation"
        readonly property var approval: root.manager.hostServices.panelApproval
        visible: approval.widget === root.page.id && approval.id !== undefined
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: Math.min(parent.height, confirmationLayout.implicitHeight + 32)
        color: Theme.surface; border.color: Theme.line
        function tr(zh, en) { return I18n.language === "en" ? en : zh }
        function actionText() {
            switch (approval.operation) {
            case "skills.attach": return approval.enabled ? tr("附带到当前聊天", "Attach to this chat") : tr("从当前聊天移除", "Detach from this chat")
            case "skills.default": return approval.enabled ? tr("设为全局默认启用", "Enable global default") : tr("设为全局默认停用", "Disable global default")
            case "skills.reveal": return tr("打开所在文件夹", "Open containing folder")
            case "skills.remove": return tr("卸载整个技能包", "Uninstall the whole skill package")
            case "pi.install": return tr("安装 Pi 技能包", "Install Pi skill package")
            case "skills.import": return tr("导入本地技能", "Import local skills") + (approval.project ? tr(" · 当前项目", " · Current project") : tr(" · 全局", " · Global"))
            default: return tr("确认操作", "Confirm operation")
            }
        }
        ColumnLayout {
            id: confirmationLayout
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 16 }
            spacing: 10
            RowLayout {
                Glyph { name: "lock"; width: Theme.icon(16); height: Theme.icon(16) }
                Text { font.family: Theme.fontFamily; text: panelConfirmation.tr("由 Umeko 确认", "Confirm with Umeko"); color: Theme.ink; font.pixelSize: Theme.font(13); font.bold: true }
            }
            Text { font.family: Theme.fontFamily; text: panelConfirmation.actionText(); color: Theme.ink; font.pixelSize: Theme.font(12); wrapMode: Text.Wrap; Layout.fillWidth: true }
            Text { font.family: Theme.fontFamily; text: panelConfirmation.approval.name || ""; textFormat: Text.PlainText; color: Theme.muted; font.pixelSize: Theme.font(11); elide: Text.ElideMiddle; Layout.fillWidth: true }
            Text {
                font.family: Theme.fontFamily
                text: panelConfirmation.approval.operation === "skills.attach" ? panelConfirmation.tr("只改变此聊天可用的技能；已读取的内容不会被清除。", "Changes skills available to this chat. Content already read stays in its history.") : panelConfirmation.approval.operation === "skills.remove" ? panelConfirmation.tr("包内的其他技能和扩展也会一并卸载。", "Other skills and extensions in this package will also be removed.") : panelConfirmation.tr("此操作由宿主执行。", "Umeko will perform this operation.")
                color: Theme.muted; font.pixelSize: Theme.font(11); wrapMode: Text.Wrap; Layout.fillWidth: true
            }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                ActionButton { objectName: "widgetPanelDeny"; text: panelConfirmation.tr("取消", "Cancel"); onClicked: root.manager.hostServices.respondApproval(false) }
                ActionButton { objectName: "widgetPanelAllow"; text: panelConfirmation.tr("确认", "Confirm"); primary: true; onClicked: root.manager.hostServices.respondApproval(true) }
            }
        }
    }
    ColumnLayout {
        anchors.centerIn: parent; width: Math.max(0,parent.width-48); spacing:14
        visible: !!root.page.error || content.status===Loader.Error
        Text { font.family: Theme.fontFamily;text:root.page.error || I18n.t("插件页面加载失败，请检查 QML 文件");textFormat:Text.PlainText;color:Theme.muted;wrapMode:Text.Wrap;Layout.fillWidth:true;font.pixelSize: Theme.font(12, visible)}
        ActionButton {text:I18n.t("重试");onClicked:root.manager.openPage(root.page.id)}
    }
}
