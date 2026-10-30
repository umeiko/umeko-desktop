import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: root
    property var approvalBackend: backend
    property string actionPrefix: ""
    objectName: "toolApproval"
    modal: false; focus: true; padding: 24
    width: Math.min(650, parent.width - 60)
    height: Math.min(490, parent.height - 80)
    visible: root.approvalBackend.pendingApproval.id !== undefined
    x: (parent.width - width) / 2; y: (parent.height - height) / 2
    closePolicy: Popup.NoAutoClose
    onVisibleChanged: if (visible) dialogInput.text = root.approvalBackend.pendingApproval.method === "editor" ? root.approvalBackend.pendingApproval.detail || "" : ""
    background: Rectangle { color: Theme.surface; radius: 13; border.color: Theme.line }
    Overlay.modal: Rectangle { color: "#60000000" }
    Shortcut { sequence: "Escape"; enabled: root.visible; onActivated: root.approvalBackend.respondApproval(false) }
    ColumnLayout {
        anchors.fill: parent; spacing: 19
        RowLayout {
            Glyph { name: "lock"; width: Theme.icon(20); height: Theme.icon(20) }
            Text { text: root.approvalBackend.pendingApproval.title || I18n.t("操作确认"); color: Theme.ink; font.pixelSize: Theme.font(17); font.weight: Font.Medium }
        }
        ScrollView {
            visible: root.approvalBackend.pendingApproval.method === "confirm"
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
            TextArea { text: root.approvalBackend.pendingApproval.detail || ""; color: Theme.ink; font.pixelSize: Theme.font(12); font.family: "Consolas"; readOnly: true; selectByMouse: true; wrapMode: TextArea.Wrap; padding: 14
                background: Rectangle { color: Theme.bg; radius: 7; border.color: Theme.line }
            }
        }
        Picker { id: choice; Layout.fillWidth: true; visible: root.approvalBackend.pendingApproval.method === "select"; model: root.approvalBackend.pendingApproval.options || [] }
        ScrollView {
            visible: root.approvalBackend.pendingApproval.method === "input" || root.approvalBackend.pendingApproval.method === "editor"
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
            TextArea { id: dialogInput; color: Theme.ink; font.pixelSize: Theme.font(12); selectByMouse: true; wrapMode: TextArea.Wrap; placeholderText: root.approvalBackend.pendingApproval.method === "input" ? root.approvalBackend.pendingApproval.detail || "" : "" }
        }
        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            ActionButton { objectName: root.actionPrefix + "denyToolButton"; text: I18n.t("拒绝"); onClicked: root.approvalBackend.respondApproval(false) }
            ActionButton { objectName: root.actionPrefix + "allowToolButton"; text: I18n.t("确认"); primary: true; onClicked: { if (root.approvalBackend.pendingApproval.method === "confirm") root.approvalBackend.respondApproval(true); else root.approvalBackend.respondPiDialog(root.approvalBackend.pendingApproval.method === "select" ? choice.currentText : dialogInput.text) } }
        }
    }
}
