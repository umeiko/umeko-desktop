import QtQuick

Flickable {
    id: root
    required property var items
    signal removeRequested(string id)
    implicitHeight: Theme.control(36)
    contentWidth: attachmentRow.width
    contentHeight: height
    clip: true

    Row {
        id: attachmentRow
        spacing: 7
        Repeater {
            model: root.items
            delegate: Rectangle {
                id: chip
                required property var modelData
                width: Math.min(attachmentName.implicitWidth, 165) + Theme.control(63)
                height: Theme.control(33)
                radius: 7
                color: Theme.accentBg
                Glyph {
                    x: 9
                    anchors.verticalCenter: parent.verticalCenter
                    name: chip.modelData.kind === "web" ? "globe" : chip.modelData.kind === "folder" ? "folder"
                        : chip.modelData.kind === "image" ? "image" : "file"
                    width: Theme.icon(15)
                    height: Theme.icon(15)
                }
                Text {
                    id: attachmentName
                    x: Theme.control(31)
                    anchors.verticalCenter: parent.verticalCenter
                    width: Math.min(implicitWidth, 165)
                    text: chip.modelData.name
                    textFormat: Text.PlainText
                    elide: Text.ElideMiddle
                    color: Theme.ink
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.font(10, visible)
                }
                ActionButton {
                    objectName: "removeComposerAttachment"
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    width: Theme.control(27)
                    height: Theme.control(27)
                    quiet: true
                    glyph: "x"
                    Accessible.name: I18n.language === "en" ? "Remove attachment" : "移除附件"
                    onClicked: root.removeRequested(chip.modelData.id)
                }
            }
        }
    }
}
