import QtQuick

FocusScope {
    id: root
    objectName: "welcomeMascot"
    width: 210; height: 210
    property int portraitIndex: 0
    readonly property bool loaded: portrait.status === Image.Ready
    property string reactionText: ""
    property bool dragging: false
    property bool resetting: false
    property bool ready: false
    property int combo: 0
    property real offsetX: 0
    property real offsetY: 0
    property real tilt: 0
    property real squashX: 1
    property real squashY: 1
    property real hop: 0
    property real burstProgress: 1
    readonly property bool celebrating: burst.running
    readonly property bool animating: jump.running || burst.running || springX.running || springY.running || springTilt.running || springSquashX.running || springSquashY.running
    readonly property var tapLines: Character.scene("welcome.tap", [])
    signal interaction(string kind)
    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: Character.id === "yanami" ? I18n.t("八奈见：点击互动，拖拽回弹，长按有彩蛋") : Character.style.name
    Accessible.onPressAction: tap()
    Component.onCompleted: ready = true
    onVisibleChanged: if (ready && !visible) reset()

    function say(text) { reactionText = text; reactionTimer.restart() }
    function pressPose() {
        jump.stop(); hop = 0
        squashX = 1.08; squashY = 0.91; tilt = -4
    }
    function returnHome() {
        dragging = false
        offsetX = 0; offsetY = 0; tilt = 0; squashX = 1; squashY = 1
    }
    function tap() {
        returnHome()
        interaction("tap")
        combo++
        comboTimer.restart()
        if (combo >= 3) { celebrate(); return }
        say(tapLines[Math.floor(Math.random() * tapLines.length)])
        jump.restart()
    }
    function celebrate() {
        combo = 0; comboTimer.stop()
        say(Character.scene("welcome.celebration", ""))
        returnHome(); jump.restart(); burst.restart()
    }
    function reset() {
        resetting = true
        pointer.validPress = false
        jump.stop(); burst.stop(); reactionTimer.stop(); comboTimer.stop()
        combo = 0; reactionText = ""; hop = 0; burstProgress = 1
        returnHome()
        resetting = false
    }
    Behavior on offsetX { enabled: root.visible && !root.dragging && !root.resetting; SpringAnimation { id: springX; spring: 3; damping: 0.3; epsilon: 0.1 } }
    Behavior on offsetY { enabled: root.visible && !root.dragging && !root.resetting; SpringAnimation { id: springY; spring: 3; damping: 0.3; epsilon: 0.1 } }
    Behavior on tilt { enabled: root.visible && !root.dragging && !root.resetting; SpringAnimation { id: springTilt; spring: 3; damping: 0.3; epsilon: 0.1 } }
    Behavior on squashX { enabled: root.visible && !root.dragging && !root.resetting; SpringAnimation { id: springSquashX; spring: 3; damping: 0.3; epsilon: 0.005 } }
    Behavior on squashY { enabled: root.visible && !root.dragging && !root.resetting; SpringAnimation { id: springSquashY; spring: 3; damping: 0.3; epsilon: 0.005 } }
    SequentialAnimation {
        id: jump
        NumberAnimation { target: root; property: "hop"; to: -18; duration: 110; easing.type: Easing.OutCubic }
        NumberAnimation { target: root; property: "hop"; to: 0; duration: 420; easing.type: Easing.OutBounce }
    }
    NumberAnimation { id: burst; target: root; property: "burstProgress"; from: 0; to: 1; duration: 1150; easing.type: Easing.OutQuad }
    Timer { id: reactionTimer; interval: 3200; onTriggered: root.reactionText = "" }
    Timer { id: comboTimer; interval: 1000; onTriggered: root.combo = 0 }

    Rectangle { anchors.fill: parent; radius: width / 2; color: "transparent"; border.color: Theme.accent; opacity: 0.4; visible: root.activeFocus }
    CharacterArt {
        id: portrait
        x: root.offsetX; y: root.offsetY + root.hop; width: root.width; height: root.height
        fallbackSource: "../icons/portraits/" + (root.portraitIndex + 1).toString().padStart(2, "0") + ".png"
        artwork: Character.asset("welcome", fallbackSource)
        sourceSize: Qt.size(420,420); fillMode: Image.PreserveAspectFit; mipmap: true
        transform: [
            Rotation { origin.x: portrait.width / 2; origin.y: portrait.height * 0.72; angle: root.tilt },
            Scale { origin.x: portrait.width / 2; origin.y: portrait.height * 0.72; xScale: root.squashX; yScale: root.squashY }
        ]
    }
    Repeater {
        model: 6
        Glyph {
            required property int index
            readonly property real angle: (index * 60 - 110) * Math.PI / 180
            name: "spark"; width: Theme.icon(17); height: Theme.icon(17)
            visible: root.celebrating
            x: root.width / 2 + Math.cos(angle) * (78 + root.burstProgress * 44) - width / 2
            y: root.height * 0.4 + Math.sin(angle) * (65 + root.burstProgress * 28) - root.burstProgress * 26
            opacity: 0.9 * (1 - root.burstProgress); rotation: root.burstProgress * 55
            scale: 0.7 + root.burstProgress * 0.5
        }
    }
    Rectangle {
        objectName: "welcomeCookie"
        width: 32; height: 32; radius: 16; color: "#f2c47a"; border.color: "#bb8447"; border.width: 1.5
        visible: root.celebrating
        x: root.width / 2 - width / 2; y: -10 - root.burstProgress * 46
        rotation: -12 + root.burstProgress * 35; opacity: 1 - root.burstProgress
        Repeater {
            model: [{x:9,y:8},{x:21,y:11},{x:14,y:18},{x:7,y:23},{x:22,y:24}]
            Rectangle { required property var modelData; x: modelData.x; y: modelData.y; width: 3.5; height: 3.5; radius: 1.5; color: "#99653b" }
        }
    }
    MouseArea {
        id: pointer; objectName: "welcomeMascotPointer"; anchors.fill: parent
        acceptedButtons: Qt.LeftButton; hoverEnabled: true; preventStealing: true
        pressAndHoldInterval: 650
        cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
        property point start: Qt.point(0, 0)
        property bool held: false
        property bool validPress: false
        onPressed: mouse => { start = Qt.point(mouse.x, mouse.y); held = false; validPress = true; root.dragging = false; root.pressPose() }
        onPositionChanged: mouse => {
            if (!pressed || held || !validPress) return
            const dx = mouse.x - start.x, dy = mouse.y - start.y
            if (Math.abs(dx) + Math.abs(dy) > 8) root.dragging = true
            if (root.dragging) {
                root.offsetX = Math.max(-72, Math.min(72, dx))
                root.offsetY = Math.max(-48, Math.min(12, dy))
                root.tilt = Math.max(-15, Math.min(15, dx / 5))
                root.squashX = 1.03; root.squashY = 0.97
            }
        }
        onPressAndHold: {
            if (root.dragging || !validPress) return
            held = true; root.interaction("hold"); root.celebrate()
        }
        onReleased: {
            if (!validPress) { root.returnHome(); return }
            validPress = false
            if (root.dragging) { root.interaction("drag"); root.say(Character.scene("welcome.dragReturn", "")); root.returnHome() }
            else if (held) root.returnHome()
            else root.tap()
        }
        onCanceled: { validPress = false; root.returnHome() }
    }
    Keys.onPressed: event => {
        if ([Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter].indexOf(event.key) < 0) return
        event.accepted = true
        if (!event.isAutoRepeat) root.pressPose()
    }
    Keys.onReleased: event => {
        if ([Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter].indexOf(event.key) < 0) return
        event.accepted = true
        if (!event.isAutoRepeat) root.tap()
    }
}
