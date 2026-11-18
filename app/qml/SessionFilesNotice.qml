import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: root
    objectName: "sessionFilesFailurePopup"
    parent: Overlay.overlay
    width: Math.min(500, parent.width - 40)
    height: Math.min(430, parent.height - 40)
    x: (parent.width-width)/2; y: (parent.height-height)/2
    modal: true; focus: true; padding: 22
    background: Rectangle { radius: 12; color: Theme.surface; border.color: Theme.line }
    onClosed: backend.sessionFiles.dismissFailure()
    Connections {
        target: backend.sessionFiles
        function onFailureChanged() { if (backend.sessionFiles.failure.title) root.open() }
    }
    ColumnLayout {
        anchors.fill: parent; spacing: 16
        Text { Layout.fillWidth: true; wrapMode: Text.Wrap; text: I18n.t(backend.sessionFiles.failure.title || "无法导入会话"); font.family: Theme.fontFamily; font.pixelSize: Theme.font(16, visible); font.weight: Font.Medium; color: Theme.ink }
        ScrollView {
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
            TextArea { objectName: "sessionFilesFailureDetails"; text: backend.sessionFiles.failure.details || ""; textFormat: TextEdit.PlainText; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible); background: null }
        }
        ActionButton { Layout.alignment: Qt.AlignRight; text: I18n.t("知道了"); primary: true; onClicked: root.close() }
    }
}
