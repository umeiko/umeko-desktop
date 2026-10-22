import QtQuick
import "assistant-avatars.js" as Avatars

Image {
    property string messageKey: ""
    readonly property int variant: Avatars.choose(messageKey)
    readonly property bool loaded: status === Image.Ready
    width: Theme.icon(40); height: width
    source: "../icons/avatars/" + ["smile", "wink", "happy"][variant] + ".webp"
    sourceSize: Qt.size(96, 96)
    fillMode: Image.PreserveAspectFit
    smooth: false; mipmap: false
    Accessible.ignored: true
}
