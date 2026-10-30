import QtQuick

FocusScope {
    id: root
    property var selectionController: null
    property url portraitSource: Character.asset("reply", "../icons/yanami-pixel.png")
    property string interactionLabel: Character.id === "yanami" ? I18n.t("八奈见：点击互动，连续点击或长按有彩蛋") : Character.style.name
    property var tapLines: Character.scene("reply.tap", [])
    property string celebrationLine: Character.scene("reply.celebration", "")
    property real captionMaxWidth: parent ? Math.max(1,parent.width-x-width-8) : 240
    readonly property bool loaded: portrait.status === Image.Ready
    readonly property bool animating: wiggle.running || burst.running
    property string reaction: ""
    property bool ready: false
    Component.onCompleted: ready = true
    property int combo: 0
    property real tilt: 0
    property real progress: 1
    width: 56; height: Math.max(width, bubble.visible ? bubble.height : 0)
    smooth: false
    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: interactionLabel
    Accessible.onPressAction: tap()
    function tap() {
        combo++; comboTimer.restart()
        reaction = tapLines.length ? tapLines[Math.floor(Math.random() * tapLines.length)] : ""
        if (combo >= 3) celebrate()
        else { wiggle.restart(); reactionTimer.restart() }
    }
    function celebrate() { combo = 0; reaction = celebrationLine; wiggle.restart(); burst.restart(); reactionTimer.restart() }
    function say(text) { combo = 0; comboTimer.stop(); reaction = text; wiggle.restart(); reactionTimer.restart() }
    function reset() { wiggle.stop(); burst.stop(); reactionTimer.stop(); comboTimer.stop(); combo = 0; reaction = ""; tilt = 0; progress = 1 }
    onVisibleChanged: if (ready && !visible) reset()
    onPortraitSourceChanged: if (ready) reset()
    SequentialAnimation {
        id: wiggle
        NumberAnimation { target: root; property: "tilt"; to: -14; duration: 90; easing.type: Easing.OutCubic }
        NumberAnimation { target: root; property: "tilt"; to: 11; duration: 130 }
        NumberAnimation { target: root; property: "tilt"; to: -5; duration: 110 }
        NumberAnimation { target: root; property: "tilt"; to: 0; duration: 180; easing.type: Easing.OutBack }
    }
    NumberAnimation { id: burst; target: root; property: "progress"; from: 0; to: 1; duration: 850; easing.type: Easing.OutQuad }
    Timer { id: reactionTimer; interval: 1800; onTriggered: root.reaction = "" }
    Timer { id: comboTimer; interval: 900; onTriggered: root.combo = 0 }
    CharacterArt {
        id: portrait; anchors.centerIn: parent; width: root.width; height: width; artwork: root.portraitSource; fallbackSource: "../icons/yanami-pixel.png"; sourceSize: Qt.size(224,224)
        fillMode: Image.PreserveAspectFit; smooth: false; mipmap: false; rotation: root.tilt
        scale: pointer.pressed ? 0.87 : pointer.interactionHovered || root.activeFocus ? 1.08 : 1
        Behavior on scale { SpringAnimation { spring: 4; damping: 0.25; epsilon: 0.005 } }
    }
    Repeater {
        model: 5
        Glyph {
            required property int index
            readonly property real angle: (index * 72 - 110) * Math.PI / 180
            visible: burst.running; name: "spark"; color: Theme.accent; width: Theme.icon(11); height: Theme.icon(11)
            x: root.width / 2 + Math.cos(angle) * (20 + root.progress * 32)
            y: root.height / 2 + Math.sin(angle) * (20 + root.progress * 28) - root.progress * 12
            opacity: 1 - root.progress; rotation: root.progress * 60
        }
    }
    Rectangle {
        id: bubble; objectName: "replyMascotBubble"
        x: root.width + 8; anchors.verticalCenter: parent.verticalCenter
        width: Math.max(1,Math.min(caption.implicitWidth + 20,root.captionMaxWidth)); height: Math.max(30,caption.implicitHeight+12); radius: 9
        visible: root.reaction.length > 0; color: Theme.surface; border.color: Theme.line
        Text { id: caption; anchors.centerIn: parent; width: Math.max(0,parent.width-20); text: root.reaction; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Theme.ink; font.pixelSize: Theme.font(11) }
    }
    ChatHitArea {
        id: pointer; objectName: "replyMascotPointer"; anchors.fill: parent; selectionController: root.selectionController
        property bool held: false
        pressAndHoldInterval: 650
        onPressed: { held = false; root.forceActiveFocus() }
        onPressAndHold: { held = true; root.celebrate() }
        onClicked: if (!held) root.tap()
    }
    Keys.onPressed: event => { if ((event.key === Qt.Key_Space || event.key === Qt.Key_Return) && !event.isAutoRepeat) { tap(); event.accepted = true } }
}
