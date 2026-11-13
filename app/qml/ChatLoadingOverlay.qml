import QtQuick
import "loading-tips.js" as LoadingTips

Rectangle {
    id: root
    objectName: "chatLoadingOverlay"
    property bool loading: false
    property bool waitingForContent: false
    // Loads that finish within showDelay never draw the cover; the overlay
    // still takes input so the previous chat is not edited mid-switch.
    property bool delayElapsed: false
    property int showDelay: 150
    // True while the new conversation is still laid out behind the scenes.
    property bool contentHeld: false
    property var view
    property int frames: 0
    property int tipIndex: -1
    readonly property var tips: Character.scene("loading.tips", LoadingTips.items)
    readonly property string tip: tipIndex >= 0 && tips.length ? tips[tipIndex % tips.length] : ""
    readonly property bool shown: visible && delayElapsed
    readonly property bool artworkLoaded: mascot.loaded
    signal revealed()
    color: Theme.bg; visible: loading || waitingForContent
    opacity: delayElapsed ? 1 : 0
    function begin() {
        tipIndex = LoadingTips.choose(tipIndex, undefined, tips)
        waitingForContent = false; loading = true
        if (!delayElapsed) delayTimer.restart()
    }
    function contentReady() { loading = false; frames = 0; waitingForContent = true }
    function finish() { delayTimer.stop(); waitingForContent = false; delayElapsed = false; revealed() }
    function cancel() { delayTimer.stop(); loading = false; waitingForContent = false; delayElapsed = false }
    Timer { id: delayTimer; interval: root.showDelay; onTriggered: if (root.loading || root.waitingForContent) root.delayElapsed = true }
    FrameAnimation {
        running: root.waitingForContent
        onTriggered: {
            root.frames++
            if (root.frames >= 2 && !root.contentHeld && (!root.view || !root.view.restoring)) {
                if (root.view) root.view.forceLayout()
                // The finished conversation replaces the cover in one frame.
                root.finish()
            }
        }
    }
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onWheel: wheel => wheel.accepted = true }
    Column {
        anchors.centerIn: parent; anchors.verticalCenterOffset: -35; spacing: 20
        width: Math.max(0,Math.min(parent.width-64,560))
        LoadingMascot { id: mascot; anchors.horizontalCenter: parent.horizontalCenter; running: root.shown }
        Text { font.family: Theme.fontFamily; anchors.horizontalCenter: parent.horizontalCenter; text: Character.scene("loading.title", ""); color: Theme.muted; font.pixelSize: Theme.font(13, visible); textFormat: Text.PlainText }
        Text { font.family: Theme.fontFamily; objectName: "chatLoadingTip"; width: parent.width; text: root.tip; textFormat: Text.PlainText; color: Theme.muted; opacity: 0.85; font.pixelSize: Theme.font(12, visible); wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter; lineHeight: 1.5 }
    }
    Accessible.role: Accessible.Indicator; Accessible.name: I18n.t("正在打开聊天")
}
