import QtQuick
Item {
    property string name: "chat"
    implicitWidth: 20; implicitHeight: 20
    width: 20; height: 20
    opacity: enabled ? 0.9 : 0.4
    Image {
        anchors.fill: parent
        source: parent.name === "" ? "" : "../icons/" + parent.name + ".svg"
        sourceSize: Qt.size(64, 64)
        fillMode: Image.PreserveAspectFit
    }
}
