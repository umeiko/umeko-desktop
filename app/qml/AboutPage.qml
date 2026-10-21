import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Column {
    id: root
    objectName: "aboutPage"
    readonly property var about: backend.appAbout
    spacing: 18
    SectionCard {
        width: parent.width
        ColumnLayout {
            width: parent.width; spacing: 22
            RowLayout {
                Layout.fillWidth: true; spacing: 16
                Image { source: "../icons/app.png"; Layout.preferredWidth: 60; Layout.preferredHeight: 60; sourceSize: Qt.size(120, 120); mipmap: true }
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 6
                    Text { text: root.about.info.name; color: Theme.ink; font.pixelSize: 24; font.weight: Font.DemiBold }
                    Text { Layout.fillWidth: true; text: "以 Pi Coding Agent 为内核的桌面 Agent 客户端"; color: Theme.muted; font.pixelSize: 12; wrapMode: Text.Wrap }
                }
                ActionButton { objectName: "aboutProjectButton"; text: "GitHub"; glyph: "external-link"; onClicked: root.about.openProject() }
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
            GridLayout {
                Layout.fillWidth: true; columns: 2; columnSpacing: 24; rowSpacing: 13
                Text { text: "当前版本"; color: Theme.muted; font.pixelSize: 12; Layout.preferredWidth: 100 }
                TextEdit { objectName: "aboutVersion"; text: "v" + root.about.info.version; color: Theme.ink; font.pixelSize: 13; readOnly: true; selectByMouse: true; textFormat: TextEdit.PlainText }
                Text { text: "作者"; color: Theme.muted; font.pixelSize: 12 }
                ActionButton { objectName: "aboutAuthorButton"; text: root.about.info.author; glyph: "external-link"; quiet: true; implicitHeight: 26; onClicked: root.about.openAuthor() }
                Text { text: "项目地址"; color: Theme.muted; font.pixelSize: 12 }
                TextEdit { objectName: "aboutRepository"; Layout.fillWidth: true; text: root.about.info.projectUrl; color: Theme.ink; font.pixelSize: 12; readOnly: true; selectByMouse: true; textFormat: TextEdit.PlainText; wrapMode: TextEdit.Wrap }
                Text { text: "构建平台"; color: Theme.muted; font.pixelSize: 12 }
                Text { objectName: "aboutPlatform"; text: root.about.info.buildPlatform; color: Theme.ink; font.pixelSize: 12 }
                Text { text: "构建类型"; color: Theme.muted; font.pixelSize: 12 }
                Text { text: root.about.info.buildType; color: Theme.ink; font.pixelSize: 12 }
                Text { text: "构建时间"; color: Theme.muted; font.pixelSize: 12 }
                Text { text: root.about.info.builtAt; color: Theme.ink; font.pixelSize: 12 }
                Text { text: "提交版本"; color: Theme.muted; font.pixelSize: 12 }
                TextEdit { text: root.about.info.commit + (root.about.info.dirty ? "（含未提交修改）" : ""); color: Theme.ink; font.pixelSize: 12; readOnly: true; selectByMouse: true; textFormat: TextEdit.PlainText }
                Text { text: "Agent 内核"; color: Theme.muted; font.pixelSize: 12 }
                Text { text: "Pi Coding Agent · " + backend.kernelVersion; color: Theme.ink; font.pixelSize: 12 }
            }
            ActionButton { objectName: "copyAboutInfoButton"; Layout.alignment: Qt.AlignRight; text: "复制项目信息"; glyph: "copy"; quiet: true; onClicked: root.about.copyInfo() }
        }
    }
    SectionCard {
        width: parent.width
        ColumnLayout {
            width: parent.width; spacing: 14
            RowLayout {
                Layout.fillWidth: true; spacing: 12
                Text { text: "客户端更新"; color: Theme.ink; font.pixelSize: 14; font.weight: Font.DemiBold }
                Item { Layout.fillWidth: true }
                BusyIndicator { visible: root.about.busy; running: visible; implicitWidth: 22; implicitHeight: 22 }
                ActionButton { objectName: "checkAppUpdatesButton"; text: root.about.busy ? "检查中…" : "检查更新"; glyph: "refresh"; primary: true; enabled: !root.about.busy; onClicked: root.about.checkUpdates() }
            }
            Text { objectName: "appUpdateStatus"; Layout.fillWidth: true; text: root.about.release.message || "检查 GitHub 上的最新正式发布版本。"; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: root.about.release.state === "error" ? Theme.danger : root.about.release.state === "available" ? Theme.accent : Theme.ink; font.pixelSize: 12 }
            Text { visible: root.about.checkedAt !== ""; text: "上次检查：" + root.about.checkedAt; color: Theme.muted; font.pixelSize: 11 }
            InlineScrollView {
                visible: (root.about.release.notes || "") !== ""
                Layout.fillWidth: true; Layout.preferredHeight: 160; clip: true
                TextArea { objectName: "appReleaseNotes"; text: root.about.release.notes || ""; textFormat: TextEdit.PlainText; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; color: Theme.ink; font.pixelSize: 12; padding: 12
                    background: Rectangle { radius: 8; color: Theme.bg; border.color: Theme.line }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Text { Layout.fillWidth: true; text: "更新包及完整说明在 GitHub 发布页查看。"; color: Theme.muted; font.pixelSize: 11; wrapMode: Text.Wrap }
                ActionButton { objectName: "openAppReleasesButton"; text: root.about.release.state === "available" ? "前往下载" : "查看发布页"; glyph: "external-link"; onClicked: root.about.openReleases() }
            }
        }
    }
}
