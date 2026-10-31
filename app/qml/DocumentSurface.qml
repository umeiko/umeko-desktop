import QtQuick
import QtQuick.Controls
import Umeko.Text 1.0

Item {
    id: root
    readonly property var state: backend.documentPreview.state
    property bool browserAllowed: false
    property bool browserReady: false
    readonly property string previewUrl: state.previewUrl || ""
    readonly property bool browserMode: state.fileType === "html" && state.mode === "rendered" && previewUrl.length > 0
    readonly property bool rich: state.mode !== "source" && !!state.html
    readonly property bool sourceMode: state.mode === "source" && ["markdown","html"].includes(state.fileType || "")
    onPreviewUrlChanged: browserReady = false
    function syncDocument() {
        // Set the format first. Updating two bindings independently can parse
        // Markdown source as HTML during a rich-to-source transition.
        editor.textFormat = root.rich ? TextEdit.RichText : TextEdit.PlainText
        editor.text = root.browserMode ? "" : root.rich ? root.state.html : root.state.text || ""
    }
    onStateChanged: Qt.callLater(root.syncDocument)
    onRichChanged: Qt.callLater(root.syncDocument)
    Component.onCompleted: syncDocument()
    Column {
        id: notices; x: 18; y: 10; width: parent.width - 36; spacing: 4
        Text { font.family: Theme.fontFamily; width: parent.width; visible: !!root.state.truncated && !root.browserMode; text: I18n.t("仅显示部分内容，打开可查看完整文件"); wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(10) }
        Text { font.family: Theme.fontFamily; width: parent.width; visible: !!root.state.simple && !root.sourceMode; text: I18n.t("文档较复杂，已使用纯文本预览"); wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(10) }
        Text { font.family: Theme.fontFamily; width: parent.width; visible: !!root.state.renderNote; text: I18n.t(root.state.renderNote || ""); wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(10) }
        Text { font.family: Theme.fontFamily; width: parent.width; visible: root.state.kind === "code" && !root.state.highlight; text: I18n.t("代码较大，已关闭语法高亮"); wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(10) }
    }
    ScrollView {
        id: scroll; objectName: "documentPreviewScroll"
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        anchors.top: notices.bottom; anchors.topMargin: 4
        visible: !root.browserMode && !root.state.busy && !root.state.error
        contentWidth: availableWidth
        TextArea {
            id: editor; objectName: "documentPreviewText"
            readonly property var syntaxColors: documentColors
            width: scroll.availableWidth
            readOnly: true; selectByMouse: true; persistentSelection: true
            textFormat: TextEdit.PlainText
            wrapMode: root.rich ? TextEdit.Wrap : TextEdit.WrapAnywhere
            color: Theme.ink; selectionColor: Theme.selectionBg; selectedTextColor: Theme.selectionText
            font.family: root.state.kind === "code" || root.sourceMode ? "monospace" : Qt.application.font.family
            font.pixelSize: Theme.font(root.state.kind === "code" ? 12 : 13)
            leftPadding: 18; rightPadding: 18; topPadding: 4; bottomPadding: 24
            background: null
            onLinkActivated: link => { if (/^https?:\/\//i.test(link)) Qt.openUrlExternally(link) }
            SyntaxHighlighter {
                id: documentColors
                objectName: "documentPreviewSyntax"
                document: editor.textDocument; language: root.state.language || ""; dark: Theme.dark
                enabled: !root.browserMode && !root.rich && !root.state.busy && (!!root.state.highlight || root.state.fileType === "markdown" && (root.state.text || "").length <= 24000 && !root.state.simple)
            }
        }
    }
    Timer { interval: 0; running: root.browserMode && root.browserAllowed && !root.browserReady; onTriggered: root.browserReady = true }
    Loader {
        id: browser; objectName: "htmlPreviewBrowser"
        anchors.fill: parent; anchors.margins: 8
        active: root.browserMode && root.browserReady
        visible: root.browserAllowed && (!item || !item.errorMessage)
        source: active ? "WebSurface.qml" : ""
        onLoaded: item.url = root.previewUrl
    }
    Text { font.family: Theme.fontFamily; anchors.centerIn: parent; width: parent.width-40; visible: root.browserMode && (browser.status === Loader.Error || !!browser.item && !!browser.item.errorMessage); text: I18n.t("网页加载失败") + "\n" + I18n.t("可以切换到源码查看文件"); color: Theme.muted; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter; font.pixelSize: Theme.font(12) }
    BusyIndicator { anchors.centerIn: parent; visible: !!root.state.busy; running: visible; width: 30; height: 30 }
    Text { font.family: Theme.fontFamily; anchors.centerIn: parent; width: parent.width - 40; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; visible: !!root.state.error; text: I18n.t(root.state.error || ""); color: Theme.muted; font.pixelSize: Theme.font(12) }
}
