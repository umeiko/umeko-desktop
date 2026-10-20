import QtQuick
import QtQuick.Window

Item {
    id: root
    objectName: "windowResizeHandles"
    required property var targetWindow
    readonly property int edgeSize: 6
    readonly property int cornerSize: 18
    enabled: targetWindow.visibility !== Window.Maximized && targetWindow.visibility !== Window.FullScreen

    // Disjoint corner and edge regions keep diagonal drags from hitting a single edge.
    Repeater {
        model: [
            {name:"left", edges:Qt.LeftEdge, cursor:Qt.SizeHorCursor},
            {name:"right", edges:Qt.RightEdge, cursor:Qt.SizeHorCursor},
            {name:"top", edges:Qt.TopEdge, cursor:Qt.SizeVerCursor},
            {name:"bottom", edges:Qt.BottomEdge, cursor:Qt.SizeVerCursor},
            {name:"topLeft", edges:Qt.TopEdge | Qt.LeftEdge, cursor:Qt.SizeFDiagCursor},
            {name:"topRight", edges:Qt.TopEdge | Qt.RightEdge, cursor:Qt.SizeBDiagCursor},
            {name:"bottomLeft", edges:Qt.BottomEdge | Qt.LeftEdge, cursor:Qt.SizeBDiagCursor},
            {name:"bottomRight", edges:Qt.BottomEdge | Qt.RightEdge, cursor:Qt.SizeFDiagCursor}
        ]
        MouseArea {
            required property var modelData
            objectName: "windowResize_" + modelData.name
            readonly property bool horizontalEdge: (modelData.edges & (Qt.LeftEdge | Qt.RightEdge)) !== 0
            readonly property bool verticalEdge: (modelData.edges & (Qt.TopEdge | Qt.BottomEdge)) !== 0
            readonly property bool corner: horizontalEdge && verticalEdge
            width: corner ? root.cornerSize : horizontalEdge ? root.edgeSize : root.width - 2 * root.cornerSize
            height: corner ? root.cornerSize : horizontalEdge ? root.height - 2 * root.cornerSize : root.edgeSize
            x: horizontalEdge ? ((modelData.edges & Qt.RightEdge) ? root.width - width : 0) : root.cornerSize
            y: verticalEdge ? ((modelData.edges & Qt.BottomEdge) ? root.height - height : 0) : root.cornerSize
            hoverEnabled: true
            acceptedButtons: Qt.LeftButton
            preventStealing: true
            cursorShape: modelData.cursor
            onPressed: root.targetWindow.startSystemResize(modelData.edges)
        }
    }
}
