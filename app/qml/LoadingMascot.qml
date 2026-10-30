import QtQuick

Item {
    id: root
    width: 192; height: 192
    property bool running: visible
    readonly property bool nativeDecoration: !Character.has("loading") || portrait.failed
    readonly property bool loaded: portrait.status === Image.Ready
    // Keep the approved artwork intact. Only the baked loading marks are
    // covered and redrawn as lightweight native items sharing its palette.
    CharacterArt {
        id: portrait; objectName: "loadingPortrait"; anchors.fill: parent
        artwork: Character.asset("loading", "../icons/yanami-loading.png"); fallbackSource: "../icons/yanami-loading.png"; sourceSize: Qt.size(384,384)
        asynchronous: true; smooth: false; fillMode: Image.PreserveAspectFit
        SequentialAnimation on scale {
            running: root.running && !root.nativeDecoration; loops: Animation.Infinite
            NumberAnimation { from: 0.98; to: 1.02; duration: 850; easing.type: Easing.InOutSine }
            NumberAnimation { from: 1.02; to: 0.98; duration: 850; easing.type: Easing.InOutSine }
        }
    }
    Rectangle { visible: root.nativeDecoration; x: root.width * 960/1254; y: root.height * 148/1254; width: root.width * 160/1254; height: root.height * 178/1254; color: Theme.bg }
    Rectangle { visible: root.nativeDecoration; x: 0; y: root.height * 1160/1254; width: root.width; height: root.height * 94/1254; color: Theme.bg }
    Item {
        id: spinner; objectName: "loadingSpinner"
        visible: root.nativeDecoration
        x: root.width * 1040/1254 - width/2; y: root.height * 236/1254 - height/2
        width: 31; height: 31
        Repeater {
            model: ["#1446aa", "#245ac1", "#4b9ded", "#92d5ff", "#c0edff", "#ddf7ff"]
            Rectangle {
                required property int index
                required property string modelData
                width: 5; height: 5; radius: 0.8; color: modelData
                x: 13 + Math.cos((index * 45 - 135) * Math.PI / 180) * 11
                y: 13 + Math.sin((index * 45 - 135) * Math.PI / 180) * 11
            }
        }
        RotationAnimator { target: spinner; from: 0; to: 360; duration: 1100; loops: Animation.Infinite; running: root.running && root.nativeDecoration }
    }
    Row {
        visible: root.nativeDecoration
        x: root.width * 692/1254 - width/2; y: root.height * 1178/1254
        spacing: 4
        Repeater {
            model: 3
            Rectangle {
                id: dot; required property int index
                width: 5; height: 5; radius: 0.8; color: "#91d6ff"; opacity: 0.4
                SequentialAnimation {
                    running: root.running; loops: Animation.Infinite
                    PauseAnimation { duration: dot.index * 140 }
                    OpacityAnimator { target: dot; from: 0.4; to: 1; duration: 220 }
                    OpacityAnimator { target: dot; from: 1; to: 0.4; duration: 320 }
                    PauseAnimation { duration: (2 - dot.index) * 140 }
                }
            }
        }
    }
}
