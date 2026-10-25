import QtQuick

MouseArea {
    id: root
    property var selectionController: null
    property int interactionPriority: 0
    readonly property bool interactionHovered: selectionController ? selectionController.hoveredTarget === root : containsMouse
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    Component.onCompleted: if (selectionController) selectionController.attachInteraction(root)
    Component.onDestruction: if (selectionController) selectionController.detachInteraction(root)
}
