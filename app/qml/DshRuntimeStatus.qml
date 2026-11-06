import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Check/download state of the dsh runtime, with its actions.
ColumnLayout {
    id: root
    property var runtime
    signal checkRequested()
    signal downloadRequested()
    spacing: 10

    RowLayout {
        Layout.fillWidth: true; spacing: 8
        ColumnLayout {
            Layout.fillWidth: true; spacing: 4
            Text {
                objectName: "dshRuntimeStatus"
                Layout.fillWidth: true; text: I18n.t(root.runtime.status)
                textFormat: Text.PlainText; wrapMode: Text.Wrap
                // Same status colours as the About and MCP install sections.
                color: root.runtime.ready ? Theme.accent : root.runtime.failed && !root.runtime.busy ? Theme.danger : Theme.muted
                font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible)
            }
            Text {
                objectName: "dshRuntimeHint"
                Layout.fillWidth: true; visible: text.length > 0; text: I18n.t(root.runtime.hint)
                textFormat: Text.PlainText; wrapMode: Text.Wrap
                color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible)
            }
        }
        ActionButton {
            objectName: "checkDshRuntimeButton"
            Layout.alignment: Qt.AlignTop
            text: I18n.t("检查"); glyph: "refresh"; enabled: !root.runtime.busy
            onClicked: root.checkRequested()
        }
        ActionButton {
            objectName: "downloadDshRuntimeButton"
            Layout.alignment: Qt.AlignTop
            text: I18n.t("下载运行时"); glyph: "download"; primary: true
            visible: !root.runtime.ready; enabled: !root.runtime.busy
            onClicked: root.downloadRequested()
        }
        ActionButton {
            objectName: "cancelDshRuntimeButton"
            Layout.alignment: Qt.AlignTop
            text: I18n.t("取消"); visible: root.runtime.busy
            onClicked: root.runtime.cancel()
        }
    }
    ProgressBar {
        objectName: "dshRuntimeProgress"
        Layout.fillWidth: true; visible: root.runtime.busy
        from: 0; to: 1; value: root.runtime.progress
        indeterminate: root.runtime.busy && root.runtime.progress === 0
    }
}
