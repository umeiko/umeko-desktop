import QtQuick

Rectangle {
    id: root
    objectName: "chatLoadingOverlay"
    property bool loading: false
    property bool waitingForContent: false
    property var view
    property int frames: 0
    readonly property bool revealing: fade.running
    readonly property bool artworkLoaded: mascot.loaded
    signal revealed()
    color: Theme.bg; visible: loading || waitingForContent || fade.running
    opacity: 1
    function begin() { fade.stop(); waitingForContent = false; loading = true; opacity = 1 }
    function contentReady() { loading = false; frames = 0; waitingForContent = true }
    function cancel() { fade.stop(); loading = false; waitingForContent = false; opacity = 1 }
    FrameAnimation {
        running: root.waitingForContent
        onTriggered: {
            root.frames++
            if (root.frames >= 2 && root.view && !root.view.restoring) {
                root.view.forceLayout()
                fade.start()
                root.waitingForContent = false
            }
        }
    }
    NumberAnimation { id: fade; target: root; property: "opacity"; from: 1; to: 0; duration: 160; easing.type: Easing.OutCubic; onFinished: root.revealed() }
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onWheel: wheel => wheel.accepted = true }
    Column {
        anchors.centerIn: parent; anchors.verticalCenterOffset: -35; spacing: 20
        LoadingMascot { id: mascot; anchors.horizontalCenter: parent.horizontalCenter; running: root.visible }
        Text { anchors.horizontalCenter: parent.horizontalCenter; text: "正在打开聊天…"; color: Theme.muted; font.pixelSize: 13; textFormat: Text.PlainText }
    }
    Accessible.role: Accessible.Indicator; Accessible.name: "正在打开聊天"
}
