import QtQuick

Item {
    id: root
    property string text: ""
    property var attachments: []
    property var selectionController: null
    property int messageIndex: -1
    implicitWidth: textMeasure.advanceWidth + attachmentMeasure.advanceWidth + attachments.length * 34 + Math.max(0, attachments.length - (text.length ? 0 : 1)) * 6 + 1
    implicitHeight: content.implicitHeight
    TextMetrics { id: textMeasure; font: prose.font; text: root.text.slice(0,512).split("\n").reduce((a,b) => a.length > b.length ? a : b, "") }
    TextMetrics { id: attachmentMeasure; font.pixelSize: Theme.font(12); text: root.attachments.map(item => item.name).join("") }
    Flow {
        id: content; width: root.width; spacing: 6
        SelectableText {
            id: prose; visible: root.text.length > 0
            width: Math.min(root.width, Math.max(1, Math.ceil(textMeasure.advanceWidth) + 1))
            text: root.text; color: Theme.ink; textFormat: TextEdit.PlainText
            font.pixelSize: Theme.font(13); wrapMode: TextEdit.Wrap; topPadding: 3; bottomPadding: 3
            selectionController: root.selectionController; messageIndex: root.messageIndex; blockIndex: 0
        }
        Repeater {
            model: root.attachments
            Rectangle {
                required property var modelData
                required property int index
                objectName: "userAttachment_" + root.messageIndex + "_" + index
                width: Math.min(root.width, Math.ceil(nameMeasure.advanceWidth) + 34)
                height: Math.max(26, filename.contentHeight + 8)
                radius: 5; color: Theme.accentBg; border.color: Theme.line
                TextMetrics { id: nameMeasure; font: filename.font; text: modelData.name }
                Glyph { x: 7; y: 6; width: 14; height: 14; name: modelData.kind === "folder" ? "folder" : modelData.kind === "image" ? "image" : "file" }
                SelectableText {
                    id: filename; objectName: "userAttachmentName_" + root.messageIndex + "_" + index
                    x: 25; y: 4; width: parent.width - 32
                    text: modelData.name; textFormat: TextEdit.PlainText; font.pixelSize: Theme.font(12)
                    color: Theme.ink; wrapMode: TextEdit.WrapAnywhere
                    selectionController: root.selectionController; messageIndex: root.messageIndex; blockIndex: 10000 + index
                    Accessible.description: modelData.path
                }
            }
        }
    }
}
