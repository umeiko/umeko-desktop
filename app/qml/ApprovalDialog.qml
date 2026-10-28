import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "PackageText.js" as PackageText

Popup {
    id: root
    objectName: "toolApproval"
    readonly property var packageInstall: backend.pendingApproval.method === "confirm" && backend.pendingApproval.title === "安装 Pi 扩展包？" ? PackageText.installRequest(backend.pendingApproval.detail) : null
    modal: false; focus: true; padding: 24
    width: Math.min(650, parent.width - 60)
    height: Math.min(490, parent.height - 80)
    visible: backend.pendingApproval.id !== undefined
    x: (parent.width - width) / 2; y: (parent.height - height) / 2
    closePolicy: Popup.NoAutoClose
    onVisibleChanged: if (visible) dialogInput.text = backend.pendingApproval.method === "editor" ? backend.pendingApproval.detail || "" : ""
    background: Rectangle { color: Theme.surface; radius: 13; border.color: Theme.line }
    Overlay.modal: Rectangle { color: "#60000000" }
    Keys.onEscapePressed: backend.respondApproval(false)
    ColumnLayout {
        anchors.fill: parent; spacing: 19
        RowLayout {
            Glyph { name: "lock"; width: Theme.icon(20); height: Theme.icon(20) }
            Text { objectName: "approvalTitle"; text: I18n.t(backend.pendingApproval.title || "操作确认"); color: Theme.ink; font.pixelSize: Theme.font(17); font.weight: Font.Medium }
        }
        ScrollView {
            visible: backend.pendingApproval.method === "confirm" && !root.packageInstall
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
            TextArea { text: backend.pendingApproval.detail || ""; color: Theme.ink; font.pixelSize: Theme.font(12); font.family: "Consolas"; readOnly: true; selectByMouse: true; wrapMode: TextArea.Wrap; padding: 14
                background: Rectangle { color: Theme.bg; radius: 7; border.color: Theme.line }
            }
        }
        ScrollView {
            visible: !!root.packageInstall
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true; contentWidth: availableWidth
            Column {
                width: parent.width; spacing: 14
                Text { width: parent.width; text: root.packageInstall ? root.packageInstall.source : ""; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Theme.ink; font.pixelSize: Theme.font(12) }
                Text { width: parent.width; text: I18n.t("安装原因：") + I18n.t(root.packageInstall ? root.packageInstall.reason : ""); textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Theme.ink; font.pixelSize: Theme.font(12) }
                PackageAudit { objectName: "approvalPackageAudit"; width: parent.width; value: root.packageInstall ? root.packageInstall.audit : "" }
            }
        }
        Picker { id: choice; Layout.fillWidth: true; visible: backend.pendingApproval.method === "select"; model: backend.pendingApproval.options || [] }
        ScrollView {
            visible: backend.pendingApproval.method === "input" || backend.pendingApproval.method === "editor"
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
            TextArea { id: dialogInput; color: Theme.ink; font.pixelSize: Theme.font(12); selectByMouse: true; wrapMode: TextArea.Wrap; placeholderText: backend.pendingApproval.method === "input" ? backend.pendingApproval.detail || "" : "" }
        }
        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            ActionButton { objectName: "denyToolButton"; text: I18n.t("拒绝"); onClicked: backend.respondApproval(false) }
            ActionButton { objectName: "allowToolButton"; text: I18n.t("确认"); primary: true; onClicked: { if (backend.pendingApproval.method === "confirm") backend.respondApproval(true); else backend.respondPiDialog(backend.pendingApproval.method === "select" ? choice.currentText : dialogInput.text) } }
        }
    }
}
