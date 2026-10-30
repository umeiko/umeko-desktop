import QtQuick
Rectangle {
    required property var colors
    property string iconName: "package"
    width: 40; height: width; radius: width/5
    color: colors.accentBg
    Image {
        anchors.fill: parent
        source: "assets/extensions/" + (["codemode","tool-search","mcp","chatbox","pi-commands","umeko-control","background-jobs","subagents"].indexOf(parent.iconName)>=0 ? parent.iconName : "package") + ".svg"
        fillMode: Image.PreserveAspectFit
        sourceSize.width: parent.width*2
        sourceSize.height: parent.height*2
    }
}
