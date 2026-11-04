import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: root
    property var channel: backend.appAbout.preview
    function remedy(name) {
        switch (name) {
        case "保留的正式版": return I18n.t("请从完整解压的正式版安装包启动，再检查运行前提。")
        case "Git": return I18n.t("请安装 Git 并将其加入 PATH，然后重新打开 Umeko。")
        case "Python 3.10+ / venv": return I18n.t("请安装含 venv 和 ensurepip 的 Python 3.10 或更新版本，并将 Python 或 py 启动器加入 PATH，然后重新打开 Umeko。")
        case "Node.js 22.19+": return I18n.t("请安装 Node.js 22.19 或更新版本并将其加入 PATH；打包版请先重新解压完整安装包。然后重新打开 Umeko。")
        case "npm": return I18n.t("请安装含 npm 的 Node.js，并将 npm 加入 PATH，然后重新打开 Umeko。")
        case "安装脚本 Shell": return I18n.t("Windows 请确保 PowerShell 可用；macOS 和 Linux 请安装 Bash 并将其加入 PATH。")
        case "磁盘空间 (至少 2 GiB)": return I18n.t("请在用户数据目录所在磁盘腾出至少 2 GiB 可用空间，然后重新检查。")
        case "官方 main 分支连接": return I18n.t("请检查系统和 Git 的网络、代理及证书配置，确保 Git 能连接官方仓库，然后重新检查。供应商代理不用于此操作。")
        default: return I18n.t("请根据下方检查详情处理问题，然后重新检查。")
        }
    }
    function details() {
        const checks = root.channel.status.details
        if (checks && checks.length)
            return checks.map(check => I18n.t(check.ready ? "已满足" : "未满足") + " · " + I18n.t(check.name) + ": " + String(check.detail || "").split("\n").map(line => I18n.t(line)).join("\n") + (check.ready ? "" : "\n" + (check.hint ? I18n.t(check.hint) : root.remedy(check.name))) + (check.limitation ? "\n" + I18n.t(check.limitation) : "")).join("\n")
        return String(root.channel.status.detail || "").split("\n").map(line => I18n.t(line)).join("\n") + (root.channel.status.hint ? "\n" + I18n.t(root.channel.status.hint) : "") + (root.channel.status.limitation ? "\n" + I18n.t(root.channel.status.limitation) : "")
    }
    spacing: 14
    RowLayout {
        Layout.fillWidth: true
        Text { text: I18n.t("更新通道"); font.family: Theme.fontFamily; font.pixelSize: Theme.font(14, visible); font.weight: Font.DemiBold; color: Theme.ink }
        Item { Layout.fillWidth: true }
        Picker {
            objectName: "updateChannelPicker"
            visible: root.channel.supported
            Layout.preferredWidth: 180
            model: [I18n.t("正式版"), I18n.t("预览版")]
            currentIndex: root.channel.channel === "preview" ? 1 : 0
            enabled: !root.channel.busy
            onActivated: index => {
                if (index === 1 && root.channel.channel === "release") root.channel.preflight()
                if (index === 0 && root.channel.channel === "preview") releaseConfirmation.open()
                currentIndex = Qt.binding(() => root.channel.channel === "preview" ? 1 : 0)
            }
        }
    }
    Text {
        objectName: "previewChannelWarning"
        Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.PlainText
        text: root.channel.supported ? I18n.t("正式版使用已发布的安装包。预览版从官方 main 分支的 Python 源码运行，包含最新未发布改动，可能不稳定。") : I18n.t("预览通道支持 Windows、macOS 和 Linux 的 Python 安装包。请从正式版安装包启用；普通源码工作目录不提供通道切换。")
        font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible); color: Theme.muted
    }
    Text {
        objectName: "previewChannelStatus"
        Layout.fillWidth: true; visible: !!root.channel.status.message
        text: I18n.t(root.channel.status.message); textFormat: Text.PlainText; wrapMode: Text.Wrap
        font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible)
        color: root.channel.status.state === "error" ? Theme.danger : Theme.ink
    }
    Text {
        objectName: "previewPrerequisiteResult"
        Layout.fillWidth: true
        visible: root.channel.status.state === "prerequisites"
        text: I18n.t(root.channel.status.ready ? "运行前提全部满足，可以确认并安装预览版。" : "运行前提尚未满足，安装按钮暂不可用。请处理下列未满足项目后重新检查。")
        textFormat: Text.PlainText; wrapMode: Text.Wrap
        font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible)
        color: root.channel.status.ready ? Theme.ink : Theme.danger
    }
    Text {
        objectName: "previewChannelDetails"
        Layout.fillWidth: true; visible: !!root.channel.status.detail || !!(root.channel.status.details && root.channel.status.details.length)
        text: root.details(); textFormat: Text.PlainText; wrapMode: Text.Wrap
        font.family: Theme.fontFamily; font.pixelSize: Theme.font(11, visible); color: Theme.muted
    }
    ProgressBar { Layout.fillWidth: true; visible: root.channel.busy; indeterminate: true }
    RowLayout {
        Layout.fillWidth: true
        Item { Layout.fillWidth: true }
        ActionButton { objectName: "checkPreviewUpdatesButton"; visible: root.channel.channel === "preview"; enabled: !root.channel.busy; text: I18n.t("检查预览版更新"); glyph: "refresh"; onClicked: root.channel.checkUpdates() }
        ActionButton { objectName: "removeRetainedPreviewButton"; visible: root.channel.channel === "release" && root.channel.cleanupPending; enabled: !root.channel.busy; text: I18n.t("重试删除预览版源码"); onClicked: root.channel.finishRemoval() }
        ActionButton { objectName: "reviewPreviewUpdateButton"; visible: root.channel.status.state === "available"; enabled: !root.channel.busy; text: I18n.t("查看并更新"); primary: true; onClicked: updateConfirmation.open() }
        ActionButton { objectName: "recheckPreviewPrerequisitesButton"; visible: root.channel.channel === "release" && root.channel.status.state === "prerequisites"; enabled: !root.channel.busy; text: I18n.t("重新检查运行前提"); glyph: "refresh"; onClicked: root.channel.preflight() }
        ActionButton { objectName: "preparePreviewButton"; visible: root.channel.status.state === "prerequisites"; enabled: !!root.channel.status.ready && !root.channel.busy; text: I18n.t("确认并安装预览版"); primary: true; onClicked: switchConfirmation.open() }
        ActionButton { objectName: "cancelPreviewButton"; visible: root.channel.busy; text: I18n.t("取消"); onClicked: root.channel.cancel() }
        ActionButton { objectName: "restartChannelButton"; visible: root.channel.status.state === "restart-required"; enabled: !root.channel.busy; text: I18n.t("保存并重启"); primary: true; onClicked: restartConfirmation.open() }
    }
    Popup {
        id: switchConfirmation
        objectName: "previewSwitchConfirmation"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(560, parent.width - 48)
        modal: true; focus: true; padding: 24; closePolicy: Popup.CloseOnEscape
        background: Rectangle { color: Theme.surface; radius: 13; border.color: Theme.line }
        Overlay.modal: Rectangle { color: "#66000000" }
        contentItem: ColumnLayout {
            spacing: 16
            Text { text: I18n.t("切换到预览版？"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(18, visible); font.weight: Font.DemiBold }
            Text { Layout.fillWidth: true; text: I18n.t("将下载官方源码并运行仓库自带的 setup 脚本。安装失败或取消时仍使用正式版；安装包会保留。首次准备可能需要几分钟。"); color: Theme.muted; wrapMode: Text.Wrap; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13, visible) }
            Text { Layout.fillWidth: true; text: I18n.t("两个通道共用设置与会话。预览版可能迁移配置，切回正式版不会撤销迁移。切换前请关闭任务并备份用户数据目录；凭据仍保存在本机凭据存储中。"); color: Theme.muted; wrapMode: Text.Wrap; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13, visible) }
            Text { Layout.fillWidth: true; text: I18n.t("若预览版无法启动，可用 --release-channel 参数启动原安装包，直接返回正式版。"); color: Theme.muted; wrapMode: Text.Wrap; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13, visible) }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                ActionButton { text: I18n.t("取消"); onClicked: switchConfirmation.close() }
                ActionButton { objectName: "confirmPreviewSwitchButton"; text: I18n.t("安装预览版"); primary: true; onClicked: { switchConfirmation.close(); root.channel.switchToPreview() } }
            }
        }
    }
    Popup {
        id: updateConfirmation
        objectName: "previewUpdateConfirmation"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(600, parent.width - 48)
        modal: true; focus: true; padding: 24; closePolicy: Popup.CloseOnEscape
        background: Rectangle { color: Theme.surface; radius: 13; border.color: Theme.line }
        Overlay.modal: Rectangle { color: "#66000000" }
        contentItem: ColumnLayout {
            spacing: 16
            Text { text: I18n.t("应用预览版更新？"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(18, visible); font.weight: Font.DemiBold }
            Text { objectName: "previewCommitRange"; Layout.fillWidth: true; text: (root.channel.status.base || "").slice(0, 12) + " → " + (root.channel.status.target || "").slice(0, 12); textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible) }
            ScrollView {
                Layout.fillWidth: true; Layout.preferredHeight: 150; clip: true
                TextArea { objectName: "previewCommitSummary"; text: root.channel.status.summary || ""; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; textFormat: TextEdit.PlainText; color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible); background: Rectangle { color: Theme.bg; radius: 8 } }
            }
            Text { Layout.fillWidth: true; text: I18n.t(root.channel.status.dependencyPending || (root.channel.status.dependencies || []).length > 0 ? "仅快进更新到上述提交，然后重新同步依赖。本地改动或冲突文件会阻止更新。完成后可选择重启。" : "仅快进更新到上述提交，依赖文件未变则跳过安装。本地改动或冲突文件会阻止更新。完成后可选择重启。"); wrapMode: Text.Wrap; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13, visible) }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                ActionButton { text: I18n.t("取消"); onClicked: updateConfirmation.close() }
                ActionButton { objectName: "confirmPreviewUpdateButton"; text: I18n.t("快进更新"); primary: true; onClicked: { updateConfirmation.close(); root.channel.applyUpdate() } }
            }
        }
    }
    Popup {
        id: releaseConfirmation
        objectName: "releaseChannelConfirmation"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(540, parent.width - 48)
        modal: true; focus: true; padding: 24; closePolicy: Popup.CloseOnEscape
        background: Rectangle { color: Theme.surface; radius: 13; border.color: Theme.line }
        Overlay.modal: Rectangle { color: "#66000000" }
        contentItem: ColumnLayout {
            spacing: 16
            Text { text: I18n.t("切回正式版？"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(18, visible); font.weight: Font.DemiBold }
            Text { Layout.fillWidth: true; text: I18n.t("下次启动使用保留的安装包。设置、凭据与会话不会删除；预览版的配置迁移不会自动撤销。"); wrapMode: Text.Wrap; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13, visible) }
            CheckBox { id: removeSource; objectName: "removePreviewCheckout"; text: I18n.t("重启正式版后删除预览版源码和依赖"); checked: false; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible) }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                ActionButton { text: I18n.t("取消"); onClicked: releaseConfirmation.close() }
                ActionButton { objectName: "confirmReleaseChannelButton"; text: I18n.t("切回正式版"); primary: true; onClicked: { releaseConfirmation.close(); root.channel.switchToRelease(removeSource.checked) } }
            }
        }
    }
    Popup {
        id: restartConfirmation
        objectName: "previewRestartConfirmation"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(480, parent.width - 48)
        modal: true; focus: true; padding: 24; closePolicy: Popup.CloseOnEscape
        background: Rectangle { color: Theme.surface; radius: 13; border.color: Theme.line }
        contentItem: ColumnLayout {
            spacing: 16
            Text { text: I18n.t("保存并重启？"); color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(18, visible) }
            Text { Layout.fillWidth: true; text: I18n.t("将停止所有 Agent 并关闭 Umeko。工作记录与设置会保存，未完成任务需重新发起。"); wrapMode: Text.Wrap; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13, visible) }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                ActionButton { text: I18n.t("取消"); onClicked: restartConfirmation.close() }
                ActionButton { objectName: "confirmChannelRestartButton"; text: I18n.t("保存并重启"); primary: true; onClicked: { restartConfirmation.close(); root.channel.restart() } }
            }
        }
    }
}
