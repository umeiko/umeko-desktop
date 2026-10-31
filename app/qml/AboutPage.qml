import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "markdown.js" as Markdown

Column {
    id: root
    objectName: "aboutPage"
    readonly property var about: backend.appAbout
    readonly property bool transferring: about.download.state === "downloading" || about.download.state === "verifying"
    function bytes(value) {
        const n = Math.max(0, Number(value || 0))
        return n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : (n / 1024).toFixed(0) + " KB"
    }
    function remaining(seconds) {
        return seconds >= 60 ? Math.ceil(seconds / 60) + I18n.t("分钟") : Math.ceil(seconds) + I18n.t("秒")
    }
    spacing: 18
    AppInstallDialog { id: installConfirmation; about: root.about }
    SectionCard {
        width: parent.width
        ColumnLayout {
            width: parent.width; spacing: 22
            RowLayout {
                Layout.fillWidth: true; spacing: 16
                Image { source: "../icons/app.png"; Layout.preferredWidth: 60; Layout.preferredHeight: 60; sourceSize: Qt.size(120, 120); mipmap: true }
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 6
                    Text { font.family: Theme.fontFamily; text: root.about.info.name; color: Theme.ink; font.pixelSize: Theme.font(24, visible); font.weight: Font.DemiBold }
                    Text { font.family: Theme.fontFamily; Layout.fillWidth: true; text: I18n.t("以 Pi Coding Agent 为内核的桌面 Agent 客户端"); color: Theme.muted; font.pixelSize: Theme.font(12, visible); wrapMode: Text.Wrap }
                }
                ActionButton { objectName: "aboutProjectButton"; text: "GitHub"; glyph: "external-link"; onClicked: root.about.openProject() }
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
            GridLayout {
                Layout.fillWidth: true; columns: 2; columnSpacing: 24; rowSpacing: 13
                Text { font.family: Theme.fontFamily; text: I18n.t("当前版本"); color: Theme.muted; font.pixelSize: Theme.font(12, visible); Layout.preferredWidth: 100 }
                TextEdit { font.family: Theme.fontFamily; objectName: "aboutVersion"; text: "v" + root.about.info.version; color: Theme.ink; font.pixelSize: Theme.font(13, visible); readOnly: true; selectByMouse: true; textFormat: TextEdit.PlainText }
                Text { font.family: Theme.fontFamily; text: I18n.t("作者"); color: Theme.muted; font.pixelSize: Theme.font(12, visible) }
                ActionButton { objectName: "aboutAuthorButton"; text: root.about.info.author; glyph: "external-link"; quiet: true; implicitHeight: 26; onClicked: root.about.openAuthor() }
                Text { font.family: Theme.fontFamily; text: I18n.t("项目地址"); color: Theme.muted; font.pixelSize: Theme.font(12, visible) }
                TextEdit { font.family: Theme.fontFamily; objectName: "aboutRepository"; Layout.fillWidth: true; text: root.about.info.projectUrl; color: Theme.ink; font.pixelSize: Theme.font(12, visible); readOnly: true; selectByMouse: true; textFormat: TextEdit.PlainText; wrapMode: TextEdit.Wrap }
                Text { font.family: Theme.fontFamily; text: I18n.t("构建平台"); color: Theme.muted; font.pixelSize: Theme.font(12, visible) }
                Text { font.family: Theme.fontFamily; objectName: "aboutPlatform"; text: root.about.info.buildPlatform; color: Theme.ink; font.pixelSize: Theme.font(12, visible) }
                Text { font.family: Theme.fontFamily; text: I18n.t("构建类型"); color: Theme.muted; font.pixelSize: Theme.font(12, visible) }
                Text { font.family: Theme.fontFamily; text: root.about.info.buildType; color: Theme.ink; font.pixelSize: Theme.font(12, visible) }
                Text { font.family: Theme.fontFamily; text: I18n.t("构建时间"); color: Theme.muted; font.pixelSize: Theme.font(12, visible) }
                Text { font.family: Theme.fontFamily; text: root.about.info.builtAt; color: Theme.ink; font.pixelSize: Theme.font(12, visible) }
                Text { font.family: Theme.fontFamily; text: I18n.t("提交版本"); color: Theme.muted; font.pixelSize: Theme.font(12, visible) }
                TextEdit { font.family: Theme.fontFamily; text: root.about.info.commit + (root.about.info.dirty ? I18n.t("（含未提交修改）") : ""); color: Theme.ink; font.pixelSize: Theme.font(12, visible); readOnly: true; selectByMouse: true; textFormat: TextEdit.PlainText }
                Text { font.family: Theme.fontFamily; text: I18n.t("Agent 内核"); color: Theme.muted; font.pixelSize: Theme.font(12, visible) }
                Text { font.family: Theme.fontFamily; text: "Pi Coding Agent · " + backend.kernelVersion; color: Theme.ink; font.pixelSize: Theme.font(12, visible) }
            }
            ActionButton { objectName: "copyAboutInfoButton"; Layout.alignment: Qt.AlignRight; text: I18n.t("复制项目信息"); glyph: "copy"; quiet: true; onClicked: root.about.copyInfo() }
        }
    }
    SectionCard {
        width: parent.width
        ColumnLayout {
            width: parent.width; spacing: 14
            RowLayout {
                Layout.fillWidth: true; spacing: 12
                Text { font.family: Theme.fontFamily; text: I18n.t("客户端更新"); color: Theme.ink; font.pixelSize: Theme.font(14, visible); font.weight: Font.DemiBold }
                Item { Layout.fillWidth: true }
                BusyIndicator { visible: root.about.busy; running: visible; implicitWidth: 22; implicitHeight: 22 }
                ActionButton { objectName: "checkAppUpdatesButton"; text: root.about.busy ? I18n.t("检查中…") : I18n.t("检查更新"); glyph: "refresh"; primary: true; enabled: !root.about.busy && !root.transferring; onClicked: root.about.checkUpdates() }
            }
            Text { font.family: Theme.fontFamily; objectName: "appUpdateStatus"; Layout.fillWidth: true; text: I18n.t(root.about.release.message) || I18n.t("检查 GitHub 上的最新正式发布版本。"); textFormat: Text.PlainText; wrapMode: Text.Wrap; color: root.about.release.state === "error" ? Theme.danger : root.about.release.state === "available" ? Theme.accent : Theme.ink; font.pixelSize: Theme.font(12, visible) }
            Text { font.family: Theme.fontFamily; visible: root.about.checkedAt !== ""; text: I18n.t("上次检查：") + root.about.checkedAt; color: Theme.muted; font.pixelSize: Theme.font(11, visible) }
            Text { font.family: Theme.fontFamily; objectName: "appDownloadStatus"; Layout.fillWidth: true; visible: !!root.about.download.state; text: I18n.t(root.about.download.message) + (root.about.download.state === "downloading" ? " " + (root.about.download.progress || 0) + "%" : root.about.download.state === "ready" ? " · " + root.about.download.path : ""); color: root.about.download.state === "error" ? Theme.danger : Theme.muted; font.pixelSize: Theme.font(12, visible); wrapMode: Text.Wrap; textFormat: Text.PlainText }
            Text { font.family: Theme.fontFamily;
                objectName: "appDownloadDetails"
                Layout.fillWidth: true; visible: !!root.about.download.total && root.about.download.state !== "ready"
                text: root.bytes(root.about.download.received) + " / " + root.bytes(root.about.download.total)
                      + (root.about.download.speed > 0 ? " · " + root.bytes(root.about.download.speed) + "/s" : "")
                      + (root.about.download.eta > 0 && root.about.download.state === "downloading" ? " · " + I18n.t("剩余约 ") + root.remaining(root.about.download.eta) : "")
                      + (root.about.download.route ? " · " + I18n.t(root.about.download.route) : "")
                color: Theme.muted; font.pixelSize: Theme.font(11, visible); wrapMode: Text.Wrap
            }
            ProgressBar { objectName: "appDownloadProgress"; Layout.fillWidth: true; visible: root.transferring || !!root.about.download.resumable || root.about.busy && !!root.about.installation.state; value: (root.about.download.progress || 0) / 100; indeterminate: root.about.download.state === "verifying" || root.about.busy && !root.transferring }

            Text { font.family: Theme.fontFamily; Layout.fillWidth: true; visible: !!root.about.installation.message; text: I18n.t(root.about.installation.message); color: root.about.installation.state === "error" ? Theme.danger : Theme.muted; font.pixelSize: Theme.font(12, visible); wrapMode: Text.Wrap; textFormat: Text.PlainText }
            InlineScrollView {
                visible: (root.about.release.notes || "") !== ""
                Layout.fillWidth: true; Layout.preferredHeight: 160; clip: true
                TextArea {
                    objectName: "appReleaseNotes"
                    text: Markdown.forQt(root.about.release.notes || "")
                    textFormat: TextEdit.MarkdownText
                    readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap
                    color: Theme.ink; palette.link: Theme.accent
                    selectionColor: Theme.selectionBg; selectedTextColor: Theme.selectionText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.font(12, visible); padding: 12
                    onLinkActivated: link => { if (/^https?:\/\//i.test(link)) Qt.openUrlExternally(link) }
                    background: Rectangle { radius: 8; color: Theme.bg; border.color: Theme.line }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "openAppReleasesButton"; text: I18n.t("查看发布页"); glyph: "external-link"; onClicked: root.about.openReleases() }
                ActionButton { objectName: "downloadAppUpdateButton"; visible: !!root.about.release.asset && root.about.download.state !== "ready"; text: I18n.t(root.about.download.state === "paused" || root.about.download.resumable ? "继续下载" : "下载更新"); glyph: "download"; primary: true; enabled: !root.about.busy && !root.transferring; onClicked: root.about.downloadUpdate() }
                ActionButton { objectName: "installAppUpdateButton"; visible: root.about.download.state === "ready"; text: I18n.t("安装新版本"); glyph: "refresh"; primary: true; enabled: !root.about.busy; onClicked: installConfirmation.open() }
                ActionButton { objectName: "cancelAppDownloadButton"; visible: root.transferring; text: I18n.t("暂停下载"); onClicked: root.about.cancelUpdate() }
                ActionButton { visible: root.about.download.state === "ready"; glyph: "folder"; quiet: true; hint: I18n.t("在文件夹中查看"); onClicked: root.about.showDownloadedUpdate() }
            }
        }
    }
}
