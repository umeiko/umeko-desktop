import QtQuick
import QtQuick.Controls
Button {
    id: control
    property string glyph: ""
    property bool primary: false
    property bool quiet: false
    property bool destructive: false
    property string hint: ""
    property var selectionController: null
    property int interactionPriority: 10
    readonly property bool interactionHovered: hovered || !!selectionController && selectionController.hoveredTarget === control
    Component.onCompleted: if (selectionController) selectionController.attachInteraction(control)
    Component.onDestruction: if (selectionController) selectionController.detachInteraction(control)
    HoverHandler { cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }
    implicitHeight: Math.max(38, contents.implicitHeight + 16)
    implicitWidth: Math.max(38, contents.implicitWidth + (text.length ? 28 : 18))
    padding: 0
    hoverEnabled: true
    opacity: enabled ? 1 : 0.45
    scale: down ? 0.97 : 1
    Behavior on scale { NumberAnimation { duration: 110; easing.type: Easing.OutCubic } }
    background: Rectangle {
        radius: 8
        color: control.primary ? (control.interactionHovered ? Qt.lighter(Theme.button, 1.12) : Theme.button) : control.down ? Theme.accentBg : control.interactionHovered ? Theme.hover : control.quiet ? "transparent" : Theme.surface
        border.color: control.primary || control.quiet ? "transparent" : Theme.line
        Behavior on color { ColorAnimation { duration: 140 } }
    }
    contentItem: Item {
        Row {
            id: contents
            anchors.centerIn: parent
            spacing: 8
            Glyph { name: control.glyph; color: control.primary ? Theme.buttonText : control.destructive ? Theme.danger : control.interactionHovered ? Theme.accent : Theme.muted; visible: name !== ""; width: 17; height: 17; anchors.verticalCenter: parent.verticalCenter }
            Text { text: control.text; visible: text.length > 0; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: Theme.font(12)
                color: control.primary ? Theme.buttonText : control.destructive ? Theme.danger : Theme.ink }
        }
    }
    HoverTip { active: control.interactionHovered && !control.down; text: control.hint }
}
