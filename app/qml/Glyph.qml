import QtQuick
import QtQuick.Controls.impl
Item {
    id: root
    property string name: "chat"
    property color color: Theme.muted
    implicitWidth: 20; implicitHeight: 20
    width: 20; height: 20
    opacity: enabled ? 0.9 : 0.4
    IconImage {
        anchors.fill: parent
        source: parent.name === "" ? "" : "../icons/" + parent.name + ".svg"
        sourceSize: Qt.size(64, 64)
        color: root.color
        fillMode: Image.PreserveAspectFit
    }
}
