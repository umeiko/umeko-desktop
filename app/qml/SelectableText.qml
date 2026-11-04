import QtQuick
import Umeko.Text 1.0

TextEdit {
    id: root
    objectName: "selectText_" + messageIndex + "_" + blockIndex
    property var selectionController: null
    property int messageIndex: -1
    property int blockIndex: 0
    property bool conditionalSelection: false
    property bool conversationLinks: false
    function conversationLinkAt(x, y) { return conversationLinks ? linkAt(x, y) : "" }
    function activateConversationLink(href, button, x, y) {
        const info = links.linkInfo(href)
        if (!info.kind) return
        if (button === Qt.RightButton) {
            if (root.selectionController && root.selectionController.openLinkMenu)
                root.selectionController.openLinkMenu(root, info, x, y)
            else {
                linkMenuLoader.active = true
                linkMenuLoader.item.link = info
                linkMenuLoader.item.popup(x, y)
            }
        } else backend.openConversationUrl(info.target)
    }
    onLinkActivated: link => { if (conversationLinks && !selectionController) activateConversationLink(link, Qt.LeftButton, 0, 0) }
    TextLinks {
        id: links; objectName: "conversationLinks"
        document: root.textDocument; enabled: root.conversationLinks && (root.selectionController && root.selectionController.retainedView || root.visible)
        active: !root.conversationLinks || (!backend.busy && (!root.selectionController || root.selectionController.sessionActive))
        color: Theme.accent
    }
    MouseArea {
        anchors.fill: parent; enabled: root.conversationLinks && !root.selectionController
        acceptedButtons: Qt.RightButton
        onPressed: mouse => { if (!root.conversationLinkAt(mouse.x, mouse.y)) mouse.accepted = false }
        onClicked: mouse => root.activateConversationLink(root.conversationLinkAt(mouse.x, mouse.y), mouse.button, mouse.x, mouse.y)
    }
    Loader {
        id: linkMenuLoader; active: false
        sourceComponent: FloatingMenu {
        id: linkMenu; objectName: "conversationLinkMenu"
        property var link: ({})
        ContextAction { objectName: "copyConversationUrl"; visible: linkMenu.link.kind === "url"; text: I18n.t("复制网址"); glyph: "copy"; onTriggered: backend.copy(linkMenu.link.target) }
    }
    }
    readOnly: true
    font.family: Theme.fontFamily
    selectByMouse: !selectionController
    persistentSelection: true
    selectionColor: Theme.selectionBg
    selectedTextColor: Theme.selectionText
    Component.onCompleted: if (selectionController) selectionController.attach(root)
    Component.onDestruction: if (selectionController) selectionController.detach(root)
    onTextChanged: if (selectionController) selectionController.refreshSoon()
    onVisibleChanged: if (selectionController) selectionController.refreshSoon()
}
