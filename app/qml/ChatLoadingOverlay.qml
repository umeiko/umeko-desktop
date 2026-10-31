import QtQuick
import "loading-tips.js" as LoadingTips

Rectangle {
    id: root
    objectName: "chatLoadingOverlay"
    property bool loading: false
    property bool waitingForContent: false
    property var view
    property int frames: 0
    property int tipIndex: -1
    readonly property var tips: Character.scene("loading.tips", LoadingTips.items)
    readonly property string tip: tipIndex >= 0 && tips.length ? tips[tipIndex % tips.length] : ""
    readonly property bool revealing: fade.running
    readonly property bool artworkLoaded: mascot.loaded
    signal revealed()
    color: Theme.bg; visible: loading || waitingForContent || fade.running
    opacity: 1
    function begin() { tipIndex = LoadingTips.choose(tipIndex, undefined, tips); fade.stop(); waitingForContent = false; loading = true; opacity = 1 }
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
        width: Math.max(0,Math.min(parent.width-64,560))
        LoadingMascot { id: mascot; anchors.horizontalCenter: parent.horizontalCenter; running: root.visible }
        Text { font.family: Theme.fontFamily; anchors.horizontalCenter: parent.horizontalCenter; text: Character.scene("loading.title", ""); color: Theme.muted; font.pixelSize: Theme.font(13, visible); textFormat: Text.PlainText }
        Text { font.family: Theme.fontFamily; objectName: "chatLoadingTip"; width: parent.width; text: root.tip; textFormat: Text.PlainText; color: Theme.muted; opacity: 0.85; font.pixelSize: Theme.font(12, visible); wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter; lineHeight: 1.5 }
    }
    Accessible.role: Accessible.Indicator; Accessible.name: I18n.t("正在打开聊天")
}
