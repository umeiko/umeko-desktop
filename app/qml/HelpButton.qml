import QtQuick
import QtQuick.Controls

ToolButton {
    id: control
    property string help: ""
    property bool pinned: false
    property bool suppressed: false
    implicitWidth: 23; implicitHeight: 23
    hoverEnabled: true
    onClicked: { if (bubble.visible) { pinned = false; suppressed = true; bubble.close() } else { suppressed = false; pinned = true } }
    onHoveredChanged: { if (!hovered) { pinned = false; suppressed = false; bubble.close() } }
    onVisibleChanged: if (!visible) { pinned = false; suppressed = false; bubble.close() }
    Keys.onEscapePressed: pinned = false
    background: Rectangle { radius: 12; color: control.hovered || control.pinned ? Theme.hover : "transparent" }
    contentItem: Item { Glyph { name: "help"; width: 15; height: 15; anchors.centerIn: parent } }
    ToolTip {
        id: bubble
        objectName: "helpTooltip_" + control.objectName
        parent: control
        x: 0; y: control.height + 8
        margins: 12
        visible: control.visible && !control.suppressed && (control.hovered || control.pinned)
        delay: control.pinned ? 0 : 350
        timeout: 6000
        width: 320
        padding: 13
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onClosed: { control.pinned = false; if (control.hovered) control.suppressed = true }
        background: Rectangle { radius: 8; color: Theme.ink }
        contentItem: Text { text: control.help; color: Theme.bg; font.pixelSize: 11; wrapMode: Text.Wrap; lineHeight: 1.5 }
    }
}
