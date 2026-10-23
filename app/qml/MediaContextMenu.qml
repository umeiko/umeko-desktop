import QtQuick

FloatingMenu {
    id: root
    property var item: ({})
    property string itemKey: ""
    property var chatWindow: null
    implicitWidth: Math.ceil(Math.max(attachAction.implicitWidth, copyAction.implicitWidth, pathAction.implicitWidth, revealAction.implicitWidth) + leftPadding + rightPadding)
    ContextAction { id: attachAction; objectName: "attachChatbox_" + root.itemKey; text: I18n.t("附加到聊天"); glyph: "plus"; onTriggered: if (root.chatWindow) root.chatWindow.attachChatFile(root.item.path) }
    ContextAction { id: copyAction; objectName: "copyChatboxFile_" + root.itemKey; text: I18n.t("复制"); glyph: "copy"; onTriggered: backend.copyChatboxFile(root.item.path) }
    ContextAction { id: pathAction; objectName: "copyChatbox_" + root.itemKey; text: I18n.t("复制路径"); glyph: "file"; onTriggered: backend.copy(root.item.path) }
    ContextAction { id: revealAction; objectName: "revealChatbox_" + root.itemKey; text: I18n.t("在文件管理器中打开"); glyph: "folder"; onTriggered: backend.openChatboxPath(root.item.path, true) }
}
