import QtQuick

FloatingMenu {
    id: root
    property var item: ({})
    property string itemKey: ""
    property var chatWindow: null
    readonly property bool web: item.kind === "web"
    readonly property string url: item.url || item.path || ""
    implicitWidth: Math.ceil((web ? Math.max(openWebAction.implicitWidth, copyUrlAction.implicitWidth, attachWebAction.implicitWidth) : Math.max(attachAction.implicitWidth, copyAction.implicitWidth, pathAction.implicitWidth, revealAction.implicitWidth)) + leftPadding + rightPadding)
    ContextAction { id: openWebAction; visible: root.web; objectName: "openChatboxWeb_" + root.itemKey; text: I18n.t("打开"); glyph: "external-link"; onTriggered: Qt.openUrlExternally(root.url) }
    ContextAction { id: copyUrlAction; visible: root.web; objectName: "copyChatboxUrl_" + root.itemKey; text: I18n.t("复制网址"); glyph: "copy"; onTriggered: backend.copy(root.url) }
    ContextAction { id: attachWebAction; visible: root.web; objectName: "attachChatboxWeb_" + root.itemKey; text: I18n.t("附加到聊天"); glyph: "plus"; onTriggered: if (root.chatWindow) root.chatWindow.attachChatUrl(root.url) }
    ContextAction { id: attachAction; visible: !root.web; objectName: "attachChatbox_" + root.itemKey; text: I18n.t("附加到聊天"); glyph: "plus"; onTriggered: if (root.chatWindow) root.chatWindow.attachChatFile(root.item.path) }
    ContextAction { id: copyAction; visible: !root.web; objectName: "copyChatboxFile_" + root.itemKey; text: I18n.t("复制"); glyph: "copy"; onTriggered: backend.copyChatboxFile(root.item.path) }
    ContextAction { id: pathAction; visible: !root.web; objectName: "copyChatbox_" + root.itemKey; text: I18n.t("复制路径"); glyph: "file"; onTriggered: backend.copy(root.item.path) }
    ContextAction { id: revealAction; visible: !root.web; objectName: "revealChatbox_" + root.itemKey; text: I18n.t("在文件管理器中打开"); glyph: "folder"; onTriggered: backend.openChatboxPath(root.item.path, true) }
}
