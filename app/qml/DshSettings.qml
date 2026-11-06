import QtQuick
import QtQuick.Controls
import QtQuick.Controls.impl
import QtQuick.Layouts
import QtQuick.Dialogs

Column {
    id: root
    objectName: "dshSettings"
    spacing: 16
    readonly property var runtime: backend.dshRuntime
    property bool fullRuntimePathOpen: false
    readonly property string runtimeFileName: String(runtime.resolvedPath || "").replace(/\\/g, "/").split("/").pop()

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
            // Header, label and hint sizes follow PiVersionCard and PiNpmSettings.
            RowLayout {
                Layout.fillWidth: true; spacing: 12
                // The logo is a single-colour mark; tint it so it stays visible on dark themes.
                IconImage { source: "../icons/dsh.svg"; color: Theme.ink; Layout.preferredWidth: Theme.icon(38); Layout.preferredHeight: Theme.icon(38); sourceSize: Qt.size(76,76); fillMode: Image.PreserveAspectFit }
                Text { font.family: Theme.fontFamily; text: "DeepSeek Harness"; color: Theme.ink; font.pixelSize: Theme.font(17, visible); font.weight: Font.Medium; Layout.fillWidth: true }
                Text {
                    objectName: "dshRuntimeVersion"
                    text: root.runtime.version ? (/^v/i.test(root.runtime.version) ? "" : "v") + root.runtime.version : ""
                    visible: text.length > 0; color: Theme.accent; font.family: "Consolas"; font.pixelSize: Theme.font(20, visible)
                }
            }
            ColumnLayout {
                Layout.fillWidth: true; spacing: 8
                Text { text: I18n.t("运行时路径"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible) }
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
                    color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible)
                }
                RowLayout {
                    Layout.fillWidth: true; spacing: 8
                    visible: !!root.runtime.resolvedPath
                    Text {
                        objectName: "dshRuntimeLocationSummary"
                        Layout.fillWidth: true; elide: Text.ElideMiddle
                        text: root.runtimeFileName + (root.runtime.version ? " · " + root.runtime.version : "")
                        textFormat: Text.PlainText
                        color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible)
                    }
                    ActionButton {
                        objectName: "dshRuntimeLocationToggle"
                        text: root.fullRuntimePathOpen ? I18n.t("收起完整路径") : I18n.t("查看完整路径")
                        glyph: root.fullRuntimePathOpen ? "chevron-up" : "chevron-down"; quiet: true
                        onClicked: root.fullRuntimePathOpen = !root.fullRuntimePathOpen
                    }
                }
                Text {
                    objectName: "dshRuntimeResolvedPath"
                    Layout.fillWidth: true; visible: root.fullRuntimePathOpen && text.length > 0
                    text: root.runtime.resolvedPath ? I18n.t("使用路径：") + root.runtime.resolvedPath : ""
                    textFormat: Text.PlainText; wrapMode: Text.WrapAnywhere
                    color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible)
                }
            }
            DshRuntimeStatus {
                Layout.fillWidth: true
                runtime: root.runtime
                onCheckRequested: { root.savePath(); root.runtime.check() }
                onDownloadRequested: { root.savePath(); root.runtime.download() }
            }
        }
    }
    SectionCard {
        objectName: "dshModelConfiguration"
        width: parent.width
        ColumnLayout {
            width: parent.width; spacing: 12
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                Text {
                    Layout.fillWidth: true; wrapMode: Text.Wrap
                    text: I18n.t("使用 dsh 自己的模型和 API Key 配置")
                    color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13, visible)
                }
                Toggle {
                    objectName: "dshUseOwnConfig"
                    checked: root.runtime.useOwnConfig === true
                    Accessible.name: I18n.t("使用 dsh 自己的模型和 API Key 配置")
                    onClicked: {
                        const value = checked
                        checked = Qt.binding(function() { return root.runtime.useOwnConfig === true })
                        root.runtime.setUseOwnConfig(value)
                    }
                }
            }
            Text {
                objectName: "dshUseOwnConfigHint"
                Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.PlainText
                text: I18n.t("默认通过 Umeko 现有 API 代理使用已配置的模型（包括已登录供应商），无需为 dsh 另填 API Key。开启后，读取 dsh 的 ACP profile（含其全局配置）中的模型和 API Key，Umeko 不注入供应商配置。模型来源在会话开始后固定，更改后请新建 dsh 会话。")
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
