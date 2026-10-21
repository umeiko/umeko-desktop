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
            radius: 7; color: inlineImage ? "transparent" : headerArea.containsMouse ? Theme.accentBg : Theme.surface
            border.color: inlineImage ? "transparent" : Theme.line
            TextMetrics { id: nameSize; font: filename.font; text: filename.text }
            Column {
                id: content; width: parent.width; spacing: 6
                Item {
                    id: header; width: parent.width; height: card.inlineImage ? 28 : 34
                    Glyph { x: 10; width: 14; height: 14; anchors.verticalCenter: parent.verticalCenter; name: card.item.kind === "folder" ? "folder" : card.item.kind === "image" ? "image" : "file" }
                    Text { id: filename; x: 32; width: parent.width - 58; anchors.verticalCenter: parent.verticalCenter; text: card.item.title || card.item.name || "文件"; textFormat: Text.PlainText; elide: Text.ElideMiddle; color: Theme.ink; font.pixelSize: 12 }
                    MouseArea {
                        id: headerArea; objectName: "openChatbox_" + card.key
                        anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.RightButton; cursorShape: Qt.PointingHandCursor
                        onClicked: mouse => { if (mouse.button === Qt.RightButton) contextMenu.popup(mouse.x, mouse.y); else backend.openChatboxPath(card.item.path, false) }
                    }
                    Item {
                        x: parent.width - 24; width: 22; height: parent.height
                        Glyph { anchors.centerIn: parent; name: "chevron-down"; width: 11; height: 11 }
                        MouseArea { id: arrowArea; objectName: "toggleChatbox_" + card.key; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: openMenu.popup(card.width - openMenu.width, header.height) }
                        Accessible.role: Accessible.Button; Accessible.name: "在文件管理器中打开"
                    }
                    ToolTip.visible: headerArea.containsMouse && !contextMenu.visible && !openMenu.visible
                    ToolTip.delay: 500
                    ToolTip.text: [card.item.path, card.item.caption, card.item.previewNote].filter(value => !!value).join("\n")
                    Accessible.role: Accessible.Button; Accessible.name: card.item.title || card.item.name || "文件"; Accessible.description: card.item.path || ""
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
                    Text { anchors.centerIn: parent; visible: preview.status === Image.Error; text: "图片暂不可预览，点击打开"; color: Theme.muted; font.pixelSize: 11 }
                    MouseArea {
                        anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.RightButton; cursorShape: Qt.PointingHandCursor
                        onClicked: mouse => { if (mouse.button === Qt.RightButton) { const p = mapToItem(card, mouse.x, mouse.y); contextMenu.popup(p.x, p.y) } else backend.openChatboxPath(card.item.path, false) }
                    }
                }
                SelectableText {
                    visible: card.inlineImage && text.length > 0; width: parent.width; text: card.item.caption || ""; textFormat: TextEdit.PlainText; color: Theme.ink
                    font.pixelSize: 12; wrapMode: TextEdit.Wrap
                    selectionController: root.selectionController; messageIndex: root.messageIndex; blockIndex: root.blockOffset + card.index * 3 + 1
                }
            }
            Menu {
                id: openMenu
                MenuItem { objectName: "revealChatbox_" + card.key; text: "在文件管理器中打开"; onTriggered: backend.openChatboxPath(card.item.path, true) }
            }
            Menu {
                id: contextMenu
                MenuItem { objectName: "copyChatboxFile_" + card.key; text: "复制"; onTriggered: backend.copyChatboxFile(card.item.path) }
                MenuItem { objectName: "copyChatbox_" + card.key; text: "复制路径"; onTriggered: backend.copy(card.item.path) }
                MenuItem { text: "在文件管理器中打开"; onTriggered: backend.openChatboxPath(card.item.path, true) }
            }
        }
    }
}
