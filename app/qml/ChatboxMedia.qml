import QtQuick
import QtQuick.Controls
import QtQuick.Window

Column {
    id: root
    property var items: []
    property string toolId: ""
    property var expansionState: ({details:({})})
    property var selectionController: null
    property int messageIndex: -1
    property int blockOffset: 0
    spacing: 10
    visible: items.length > 0
    function sizeLabel(bytes) { return bytes >= 1048576 ? (bytes / 1048576).toFixed(1) + " MB" : bytes >= 1024 ? (bytes / 1024).toFixed(1) + " KB" : bytes + " B" }
    Repeater {
        model: root.items.length
        Rectangle {
            id: card
            required property int index
            property var item: root.items[index] || ({})
            property string key: root.toolId + "_" + index
            readonly property bool inlineImage: item.kind === "image" && !!item.preview
            objectName: "chatboxCard_" + key
            width: inlineImage ? Math.min(root.width, 460, item.pixelWidth || 460) : Math.min(root.width, Math.min(400, Math.max(120, nameSize.advanceWidth + Theme.control(42))))
            height: content.implicitHeight
            radius: 7
            color: inlineImage ? "transparent" : headerArea.pressed || contextMenu.visible ? Theme.accentBg : headerArea.interactionHovered ? Theme.hover : Theme.surface
            border.color: inlineImage ? "transparent" : headerArea.interactionHovered || contextMenu.visible ? Qt.alpha(Theme.accent, 0.45) : Theme.line
            Behavior on color { ColorAnimation { duration: 110 } }
            TextMetrics { id: nameSize; font: filename.font; text: filename.text }
            function open() {
                if (inlineImage && root.Window.window) root.Window.window.previewChatImage(item, root.items)
                else backend.openChatboxPath(item.path, false)
            }
            Column {
                id: content; width: parent.width; spacing: 6
                Item {
                    width: parent.width; height: Theme.control(card.inlineImage ? 23 : 30)
                    Glyph { visible: !card.inlineImage; x: 9; width: Theme.icon(14); height: Theme.icon(14); anchors.verticalCenter: parent.verticalCenter; name: card.item.kind === "folder" ? "folder" : "file" }
                    Text {
                        id: filename; objectName: "chatboxLabel_" + card.key
                        x: card.inlineImage ? 0 : 16 + Theme.icon(14); width: parent.width - x - 8; anchors.verticalCenter: parent.verticalCenter
                        text: card.inlineImage ? [card.item.name || card.item.title, card.item.mime || "image/" + (card.item.name || "").split(".").pop().toLowerCase(), root.sizeLabel(card.item.bytes || 0)].join(" · ") : card.item.title || card.item.name || I18n.t("文件")
                        textFormat: Text.PlainText; elide: Text.ElideMiddle; color: card.inlineImage ? Theme.muted : Theme.ink; font.pixelSize: Theme.font(card.inlineImage ? 11 : 12)
                    }
                    ChatHitArea {
                        id: headerArea; objectName: "openChatbox_" + card.key
                        selectionController: root.selectionController
                        anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.RightButton
                        onClicked: mouse => { if (mouse.button === Qt.RightButton) contextMenu.popup(mouse.x, mouse.y); else card.open() }
                    }
                    HoverTip { objectName: "chatboxTip_" + card.key; active: headerArea.interactionHovered && !headerArea.pressed && !contextMenu.visible; heading: card.item.title || card.item.name || ""; text: [card.item.path, card.item.caption, card.item.previewNote].filter(value => !!value).join("\n") }
                    Accessible.role: Accessible.Button; Accessible.name: card.item.title || card.item.name || I18n.t("文件"); Accessible.description: card.item.path || ""
                }
                Item {
                    width: parent.width; visible: card.inlineImage
                    height: visible ? preview.status === Image.Error ? 30 : Math.min(300, width * (card.item.pixelHeight || 1) / (card.item.pixelWidth || 1)) : 0
                    Image {
                        id: preview; objectName: "chatboxImage_" + card.key; anchors.fill: parent
                        readonly property bool loaded: status === Image.Ready
                        source: parent.visible ? card.item.url : ""; asynchronous: true; cache: true; autoTransform: true
                        sourceSize: Qt.size(Math.min(1200, card.item.pixelWidth || 1200), Math.min(900, card.item.pixelHeight || 900)); fillMode: Image.PreserveAspectFit
                    }
                    BusyIndicator { anchors.centerIn: parent; running: preview.status === Image.Loading; visible: running; width: 26; height: 26 }
                    Text { anchors.centerIn: parent; visible: preview.status === Image.Error; text: I18n.t("图片暂不可预览，点击打开"); color: Theme.muted; font.pixelSize: Theme.font(11) }
                    ChatHitArea {
                        objectName: "previewChatbox_" + card.key; selectionController: root.selectionController
                        anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.RightButton
                        onClicked: mouse => { if (mouse.button === Qt.RightButton) { const p = mapToItem(card, mouse.x, mouse.y); contextMenu.popup(p.x, p.y) } else card.open() }
                    }
                }
                SelectableText {
                    visible: card.inlineImage && text.length > 0; width: parent.width; text: card.item.caption || ""; textFormat: TextEdit.PlainText; color: Theme.muted
                    font.pixelSize: Theme.font(11); wrapMode: TextEdit.Wrap
                    selectionController: root.selectionController; messageIndex: root.messageIndex; blockIndex: root.blockOffset + card.index * 3 + 1
                }
            }
            MediaContextMenu { id: contextMenu; objectName: "chatboxContext_" + card.key; item: card.item; itemKey: card.key; chatWindow: root.Window.window }
        }
    }
}
