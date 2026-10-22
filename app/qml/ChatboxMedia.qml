import QtQuick
import QtQuick.Controls

Column {
    id: root
    property var items: []
    property string toolId: ""
    property var expansionState: ({details:({})})
    property var selectionController: null
    property int messageIndex: -1
    property int blockOffset: 0
    spacing: 8
    visible: items.length > 0
    Repeater {
        model: root.items.length
        Rectangle {
            id: card
            required property int index
            property var item: root.items[index] || ({})
            property string key: root.toolId + "_" + index
            readonly property bool inlineImage: item.kind === "image" && !!item.preview
            objectName: "chatboxCard_" + key
            width: inlineImage ? Math.min(root.width, 640) : Math.min(root.width, Math.min(420, Math.max(150, nameSize.advanceWidth + 66)))
            height: content.implicitHeight
            readonly property bool hovered: headerArea.interactionHovered || arrowArea.interactionHovered
            radius: 7; color: inlineImage ? "transparent" : headerArea.pressed || openMenu.visible ? Theme.accentBg : hovered ? Theme.hover : Theme.surface
            border.color: inlineImage ? "transparent" : hovered || openMenu.visible ? Qt.alpha(Theme.accent, 0.45) : Theme.line
            Behavior on color { ColorAnimation { duration: 110 } }
            Behavior on border.color { ColorAnimation { duration: 110 } }
            TextMetrics { id: nameSize; font: filename.font; text: filename.text }
            Column {
                id: content; width: parent.width; spacing: 6
                Item {
                    id: header; width: parent.width; height: card.inlineImage ? 28 : 34
                    Glyph { x: 10; width: 14; height: 14; anchors.verticalCenter: parent.verticalCenter; name: card.item.kind === "folder" ? "folder" : card.item.kind === "image" ? "image" : "file" }
                    Text { id: filename; x: 32; width: parent.width - 58; anchors.verticalCenter: parent.verticalCenter; text: card.item.title || card.item.name || I18n.t("文件"); textFormat: Text.PlainText; elide: Text.ElideMiddle; color: Theme.ink; font.pixelSize: Theme.font(12) }
                    ChatHitArea {
                        id: headerArea; objectName: "openChatbox_" + card.key
                        selectionController: root.selectionController
                        anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.RightButton; cursorShape: Qt.PointingHandCursor
                        onClicked: mouse => { if (mouse.button === Qt.RightButton) contextMenu.popup(mouse.x, mouse.y); else backend.openChatboxPath(card.item.path, false) }
                    }
                    Rectangle {
                        id: arrowButton; objectName: "chatboxArrow_" + card.key
                        x: parent.width - width - 3; width: 26; height: parent.height - 6; anchors.verticalCenter: parent.verticalCenter
                        radius: 5; color: arrowArea.pressed || openMenu.visible ? Theme.accentBg : arrowArea.interactionHovered ? Qt.alpha(Theme.accent, 0.16) : "transparent"
                        border.color: openMenu.visible ? Qt.alpha(Theme.accent, 0.5) : "transparent"
                        Behavior on color { ColorAnimation { duration: 100 } }
                        Glyph { anchors.centerIn: parent; name: "chevron-down"; width: 12; height: 12; rotation: openMenu.visible ? 180 : 0; Behavior on rotation { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } } }
                        ChatHitArea { id: arrowArea; objectName: "toggleChatbox_" + card.key; anchors.fill: parent; selectionController: root.selectionController; interactionPriority: 10; onClicked: { if (openMenu.visible) openMenu.close(); else openMenu.popup(arrowButton.width - openMenu.width, arrowButton.height + 5) } }
                        HoverTip { active: arrowArea.interactionHovered && !openMenu.visible; text: I18n.t("文件操作") }
                        Accessible.role: Accessible.Button; Accessible.name: I18n.t("文件操作"); Accessible.description: openMenu.visible ? I18n.t("已展开") : I18n.t("已收起")
                    }
                    HoverTip {
                        objectName: "chatboxTip_" + card.key
                        active: headerArea.interactionHovered && !arrowArea.interactionHovered && !headerArea.pressed && !contextMenu.visible && !openMenu.visible
                        heading: filename.text
                        text: [card.item.path, card.item.caption, card.item.previewNote].filter(value => !!value).join("\n")
                    }
                    Accessible.role: Accessible.Button; Accessible.name: card.item.title || card.item.name || I18n.t("文件"); Accessible.description: card.item.path || ""
                }
                Item {
                    width: parent.width; visible: card.inlineImage
                    height: visible ? preview.status === Image.Error ? 30 : Math.min(360, Math.max(100, width * (card.item.pixelHeight || 1) / (card.item.pixelWidth || 1))) : 0
                    Image {
                        id: preview; objectName: "chatboxImage_" + card.key; anchors.fill: parent
                        readonly property bool loaded: status === Image.Ready
                        source: parent.visible ? card.item.url : ""; asynchronous: true; cache: true; autoTransform: true
                        sourceSize: Qt.size(Math.min(1600, card.item.pixelWidth || 1600), Math.min(1000, card.item.pixelHeight || 1000)); fillMode: Image.PreserveAspectFit
                    }
                    BusyIndicator { anchors.centerIn: parent; running: preview.status === Image.Loading; visible: running; width: 26; height: 26 }
                    Text { anchors.centerIn: parent; visible: preview.status === Image.Error; text: I18n.t("图片暂不可预览，点击打开"); color: Theme.muted; font.pixelSize: Theme.font(11) }
                    ChatHitArea {
                        selectionController: root.selectionController
                        anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.RightButton; cursorShape: Qt.PointingHandCursor
                        onClicked: mouse => { if (mouse.button === Qt.RightButton) { const p = mapToItem(card, mouse.x, mouse.y); contextMenu.popup(p.x, p.y) } else backend.openChatboxPath(card.item.path, false) }
                    }
                }
                SelectableText {
                    visible: card.inlineImage && text.length > 0; width: parent.width; text: card.item.caption || ""; textFormat: TextEdit.PlainText; color: Theme.ink
                    font.pixelSize: Theme.font(12); wrapMode: TextEdit.Wrap
                    selectionController: root.selectionController; messageIndex: root.messageIndex; blockIndex: root.blockOffset + card.index * 3 + 1
                }
            }
            FloatingMenu {
                id: openMenu; objectName: "chatboxOpen_" + card.key
                parent: arrowButton
                closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
                ContextAction { objectName: "revealChatbox_" + card.key; text: I18n.t("在文件管理器中打开"); onTriggered: backend.openChatboxPath(card.item.path, true) }
            }
            FloatingMenu {
                id: contextMenu; objectName: "chatboxContext_" + card.key
                ContextAction { objectName: "copyChatboxFile_" + card.key; text: I18n.t("复制"); onTriggered: backend.copyChatboxFile(card.item.path) }
                ContextAction { objectName: "copyChatbox_" + card.key; text: I18n.t("复制路径"); onTriggered: backend.copy(card.item.path) }
                ContextAction { text: I18n.t("在文件管理器中打开"); onTriggered: backend.openChatboxPath(card.item.path, true) }
            }
        }
    }
}
