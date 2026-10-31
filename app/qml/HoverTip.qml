import QtQuick
import QtQuick.Controls
import QtQuick.Window

// A visual hint has no Popup grab. Its overlay is owned by this control even
// while visually parented to the window, so recycled controls cannot leak it.
Item {
    id: root
    property bool active: false
    property string heading: ""
    property string text: ""
    property int delay: 500
    property int maximumWidth: 360
    readonly property Item anchorItem: parent
    property Item bubble: null
    property bool shown: false
    readonly property Item contentItem: bubble ? bubble.contentItem : null
    readonly property bool wanted: active && text.length > 0 && anchorItem && anchorItem.visible && anchorItem.enabled && anchorItem.Window.window && !anchorItem.Window.window.mediaOverlayActive
    visible: shown || (bubble && bubble.opacity > 0)
    width: 0; height: 0
    Component.onCompleted: updateVisibility()
    onWantedChanged: updateVisibility()
    function updateVisibility() {
        if (wanted) { if (!shown) opening.restart() }
        else { opening.stop(); shown = false }
    }
    function positionHint() {
        if (!anchorItem || !bubble || !bubble.parent) return
        const point = anchorItem.mapToItem(bubble.parent, anchorItem.width / 2, 0)
        bubble.x = Math.max(12, Math.min(bubble.parent.width - bubble.width - 12, point.x - bubble.width / 2))
        const above = point.y - bubble.height - 8
        bubble.y = Math.max(12, Math.min(bubble.parent.height - bubble.height - 12, above >= 12 ? above : point.y + anchorItem.height + 8))
    }
    Timer {
        id: opening; interval: root.delay
        onTriggered: if (root.wanted) {
            if (!root.bubble) root.bubble = picture.createObject(root)
            root.bubble.parent = root.Overlay.overlay
            root.positionHint()
            root.shown = true
        }
    }
    Component {
        id: picture
        Item {
            id: visual
            readonly property Item contentItem: content
            z: 10000
            visible: root.visible; opacity: root.shown ? 1 : 0
            width: Math.min(root.maximumWidth, root.Overlay.overlay ? Math.max(24, root.Overlay.overlay.width - 24) : 360, Math.max(120, details.implicitWidth + 24))
            height: content.implicitHeight + 24
            onWidthChanged: if (root.shown) root.positionHint()
            onHeightChanged: if (root.shown) root.positionHint()
            Behavior on opacity { NumberAnimation { duration: root.shown ? 100 : 80 } }
            Item {
                anchors.fill: parent
                Repeater {
                    model: 12
                    Rectangle {
                        required property int index
                        readonly property real spread: (index + 1) * 0.4
                        x: -spread; y: 3 - spread
                        width: parent.width + spread * 2; height: parent.height + spread * 2
                        radius: 9 + spread; color: "#02000000"
                    }
                }
                Rectangle { anchors.fill: parent; radius: 9; color: Theme.surface; border.color: Theme.line }
            }
            Column {
                id: content
                objectName: "hoverTipContent_" + root.objectName
                x: 12; y: 12; width: visual.width - 24; spacing: 5
                Text { font.family: Theme.fontFamily;
                    width: parent.width; visible: root.heading.length > 0
                    text: root.heading; textFormat: Text.PlainText
                    color: Theme.ink; font.pixelSize: Theme.font(12); font.weight: Font.DemiBold
                    elide: Text.ElideMiddle
                }
                Text { font.family: Theme.fontFamily;
                    id: details
                    width: parent.width; text: root.text; textFormat: Text.PlainText
                    color: Theme.muted; font.pixelSize: Theme.font(11); lineHeight: 1.3
                    wrapMode: Text.WrapAnywhere; maximumLineCount: 6; elide: Text.ElideRight
                }
            }
        }
    }
}
