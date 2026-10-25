import QtQuick
import QtQuick.Controls
import Umeko.Text 1.0

Item {
    id: root
    readonly property var state: backend.documentPreview.state
    readonly property bool rich: !!state.html
    Column {
        id: notices; x: 18; y: 10; width: parent.width - 36; spacing: 4
        Text { width: parent.width; visible: !!root.state.truncated; text: I18n.t("仅显示部分内容，打开可查看完整文件"); wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(10) }
        Text { width: parent.width; visible: !!root.state.simple; text: I18n.t("文档较复杂，已使用纯文本预览"); wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(10) }
        Text { width: parent.width; visible: root.state.kind === "code" && !root.state.highlight; text: I18n.t("代码较大，已关闭语法高亮"); wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(10) }
    }
    ScrollView {
        id: scroll; objectName: "documentPreviewScroll"
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        anchors.top: notices.bottom; anchors.topMargin: 4
        visible: !root.state.busy && !root.state.error
        contentWidth: availableWidth
        TextArea {
            id: editor; objectName: "documentPreviewText"
            readonly property var syntaxColors: documentColors
            width: scroll.availableWidth
            readOnly: true; selectByMouse: true; persistentSelection: true
            text: root.state.html || root.state.text || ""
            textFormat: root.rich ? TextEdit.RichText : TextEdit.PlainText
            wrapMode: root.rich ? TextEdit.Wrap : TextEdit.WrapAnywhere
            color: Theme.ink; selectionColor: Theme.selectionBg; selectedTextColor: Theme.selectionText
            font.family: root.state.kind === "code" ? "monospace" : Qt.application.font.family
            font.pixelSize: Theme.font(root.state.kind === "code" ? 12 : 13)
            leftPadding: 18; rightPadding: 18; topPadding: 4; bottomPadding: 24
            background: null
            onLinkActivated: link => { if (/^https?:\/\//i.test(link)) Qt.openUrlExternally(link) }
            SyntaxHighlighter {
                id: documentColors
                objectName: "documentPreviewSyntax"
                document: editor.textDocument; language: root.state.language || ""; dark: Theme.dark
                enabled: !!root.state.highlight && !root.state.busy
            }
        }
    }
    BusyIndicator { anchors.centerIn: parent; visible: !!root.state.busy; running: visible; width: 30; height: 30 }
    Text { anchors.centerIn: parent; width: parent.width - 40; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; visible: !!root.state.error; text: I18n.t(root.state.error || ""); color: Theme.muted; font.pixelSize: Theme.font(12) }
}
