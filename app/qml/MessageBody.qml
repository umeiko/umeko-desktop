import QtQuick
import QtQuick.Controls
import Umeko.Text 1.0
import "markdown.js" as Markdown

Column {
    id: root
    property string text: ""
    property bool markdown: true
    property color textColor: Theme.ink
    property var selectionController: null
    property int messageIndex: -1
    property int blockOffset: 0
    property bool compact: false
    readonly property var blocks: root.text.length ? Markdown.blocks(root.text, root.markdown, root.compact) : []
    spacing: compact ? 6 : 12
    Repeater {
        model: root.blocks.length
        Column {
            required property int index
            property var modelData: root.blocks[index] || ({code:false, text:"", language:""})
            width: root.width
            SelectableText {
                id: proseText
                selectionController: root.selectionController; messageIndex: root.messageIndex; blockIndex: root.blockOffset + index
                visible: !modelData.code; width: parent.width
                text: modelData.code ? "" : root.markdown ? Markdown.forQt(modelData.text) : modelData.text; color: root.textColor
                wrapMode: TextEdit.Wrap; textFormat: root.markdown ? TextEdit.MarkdownText : TextEdit.PlainText
                font.pixelSize: Theme.font(13, visible)
                TextSpacing { document: proseText.textDocument; factor: Theme.proseLineHeight }
            }
            Rectangle {
                visible: modelData.code; width: parent.width; height: codeText.contentHeight + 60
                radius: 9; color: Theme.dark ? "#171c19" : "#f3f5f0"; border.color: Theme.line
                Text { x: 14; y: 12; text: modelData.language || I18n.t("代码"); font.pixelSize: Theme.font(10, visible); color: Theme.muted; font.family: "Consolas" }
                ActionButton {
                    id: copyButton; objectName: "copyCode_" + index
                    selectionController: root.selectionController
                    property bool copied: false
                    anchors.right: parent.right; anchors.rightMargin: 6; y: 4; height: Theme.control(28)
                    text: copied ? I18n.t("已复制") : I18n.t("复制"); glyph: copied ? "check" : "copy"; quiet: true
                    onClicked: { backend.copy(modelData.text); copied = true; resetCopy.restart() }
                    Timer { id: resetCopy; interval: 1600; onTriggered: copyButton.copied = false }
                }
                SelectableText {
                    selectionController: root.selectionController; messageIndex: root.messageIndex; blockIndex: root.blockOffset + index
                    id: codeText; objectName: "codeBlock_" + index
                    readonly property var syntaxColors: codeColors
                    x: 14; y: 42; width: parent.width - 28
                    text: modelData.code ? modelData.text : ""; color: Theme.ink
                    wrapMode: TextEdit.WrapAnywhere; textFormat: TextEdit.PlainText
                    font.family: "Consolas"; font.pixelSize: Theme.font(12, visible)
                    SyntaxHighlighter {
                        id: codeColors
                        objectName: "syntax_" + root.messageIndex + "_" + (root.blockOffset + index)
                        document: codeText.textDocument; language: modelData.language || ""; dark: Theme.dark; enabled: codeText.visible
                    }
                }
            }
        }
    }
}
