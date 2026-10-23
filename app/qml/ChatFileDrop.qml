import QtQuick

DropArea {
    id: root
    objectName: "chatFileDropArea"
    property var chatWindow: null
    property int sloganIndex: -1
    readonly property var slogans: [I18n.t("把文件放这里，马上开工。"), I18n.t("投喂一点资料，马上开动脑筋！"), I18n.t("放心松手，已经准备好啦。"), I18n.t("文件我来接，灵感你来写。")]
    onEntered: drag => {
        drag.accepted = drag.hasUrls && drag.urls.length > 0 && drag.urls.every(url => url.toString().startsWith("file:"))
        if (drag.accepted) sloganIndex = (sloganIndex + 1) % slogans.length
    }
    onDropped: drop => {
        if (!drop.hasUrls || !drop.urls.length) { drop.accepted = false; return }
        if (chatWindow) chatWindow.acceptChatFiles(drop.urls.map(url => url.toString()))
        drop.acceptProposedAction()
    }
    Rectangle {
        objectName: "chatFileDropOverlay"; anchors.fill: parent; anchors.margins: 14; radius: 18
        visible: root.containsDrag; color: Qt.alpha(Theme.bg, 0.96); border.color: Qt.alpha(Theme.accent, 0.6); border.width: 2
        Column {
            anchors.centerIn: parent; width: parent.width - 64; spacing: 12
            Image {
                id: mascot
                objectName: "fileCatchMascot"; anchors.horizontalCenter: parent.horizontalCenter
                width: 184; height: 184; source: root.containsDrag ? "../icons/yanami-catch.png" : ""; asynchronous: true; cache: true; sourceSize: Qt.size(368, 368); fillMode: Image.PreserveAspectFit; mipmap: true
                property real lift: 0
                transform: Translate { y: mascot.lift }
                SequentialAnimation on lift { running: root.containsDrag; loops: Animation.Infinite; NumberAnimation { from: 0; to: -5; duration: 850; easing.type: Easing.InOutSine } NumberAnimation { from: -5; to: 0; duration: 850; easing.type: Easing.InOutSine } }
            }
            Text { width: parent.width; text: I18n.t("松手，接住啦！"); color: Theme.ink; font.pixelSize: Theme.font(21); font.weight: Font.DemiBold; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap }
            Text { width: parent.width; text: root.slogans[Math.max(0, root.sloganIndex)]; color: Theme.muted; font.pixelSize: Theme.font(13); horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap }
        }
    }
}
