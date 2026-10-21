import QtQuick
import QtQuick.Controls

ScrollView {
    id: root
    readonly property var coordinator: {
        let item = parent
        while (item && typeof item.activateInlineScroll !== "function") item = item.parent
        return item
    }
    readonly property bool wheelActive: coordinator && coordinator.activeInlineScroll === root
    background: Item {
        MouseArea {
            parent: root; anchors.fill: parent; z: 100
            onPressed: mouse => { if (root.coordinator) root.coordinator.activateInlineScroll(root); mouse.accepted = false }
        }
    }

    WheelHandler {
        enabled: !root.wheelActive
        target: null
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
        onWheel: event => {
            if (!root.coordinator) { event.accepted = false; return }
            root.coordinator.scrollSettings(event.pixelDelta.y || event.angleDelta.y / 120 * 60)
            event.accepted = true
        }
    }
}
