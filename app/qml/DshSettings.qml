import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

Column {
    id: root
    objectName: "dshSettings"
    spacing: 16
    readonly property var runtime: backend.dshRuntime

    function savePath() { runtime.setPath(runtimePath.text) }
    function localPath(url) {
        let value = decodeURIComponent(String(url))
        if (value.indexOf("file:///") === 0) value = value.slice(7)
        else if (value.indexOf("file://") === 0) value = "//" + value.slice(7)
        if (/^\/[A-Za-z]:\//.test(value)) value = value.slice(1)
        return value
    }

    Connections {
        target: root.runtime
        function onChanged() { if (!runtimePath.activeFocus) runtimePath.text = root.runtime.path }
    }
    FileDialog {
        id: runtimePicker
        objectName: "dshRuntimeFileDialog"
        title: I18n.t("选择 DeepSeek Harness 可执行文件")
        fileMode: FileDialog.OpenFile
        nameFilters: [I18n.t("所有文件 (*)")]
        onAccepted: {
            runtimePath.text = root.localPath(selectedFile)
            root.savePath()
        }
    }

    SectionCard {
        width: parent.width
        ColumnLayout {
            width: parent.width; spacing: 18
            RowLayout {
                Layout.fillWidth: true; spacing: 12
                Image { source: "../icons/dsh.svg"; Layout.preferredWidth: Theme.icon(38); Layout.preferredHeight: Theme.icon(38); sourceSize: Qt.size(76,76); fillMode: Image.PreserveAspectFit }
                Text { font.family: Theme.fontFamily; text: "DeepSeek Harness"; color: Theme.ink; font.pixelSize: Theme.font(17, visible); font.weight: Font.Medium; Layout.fillWidth: true }
                Text { objectName: "dshRuntimeVersion"; text: root.runtime.version; visible: text.length > 0; color: Theme.accent; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13, visible) }
            }
            Text { text: I18n.t("运行时路径"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13, visible) }
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                InputField {
                    id: runtimePath
                    objectName: "dshRuntimePathField"
                    Layout.fillWidth: true; Layout.minimumWidth: 0
                    text: root.runtime.path
                    placeholderText: I18n.t("留空时自动查找 dsh")
                    enabled: !root.runtime.busy
                    Accessible.name: I18n.t("DeepSeek Harness 运行时路径")
                    onEditingFinished: root.savePath()
                }
                ActionButton { objectName: "browseDshRuntimeButton"; text: I18n.t("浏览…"); enabled: !root.runtime.busy; onClicked: runtimePicker.open() }
            }
            Text {
                objectName: "dshRuntimePathExample"
                Layout.fillWidth: true; wrapMode: Text.WrapAnywhere
                text: I18n.t("Windows：选择 dsh 安装目录，或 node_modules\\@deepseek-ai\\dsh\\lib\\bin.js；全局安装可选择 dsh.cmd。")
                color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible)
            }
            Text {
                objectName: "dshRuntimeResolvedPath"
                Layout.fillWidth: true; visible: text.length > 0
                text: root.runtime.resolvedPath ? I18n.t("使用路径：") + root.runtime.resolvedPath : ""
                textFormat: Text.PlainText; wrapMode: Text.WrapAnywhere
                color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible)
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                Text {
                    objectName: "dshRuntimeStatus"
                    Layout.fillWidth: true; text: root.runtime.status
                    textFormat: Text.PlainText; wrapMode: Text.Wrap
                    color: root.runtime.ready ? Theme.accent : Theme.muted
                    font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible)
                }
                ActionButton {
                    objectName: "checkDshRuntimeButton"
                    text: I18n.t("检查"); glyph: "refresh"; enabled: !root.runtime.busy
                    onClicked: { root.savePath(); root.runtime.check() }
                }
                ActionButton {
                    objectName: "downloadDshRuntimeButton"
                    text: I18n.t("下载运行时"); glyph: "download"; primary: true
                    visible: !root.runtime.ready; enabled: !root.runtime.busy
                    onClicked: { root.savePath(); root.runtime.download() }
                }
                ActionButton { objectName: "cancelDshRuntimeButton"; text: I18n.t("取消"); visible: root.runtime.busy; onClicked: root.runtime.cancel() }
            }
            ProgressBar {
                objectName: "dshRuntimeProgress"
                Layout.fillWidth: true; visible: root.runtime.busy
                from: 0; to: 1; value: root.runtime.progress
                indeterminate: root.runtime.busy && root.runtime.progress === 0
            }
            Text {
                objectName: "dshRuntimeHint"
                Layout.fillWidth: true; visible: text.length > 0; text: root.runtime.hint
                textFormat: Text.PlainText; wrapMode: Text.Wrap
                color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible)
            }
        }
    }
    SectionCard {
        width: parent.width
        ColumnLayout {
            width: parent.width; spacing: 12
            Text { text: I18n.t("当前支持范围"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(14, visible); font.weight: Font.DemiBold }
            Text {
                objectName: "dshCapabilitiesHint"
                Layout.fillWidth: true
                text: I18n.t("回复会在提交后整条显示；运行时发送的新消息会排队。权限请求仅支持本次允许或拒绝。暂不支持子智能体、上下文压缩和运行中插话（steering）。")
                textFormat: Text.PlainText; wrapMode: Text.Wrap
                color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible)
            }
        }
    }
}
