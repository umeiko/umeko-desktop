import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: root
    property var about: backend.appAbout
    objectName: "appInstallConfirmation"
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(480, parent.width - 48)
    modal: true; focus: true; padding: 24
    closePolicy: Popup.CloseOnEscape
    background: Rectangle { color: Theme.surface; radius: 13; border.color: Theme.line }
    Overlay.modal: Rectangle { color: "#66000000" }
    contentItem: ColumnLayout {
        spacing: 18
        Text { text: I18n.t("安装更新？"); color: Theme.ink; font.pixelSize: Theme.font(18); font.weight: Font.DemiBold }
        Text { Layout.fillWidth: true; text: I18n.t("将停止所有 Agent 并关闭 Umeko。工作记录与设置会保存，未完成任务需重新发起。"); textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.font(13) }
        RowLayout {
            Layout.alignment: Qt.AlignRight; spacing: 10
            ActionButton { objectName: "cancelAppInstallButton"; text: I18n.t("取消"); onClicked: root.close() }
            ActionButton { objectName: "confirmAppInstallButton"; text: I18n.t("停止并安装"); primary: true; onClicked: { root.close(); root.about.installUpdate() } }
        }
    }
}
