import QtQuick

DropArea {
    id: root
    objectName: "chatFileDropArea"
    property var chatWindow: null
    property string mascotSource: "../icons/yanami-catch.png"
    property string overlayName: "chatFileDropOverlay"
    property string mascotName: "fileCatchMascot"
    onEntered: drag => {
        drag.accepted = drag.hasUrls && drag.urls.length > 0 && drag.urls.every(url => url.toString().startsWith("file:"))
    }
    onDropped: drop => {
        if (!drop.hasUrls || !drop.urls.length || !drop.urls.every(url => url.toString().startsWith("file:"))) { drop.accepted = false; return }
        if (chatWindow && chatWindow.acceptChatFiles(drop.urls.map(url => url.toString())) !== false) drop.acceptProposedAction()
        else drop.accepted = false
    }
    Rectangle {
        objectName: root.overlayName; anchors.fill: parent; anchors.margins: 14; radius: 18
        visible: root.containsDrag; color: Qt.alpha(Theme.bg, 0.96); border.color: Qt.alpha(Theme.accent, 0.6); border.width: 2
        Column {
            anchors.centerIn: parent; width: Math.max(0,parent.width-48); spacing: 15
            Image {
                id: mascot
                objectName: root.mascotName; anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(184,parent.width); height: width
                source: root.containsDrag ? root.mascotSource : ""
                asynchronous: true; cache: true; sourceSize: Qt.size(368,368); fillMode: Image.PreserveAspectFit; mipmap: true; smooth: false
                property real lift: 0
                transform: Translate { y: mascot.lift }
                SequentialAnimation on lift { running: root.containsDrag; loops: Animation.Infinite; NumberAnimation { from: 0; to: -5; duration: 850; easing.type: Easing.InOutSine } NumberAnimation { from: -5; to: 0; duration: 850; easing.type: Easing.InOutSine } }
            }
            Text { width: parent.width; text: I18n.t("松开以添加附件"); color: Theme.ink; font.pixelSize: Theme.font(14); horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap }
        }
    }
}
