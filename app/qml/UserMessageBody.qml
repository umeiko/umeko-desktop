import QtQuick
import QtQuick.Window
import Umeko.Text 1.0

Item {
    id: root
    property string text: ""
    property var attachments: []
    property var selectionController: null
    property int messageIndex: -1
    implicitWidth: Math.ceil(textMeasure.advanceWidth) + attachmentMeasure.implicitWidth + Math.max(0, attachments.length - (text.length ? 0 : 1)) * 6 + 1
    implicitHeight: content.implicitHeight
    TextMetrics { id: textMeasure; font: prose.font; text: root.text.slice(0,512).split("\n").reduce((a,b) => a.length > b.length ? a : b, "") }
    Row {
        id: attachmentMeasure; visible: false
        Repeater {
            model: root.attachments
            Item {
                required property var modelData
                width: Math.ceil(measure.advanceWidth) + Theme.control(34); height: 1
                TextMetrics { id: measure; font.pixelSize: Theme.font(12); text: modelData.name }
            }
        }
    }
    Flow {
        id: content; width: root.width; spacing: 6
        SelectableText {
            id: prose; visible: root.text.length > 0
            width: Math.min(root.width, Math.max(1, Math.ceil(textMeasure.advanceWidth) + 1))
            text: root.text; color: Theme.ink; textFormat: TextEdit.PlainText
            font.pixelSize: Theme.font(13); wrapMode: TextEdit.Wrap; topPadding: 3; bottomPadding: 3
            TextSpacing { document: prose.textDocument; factor: Theme.proseLineHeight }
            selectionController: root.selectionController; messageIndex: root.messageIndex; blockIndex: 0
        }
        Repeater {
            model: root.attachments
            Rectangle {
                id: attachment
                required property var modelData
                required property int index
                objectName: "userAttachment_" + root.messageIndex + "_" + index
                width: Math.min(root.width, Math.ceil(nameMeasure.advanceWidth) + Theme.control(34))
                height: Math.max(26, filename.contentHeight + 8)
                radius: 5; color: attachmentHit.interactionHovered ? Theme.hover : Theme.accentBg; border.color: Theme.line
                TextMetrics { id: nameMeasure; font: filename.font; text: modelData.name }
                Glyph { x: 7; anchors.verticalCenter: parent.verticalCenter; width: Theme.icon(14); height: Theme.icon(14); name: modelData.kind === "web" ? "globe" : modelData.kind === "folder" ? "folder" : modelData.kind === "image" ? "image" : "file" }
                SelectableText {
                    id: filename; objectName: "userAttachmentName_" + root.messageIndex + "_" + index
                    x: 11 + Theme.icon(14); y: 4; width: parent.width - x - 7
                    text: modelData.name; textFormat: TextEdit.PlainText; font.pixelSize: Theme.font(12)
                    color: Theme.ink; wrapMode: TextEdit.WrapAnywhere
                    selectionController: root.selectionController; messageIndex: root.messageIndex; blockIndex: 10000 + index
                    Accessible.description: modelData.path
                }
                ChatHitArea {
                    id: attachmentHit; objectName: "openUserAttachment_" + root.messageIndex + "_" + attachment.index
                    anchors.fill: parent; selectionController: root.selectionController; acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onClicked: mouse => { if (mouse.button === Qt.RightButton) fileMenu.popup(mouse.x, mouse.y); else if (root.Window.window) root.Window.window.previewChatImage(attachment.modelData) }
                }
                MediaContextMenu { id: fileMenu; item: attachment.modelData; itemKey: "user_" + root.messageIndex + "_" + attachment.index; chatWindow: root.Window.window }
            }
        }
    }
}
