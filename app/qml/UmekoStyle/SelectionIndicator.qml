import QtQuick
import QtQuick.Controls.impl
Item {
    id:root
    property int checkState:Qt.Unchecked
    property bool radio:false
    property bool round:false
    property bool pressed:false
    property bool hovered:false
    property bool focused:false
    property real uiScale:SurfaceStyle.uiScale
    readonly property bool selected:checkState!==Qt.Unchecked
    readonly property color tone:SurfaceStyle.colors.accent
    objectName:radio?"umekoRadioIndicator":"umekoCheckIndicator"
    implicitWidth:18*uiScale;implicitHeight:implicitWidth
    Rectangle {
        anchors.fill:parent;radius:root.radio || root.round?width/2:4*root.uiScale
        border.color:root.focused?root.tone:root.selected && !root.radio?Qt.darker(root.tone,1.15):SurfaceStyle.dark?"#59615d":"#b7bdc2"
        gradient:Gradient {
            GradientStop {position:0;color:root.selected && !root.radio?Qt.lighter(root.tone,root.pressed?0.94:1.22):SurfaceStyle.dark?"#202522":"#e5e7e8"}
            GradientStop {position:0.45;color:root.selected && !root.radio?root.tone:SurfaceStyle.dark?"#292f2b":"#f7f8f7"}
            GradientStop {position:1;color:root.selected && !root.radio?Qt.darker(root.tone,1.10):SurfaceStyle.dark?"#313833":"#ffffff"}
        }
        Rectangle {anchors.fill:parent;anchors.margins:1;radius:root.radio || root.round?width/2:3*root.uiScale;color:"transparent";border.color:root.selected && !root.radio?"#3affffff":SurfaceStyle.dark?"#18000000":"#b0ffffff"}
    }
    Rectangle {
        anchors.centerIn:parent;width:8*root.uiScale;height:width;radius:width/2
        visible:root.radio && root.selected;border.color:Qt.darker(root.tone,1.18)
        gradient:Gradient {GradientStop {position:0;color:Qt.lighter(root.tone,1.30)} GradientStop {position:1;color:Qt.darker(root.tone,1.08)}}
        Rectangle {anchors.top:parent.top;anchors.topMargin:1;anchors.horizontalCenter:parent.horizontalCenter;width:parent.width*0.5;height:1;color:"#65ffffff"}
    }
    IconImage {
        anchors.centerIn:parent;width:13*root.uiScale;height:width;sourceSize:Qt.size(32,32)
        source:"../../icons/check.svg";color:SurfaceStyle.dark?SurfaceStyle.colors.buttonText:"#ffffff"
        visible:!root.radio && root.checkState===Qt.Checked
    }
    Rectangle {anchors.centerIn:parent;width:8*root.uiScale;height:2*root.uiScale;radius:1;color:SurfaceStyle.dark?SurfaceStyle.colors.buttonText:"#ffffff";visible:!root.radio && root.checkState===Qt.PartiallyChecked}
}
