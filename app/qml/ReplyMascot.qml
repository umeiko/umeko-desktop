import QtQuick

FocusScope {
    id: root
    property var selectionController: null
    readonly property bool loaded: portrait.status === Image.Ready
    readonly property bool animating: wiggle.running || burst.running
    property string reaction: ""
    property bool ready: false
    Component.onCompleted: ready = true
    property int combo: 0
    property real tilt: 0
    property real progress: 1
    width: 56; height: 56
    smooth: false
    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: I18n.t("八奈见：点击互动，连续点击或长按有彩蛋")
    Accessible.onPressAction: tap()
    function tap() {
        combo++; comboTimer.restart()
        reaction = [I18n.t("我在呢～"), I18n.t("点心分我一半？"), I18n.t("好啦，继续陪你！")][Math.floor(Math.random() * 3)]
        if (combo >= 3) celebrate()
        else { wiggle.restart(); reactionTimer.restart() }
    }
    function celebrate() { combo = 0; reaction = I18n.t("发现一块小饼干！🍪"); wiggle.restart(); burst.restart(); reactionTimer.restart() }
    function reset() { wiggle.stop(); burst.stop(); reactionTimer.stop(); comboTimer.stop(); combo = 0; reaction = ""; tilt = 0; progress = 1 }
    onVisibleChanged: if (ready && !visible) reset()
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
    Image {
        id: portrait; anchors.fill: parent; source: "../icons/yanami-pixel.png"; sourceSize: Qt.size(112,112)
        fillMode: Image.PreserveAspectFit; smooth: false; mipmap: false; rotation: root.tilt
        scale: pointer.pressed ? 0.87 : pointer.interactionHovered || root.activeFocus ? 1.08 : 1
        Behavior on scale { SpringAnimation { spring: 4; damping: 0.25; epsilon: 0.005 } }
    }
    Repeater {
        model: 5
        Glyph {
            required property int index
            readonly property real angle: (index * 72 - 110) * Math.PI / 180
            visible: burst.running; name: "spark"; color: Theme.accent; width: 11; height: 11
            x: root.width / 2 + Math.cos(angle) * (20 + root.progress * 32)
            y: root.height / 2 + Math.sin(angle) * (20 + root.progress * 28) - root.progress * 12
            opacity: 1 - root.progress; rotation: root.progress * 60
        }
    }
    Rectangle {
        x: root.width + 8; anchors.verticalCenter: parent.verticalCenter
        width: caption.implicitWidth + 20; height: 30; radius: 9
        visible: root.reaction.length > 0; color: Theme.surface; border.color: Theme.line
        Text { id: caption; anchors.centerIn: parent; text: root.reaction; color: Theme.ink; font.pixelSize: Theme.font(11) }
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
