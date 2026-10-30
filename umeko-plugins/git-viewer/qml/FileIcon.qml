import QtQuick
import "../assets/file-icons.js" as FileIcons
Item {
    id: root
    property string fileName: ""
    property bool directory: false
    property bool expanded: false
    property bool dark: false
    property real uiScale: 1
    property color folderColor: dark ? "#c5c5c5" : "#616161"
    readonly property var asset: FileIcons.lookup(fileName, dark)
    width: 16 * uiScale; height: 16 * uiScale
    FontLoader { id: seti; source: "../assets/seti.ttf" }
    VsIcon { anchors.centerIn: parent; visible: root.directory; name: root.expanded ? "folder-opened" : "folder"; size: 16 * root.uiScale; color: root.folderColor }
    Text {
        anchors.centerIn: parent; visible: !root.directory
        width: parent.width; height: parent.height
        text: root.asset.glyph; color: root.asset.color
        font.family: seti.name; font.pixelSize: 24 * root.uiScale
        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
        renderType: Text.NativeRendering
    }
}
