import QtQuick
import QtQuick.Controls

ToolButton {
    id: control
    property string help: ""
    property bool suppressed: false
    readonly property bool pinned: bubble.visible
    implicitWidth: 23; implicitHeight: 23
    hoverEnabled: true
    function updateDismissal() {
        if (!bubble.visible || hovered || bubbleHover.hovered || explanation.selectionStart !== explanation.selectionEnd) closeTimer.stop()
        else closeTimer.restart()
    }
    onClicked: { openTimer.stop(); if (bubble.visible) bubble.close(); else { suppressed = false; bubble.open() } }
    onHoveredChanged: {
        if (hovered && !suppressed && !bubble.visible) openTimer.restart()
        if (!hovered) { openTimer.stop(); suppressed = false }
        updateDismissal()
    }
    onVisibleChanged: if (!visible) { openTimer.stop(); closeTimer.stop(); bubble.close() }
    background: Rectangle { radius: 12; color: control.hovered || bubble.visible ? Theme.hover : "transparent" }
    contentItem: Item { Glyph { name: "help"; width: 15; height: 15; anchors.centerIn: parent } }
    Timer { id: openTimer; interval: 350; onTriggered: if (control.hovered && !control.suppressed) bubble.open() }
    Timer { id: closeTimer; interval: 3000; onTriggered: if (!control.hovered && !bubbleHover.hovered && explanation.selectionStart === explanation.selectionEnd) bubble.close() }
    ToolTip {
        id: bubble
        objectName: "helpTooltip_" + control.objectName
        parent: control
        x: 0; y: control.height + 8
        margins: 12; width: 320; padding: 13; timeout: -1
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
        onOpened: control.updateDismissal()
        onClosed: { openTimer.stop(); closeTimer.stop(); explanation.deselect(); control.suppressed = control.hovered }
        background: Rectangle { radius: 8; color: Theme.ink }
        contentItem: TextArea {
            id: explanation; objectName: "helpText_" + control.objectName
            text: control.help; color: Theme.bg; font.pixelSize: 11; wrapMode: TextEdit.Wrap
            readOnly: true; selectByMouse: true; textFormat: TextEdit.PlainText; padding: 0
            selectionColor: Theme.accent; selectedTextColor: "white"
            background: null
            onSelectionStartChanged: control.updateDismissal()
            onSelectionEndChanged: control.updateDismissal()
            HoverHandler { id: bubbleHover; onHoveredChanged: control.updateDismissal() }
        }
    }
}
