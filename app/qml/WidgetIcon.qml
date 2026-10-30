import QtQuick
Item {
    id: root
    property var plugin: ({})
    property color color: Theme.muted
    readonly property string customSource: String(plugin.iconSource || "")
    implicitWidth: Theme.icon(20);implicitHeight: Theme.icon(20)
    Glyph {objectName:"widgetBuiltinGlyph";anchors.fill:parent;name:root.plugin.iconGlyph || "puzzle";color:root.color;visible:root.customSource.length===0 || custom.status!==Image.Ready}
    Image {
        id:custom;objectName:"widgetCustomImage";anchors.fill:parent;source:root.customSource;asynchronous:true
        sourceSize:Qt.size(64,64);fillMode:Image.PreserveAspectFit;visible:root.customSource.length>0 && status===Image.Ready
    }
}
