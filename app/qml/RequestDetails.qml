import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: root; objectName: "requestDetailsDialog"
    property string report: ""
    function show(identifier) { report = backend.requestReport(identifier); open() }
    parent: Overlay.overlay; anchors.centerIn: parent
    width: Math.min(1000, parent.width - 48); height: Math.min(730, parent.height - 48)
    modal: true; focus: true; padding: 22
    background: Rectangle { radius: 14; color: Theme.surface; border.color: Theme.line }
    contentItem: ColumnLayout {
        spacing: 14
        RowLayout {
            Layout.fillWidth: true
            Text { text: I18n.t("请求错误详情"); color: Theme.ink; font.pixelSize: Theme.font(17); font.weight: Font.DemiBold }
            Item { Layout.fillWidth: true }
            ActionButton { objectName: "copyRequestDetails"; text: I18n.t("复制完整详情"); glyph: "copy"; enabled: root.report.length > 0; onClicked: backend.copy(root.report) }
            ActionButton { text: I18n.t("关闭"); glyph: "x"; quiet: true; onClicked: root.close() }
        }
        Text { text: I18n.t("完整请求正文、HTTP 状态、响应与异常。密钥和登录凭据已隐藏，仅保存在本机。"); color: Theme.muted; font.pixelSize: Theme.font(11); wrapMode: Text.Wrap; Layout.fillWidth: true }
        ScrollView {
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
            TextArea { objectName: "requestDetailsText"; text: root.report || I18n.t("此请求的详情已过期或不可读取。"); readOnly: true; selectByMouse: true; textFormat: TextEdit.PlainText; wrapMode: TextEdit.NoWrap; color: Theme.ink; font.family: "monospace"; font.pixelSize: Theme.font(12); background: Rectangle { color: Theme.bg; radius: 8 } }
        }
    }
}
