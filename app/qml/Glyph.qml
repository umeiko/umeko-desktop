import QtQuick
import QtQuick.Controls.impl
Item {
    id: root
    property string name: "chat"
    property color color: Theme.muted
    implicitWidth: Theme.icon(20); implicitHeight: Theme.icon(20)
    width: implicitWidth; height: implicitHeight
    opacity: enabled ? 0.9 : 0.4
    IconImage {
        anchors.fill: parent
        source: parent.name === "" ? "" : "../icons/" + parent.name + ".svg"
        sourceSize: Qt.size(64, 64)
        color: root.color
        fillMode: Image.PreserveAspectFit
    }
}
