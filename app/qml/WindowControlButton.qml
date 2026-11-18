import QtQuick
import QtQuick.Controls
AbstractButton {
    id:control
    property string operation:"close"
    property bool maximized:false
    property string hint:""
    implicitWidth:Theme.control(32);implicitHeight:Theme.control(30)
    hoverEnabled:true;focusPolicy:Qt.TabFocus
    Accessible.name:hint
    HoverHandler {cursorShape:control.enabled?Qt.PointingHandCursor:Qt.ArrowCursor}
    background:Item {
        Rectangle {anchors.centerIn:parent;anchors.verticalCenterOffset:1;width:Theme.control(22);height:width;radius:width/2;color:Theme.dark?"#30000000":"#12000000";opacity:control.down?0:1}
        Rectangle {
            id:cap;anchors.centerIn:parent;anchors.verticalCenterOffset:control.down?1:0
            width:Theme.control(22);height:width;radius:width/2
            readonly property color tone:control.operation==="close"?(control.hovered?"#ed756a":"#e06d65"):Theme.dark?"#3c4540":"#f6f7f6"
            border.color:control.visualFocus?Theme.accent:control.operation==="close"?"#bf5b55":Theme.dark?"#606b64":"#cdd1d2"
            gradient:Gradient {GradientStop {position:0;color:control.down?Qt.darker(cap.tone,1.14):Qt.lighter(cap.tone,1.10)} GradientStop {position:1;color:control.down?cap.tone:Qt.darker(cap.tone,1.05)}}
            Rectangle {anchors.fill:parent;anchors.margins:1;radius:width/2;color:"transparent";border.color:control.operation==="close"?"#35ffffff":Theme.dark?"#15ffffff":"#e0ffffff";opacity:control.down?0.3:1}
        }
    }
    contentItem:Item {
        readonly property color ink:control.operation==="close"?"#ffffff":Theme.dark?"#c9d2cb":"#81898a"
        Item {
            anchors.centerIn:parent;anchors.verticalCenterOffset:control.down?1:0
            width:Theme.icon(10);height:width
            Rectangle {anchors.centerIn:parent;width:parent.width;height:Math.max(1,Theme.fontScale);radius:height/2;color:parent.parent.ink;visible:control.operation==="minimize"}
            Rectangle {anchors.centerIn:parent;width:parent.width;height:Math.max(1.2,Theme.fontScale);radius:height/2;color:parent.parent.ink;rotation:45;visible:control.operation==="close";antialiasing:true}
            Rectangle {anchors.centerIn:parent;width:parent.width;height:Math.max(1.2,Theme.fontScale);radius:height/2;color:parent.parent.ink;rotation:-45;visible:control.operation==="close";antialiasing:true}
            Rectangle {x:control.maximized?2:1;y:0;width:parent.width-2;height:width;radius:1;color:"transparent";border.color:parent.parent.ink;visible:control.operation==="maximize"}
            Rectangle {x:0;y:3;width:parent.width-3;height:width;radius:1;color:Theme.bg;border.color:parent.parent.ink;visible:control.operation==="maximize" && control.maximized}
        }
    }
    HoverTip {active:control.hovered && !control.down;text:control.hint}
}
