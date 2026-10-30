import QtQuick
import "../assets/codicons.js" as Codicons
Text {
    property string name: "file"
    property real size: 16
    readonly property bool fontReady: iconFont.status === FontLoader.Ready
    width: size; height: size
    text: Codicons.glyph(name)
    font.family: iconFont.name; font.pixelSize: size
    horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
    renderType: Text.NativeRendering
    FontLoader { id: iconFont; source: "../assets/codicon.ttf" }
}
