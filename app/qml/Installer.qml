import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    objectName: "updateInstallerWindow"
    visible: true
    width: 360; height: Math.max(380, content.implicitHeight + 64)
    minimumWidth: 320; minimumHeight: 360
    title: english ? "Umeko Update" : "Umeko 更新"
    color: "#f7f9fd"
    readonly property string state: installer.status.state || "waiting"
    readonly property bool english: installer.language === "en"
    readonly property bool settled: state === "complete" || state === "error"
    readonly property string statusText: {
        switch (state) {
        case "complete": return installer.status.launchError || (english ? "Installed" : "安装完成")
        case "error": return installer.status.message || (english ? "Installation failed" : "安装失败")
        case "waiting": return english ? "Waiting for Umeko…" : "等待退出…"
        case "verifying": return english ? "Verifying…" : "校验中…"
        default: return english ? "Installing…" : "安装中…"
        }
    }
    onClosing: function(close) { close.accepted = settled }
    ColumnLayout {
        id: content
        anchors.centerIn: parent
        width: parent.width - 64
        spacing: 22
        Image {
            objectName: "installerMascot"
            source: window.state === "complete" || window.state === "error" ? "../icons/yanami-installer.png" : "../icons/yanami-installing.png"
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: 192; Layout.preferredHeight: 192
            fillMode: Image.PreserveAspectFit
            smooth: false; mipmap: false
        }
        Text {
            objectName: "installerStatus"
            text: window.statusText
            Accessible.name: installer.status.message || text
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap; textFormat: Text.PlainText
            color: window.state === "error" ? "#b94d5b" : "#354862"
            font.pixelSize: 14
        }
        ProgressBar {
            id: progress
            objectName: "installerProgress"
            Layout.fillWidth: true
            visible: window.state !== "error"
            from: 0; to: 1
            value: Math.max(0, installer.status.progress || 0)
            indeterminate: !window.settled && (installer.status.progress === undefined || installer.status.progress < 0)
            background: Rectangle { implicitHeight: 3; radius: 1.5; color: "#e1e7f0" }
            contentItem: Item {
                implicitHeight: 3; clip: true
                Rectangle {
                    property real slide: 0
                    x: progress.indeterminate ? parent.width * slide : 0
                    width: parent.width * (progress.indeterminate ? 0.3 : progress.visualPosition)
                    height: 3; radius: 1.5; color: "#527bbd"
                    NumberAnimation on slide { running: progress.indeterminate; from: -0.3; to: 1; duration: 1200; loops: Animation.Infinite }
                }
            }
        }
        Button {
            objectName: "finishInstallationButton"
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: 112; implicitHeight: 36
            visible: window.settled; enabled: window.settled
            text: window.state === "complete" ? (window.english ? "Launch" : "启动") : (window.english ? "Close" : "关闭")
            onClicked: installer.finish()
            background: Rectangle { radius: 7; color: parent.down ? "#436aa9" : parent.hovered ? "#5d85c4" : "#527bbd" }
            contentItem: Text {
                text: parent.text; color: "white"; font.pixelSize: 13
                horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
            }
        }
    }
}
