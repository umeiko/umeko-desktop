import QtQuick

Row {
    property var about: backend.appAbout
    spacing: 4
    ActionButton {
        id: updateButton
        objectName: "sidebarUpdateButton"
        readonly property bool downloading: about.download.state === "downloading"
        readonly property bool ready: about.download.state === "ready"
        visible: about.release.state === "available"
        width: Theme.control(26); height: Theme.control(26)
        quiet: true; enabled: !downloading
        hint: downloading ? I18n.t("正在下载更新包…") : ready ? I18n.t("更新包已下载，点击查看") : I18n.t("发现新版本，点击下载") + " " + (about.release.version || "")
        onClicked: ready ? about.showDownloadedUpdate() : about.downloadUpdate()
        contentItem: Item {
            Glyph { anchors.centerIn: parent; name: updateButton.ready ? "folder" : "download"; color: Theme.accent; width: Theme.icon(17); height: width; visible: !updateButton.downloading }
            Text { anchors.centerIn: parent; text: (about.download.progress || 0) + "%"; color: Theme.accent; font.pixelSize: Theme.font(9); visible: updateButton.downloading }
        }
    }
    Text {
        anchors.verticalCenter: parent.verticalCenter
        visible: Theme.fontScale <= 1.5
        text: "v" + about.info.version
        color: Theme.muted; font.pixelSize: Theme.font(10)
    }
}
