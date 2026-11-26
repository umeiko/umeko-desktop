import QtQuick
import QtQuick.Controls
import QtQuick.Window

Column {
    id: root
    property var items: []
    property string toolId: ""
    property var expansionState: ({details:({})})
    property var selectionController: null
    readonly property bool sessionActive: !selectionController || selectionController.sessionActive
    readonly property int renderGeneration: selectionController ? selectionController.renderGeneration : 0
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
            readonly property bool sheet: backend.cowork.active && item.kind === "file" && /\.xlsx$/i.test(item.path || "")
            readonly property bool previewable: sheet || ["markdown", "code", "text"].includes(item.kind)
            readonly property bool inlineImage: item.kind === "image" && !!item.preview
            objectName: "chatboxCard_" + key
            width: inlineImage ? Math.min(root.width, 460, item.pixelWidth || 460) : Math.min(root.width, Math.min(400, Math.max(120, nameSize.advanceWidth + Theme.control(42) + (backend.cowork.active && previewable ? Theme.control(46) : 0))))
            height: content.implicitHeight
            radius: 7
            color: inlineImage ? "transparent" : headerArea.pressed || contextMenu.visible ? Theme.accentBg : headerArea.interactionHovered ? Theme.hover : Theme.surface
            border.color: inlineImage ? "transparent" : headerArea.interactionHovered || contextMenu.visible ? Qt.alpha(Theme.accent, 0.45) : Theme.line
            Behavior on color { ColorAnimation { duration: 110 } }
            TextMetrics { id: nameSize; font: filename.font; text: filename.text }
            function open() {
                if (item.kind === "web" && root.Window.window) root.Window.window.previewChatWeb(item)
                else if (previewable && root.Window.window) root.Window.window.previewChatDocument(sheet ? Object.assign({}, item, {kind:"xlsx"}) : item)
                else if (inlineImage && root.Window.window) root.Window.window.previewChatImage(item, root.items)
                else backend.openChatboxPath(item.path, false)
            }
            Column {
                id: content; width: parent.width; spacing: 6
                Item {
                    width: parent.width; height: Theme.control(card.inlineImage ? 23 : 30)
                    Glyph { visible: !card.inlineImage; x: 9; width: Theme.icon(14); height: Theme.icon(14); anchors.verticalCenter: parent.verticalCenter; name: card.item.kind === "web" ? "globe" : card.item.kind === "code" ? "code" : card.item.kind === "folder" ? "folder" : "file" }
                    Text { font.family: Theme.fontFamily;
                        id: filename; objectName: "chatboxLabel_" + card.key
                        x: card.inlineImage ? 0 : 16 + Theme.icon(14); width: parent.width - x - 8 - (previewTag.visible ? previewTag.width + 7 : 0); anchors.verticalCenter: parent.verticalCenter
                        text: card.inlineImage ? [card.item.name || card.item.title, card.item.mime || "image/" + (card.item.name || "").split(".").pop().toLowerCase(), root.sizeLabel(card.item.bytes || 0)].join(" · ") : card.item.title || card.item.name || I18n.t("文件")
                        textFormat: Text.PlainText; elide: Text.ElideMiddle; color: card.inlineImage ? Theme.muted : Theme.ink; font.pixelSize: Theme.font(card.inlineImage ? 11 : 12, visible, root.selectionController)
                    }
                    Text {
                        id: previewTag; visible: backend.cowork.active && card.previewable
                        text: backend.language === "en" ? "Preview" : "预览"; color: Theme.accent
                        anchors.right: parent.right; anchors.rightMargin: 9; anchors.verticalCenter: parent.verticalCenter
                        font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible)
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
                        readonly property string wantedSource: card.inlineImage ? String(card.item.url || "") : ""
                        readonly property bool requestActive: root.sessionActive
                        readonly property int currentGeneration: root.renderGeneration
                        property int requestGeneration: -1
                        property bool initialized: false
                        property var byteOwner: null
                        property double reportedBytes: 0
                        readonly property var accountingOwner: root.selectionController
                        // sourceSize is only the requested bound. With both item
                        // dimensions fixed, implicit size reflects the decoded
                        // pixmap; include it for providers that exceed the bound.
                        // DPR and RGBA give a conservative decoded-memory estimate.
                        readonly property size decodedSize: Qt.size(
                            Math.ceil(Math.max(0, sourceSize.width, implicitWidth * Math.max(1, Screen.devicePixelRatio))),
                            Math.ceil(Math.max(0, sourceSize.height, implicitHeight * Math.max(1, Screen.devicePixelRatio))))
                        readonly property double decodedBytes: loaded ? decodedSize.width * decodedSize.height * 4 : 0
                        function reportBytes() {
                            if (!initialized) return
                            if (byteOwner === accountingOwner) {
                                const delta = decodedBytes - reportedBytes
                                reportedBytes = decodedBytes
                                if (byteOwner && typeof byteOwner.adjustDecodedImageBytes === "function" && delta)
                                    byteOwner.adjustDecodedImageBytes(delta)
                                return
                            }
                            if (byteOwner && typeof byteOwner.adjustDecodedImageBytes === "function")
                                byteOwner.adjustDecodedImageBytes(-reportedBytes)
                            byteOwner = accountingOwner
                            reportedBytes = decodedBytes
                            if (byteOwner && typeof byteOwner.adjustDecodedImageBytes === "function")
                                byteOwner.adjustDecodedImageBytes(reportedBytes)
                        }
                        function syncSource() {
                            if (!initialized) return
                            const sameSource = source.toString() === wantedSource
                            // A completed image belongs to this retained item and
                            // can survive a switch; never retain an in-flight load.
                            if (sameSource && status === Image.Ready) {
                                requestGeneration = currentGeneration
                                return
                            }
                            if (!requestActive || !sameSource || requestGeneration !== currentGeneration)
                                source = "" // Qt disconnects/cancels the old pixmap request.
                            requestGeneration = currentGeneration
                            if (requestActive) source = wantedSource
                        }
                        onWantedSourceChanged: syncSource()
                        onRequestActiveChanged: syncSource()
                        onCurrentGenerationChanged: syncSource()
                        onStatusChanged: {
                            if (initialized && status === Image.Ready && (!requestActive || requestGeneration !== currentGeneration))
                                source = ""
                        }
                        onDecodedBytesChanged: reportBytes()
                        onAccountingOwnerChanged: reportBytes()
                        Component.onCompleted: { initialized = true; syncSource(); reportBytes() }
                        Component.onDestruction: {
                            if (byteOwner && typeof byteOwner.adjustDecodedImageBytes === "function")
                                byteOwner.adjustDecodedImageBytes(-reportedBytes)
                        }
                        asynchronous: true; cache: false; autoTransform: true
                        sourceSize: Qt.size(Math.min(1200, card.item.pixelWidth || 1200), Math.min(900, card.item.pixelHeight || 900)); fillMode: Image.PreserveAspectFit
                    }
                    BusyIndicator { anchors.centerIn: parent; running: preview.status === Image.Loading; visible: running; width: 26; height: 26 }
                    Text { font.family: Theme.fontFamily; anchors.centerIn: parent; visible: preview.status === Image.Error; text: I18n.t("图片暂不可预览，点击打开"); color: Theme.muted; font.pixelSize: Theme.font(11, visible, root.selectionController) }
                    ChatHitArea {
                        objectName: "previewChatbox_" + card.key; selectionController: root.selectionController
                        anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.RightButton
                        onClicked: mouse => { if (mouse.button === Qt.RightButton) { const p = mapToItem(card, mouse.x, mouse.y); contextMenu.popup(p.x, p.y) } else card.open() }
                    }
                }
                SelectableText {
                    visible: card.inlineImage && text.length > 0; width: parent.width; text: card.item.caption || ""; textFormat: TextEdit.PlainText; color: Theme.muted
                    font.pixelSize: Theme.font(11, visible, root.selectionController); wrapMode: TextEdit.Wrap
                    selectionController: root.selectionController; messageIndex: root.messageIndex; blockIndex: root.blockOffset + card.index * 3 + 1
                }
            }
            MediaContextMenu { id: contextMenu; objectName: "chatboxContext_" + card.key; item: card.item; itemKey: card.key; chatWindow: root.Window.window }
        }
    }
}
