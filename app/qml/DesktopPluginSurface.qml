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
        id: content; objectName: "desktopPluginPageLoader"; anchors.fill: parent
        asynchronous: true
        visible: !root.page.error
        Component.onCompleted: if (root.page.url) setSource(root.page.url,{sdk:bridge})
        Connections {target:root.manager;function onPageChanged() {
            if (!root.page.url) content.source=""
            else if (String(content.source)!==root.page.url) content.setSource(root.page.url,{sdk:bridge})
        }}
    }
    ColumnLayout {
        anchors.centerIn: parent; width: Math.max(0,parent.width-48); spacing:14
        visible: !!root.page.error || content.status===Loader.Error
        Text { font.family: Theme.fontFamily;text:root.page.error || I18n.t("插件页面加载失败，请检查 QML 文件");textFormat:Text.PlainText;color:Theme.muted;wrapMode:Text.Wrap;Layout.fillWidth:true;font.pixelSize: Theme.font(12, visible)}
        ActionButton {text:I18n.t("重试");onClicked:root.manager.openPage(root.page.id)}
    }
}
