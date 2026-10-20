import QtQuick

Item {
    id: root
    property bool running: true
    property color color: Theme.muted
    property int phase: 0
    implicitWidth: 15; implicitHeight: 15
    Timer { interval: 80; repeat: true; running: root.running && root.visible; onTriggered: root.phase = (root.phase + 1) % 12 }
    Repeater {
        model: 12
        Item {
            required property int index
            width: root.width; height: root.height
            rotation: index * 30
            Rectangle { anchors.horizontalCenter: parent.horizontalCenter; y: 0; width: 1.7; height: root.height * 0.25; radius: 1; color: root.color; opacity: 0.16 + ((index - root.phase + 12) % 12) / 11 * 0.84 }
        }
    }
}
