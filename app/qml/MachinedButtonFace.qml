import QtQuick
import QtQuick.Shapes

// Static vector finish: a cut bevel, broad metal reflections and fine lathe rings.
Item {
    id:root
    property bool pressed:false
    property bool focused:false
    property bool active:true
    implicitWidth:30;implicitHeight:30
    opacity:active?1:0.82
    Rectangle {x:0;y:2;width:parent.width;height:parent.height-1;radius:width/2;color:Theme.dark?"#65000000":"#32000000";opacity:root.pressed?0.25:1}
    Rectangle {anchors.fill:parent;radius:width/2;color:Theme.dark?"#171c22":"#969fa9";border.color:root.focused?"#6398d0":Theme.dark?"#12181f":"#929ca6"}
    Item {
        id:disk;x:1;y:root.pressed?2:0.5;width:parent.width-2;height:parent.height-2
        Shape {
            anchors.fill:parent;antialiasing:true
            ShapePath {
                strokeWidth:0.5;strokeColor:"#8b959f"
                fillGradient:ConicalGradient {
                    centerX:disk.width/2;centerY:disk.height/2;angle:40
                    GradientStop {position:0;color:"#b0bac4"}
                    GradientStop {position:0.13;color:"#ffffff"}
                    GradientStop {position:0.26;color:"#939eaa"}
                    GradientStop {position:0.43;color:"#f7fafc"}
                    GradientStop {position:0.57;color:"#86939f"}
                    GradientStop {position:0.74;color:"#fdfefe"}
                    GradientStop {position:0.90;color:"#abb6c0"}
                    GradientStop {position:1;color:"#b0bac4"}
                }
                startX:disk.width/2;startY:0.3
                PathArc {x:disk.width/2;y:disk.height-0.3;radiusX:(disk.width-0.6)/2;radiusY:(disk.height-0.6)/2}
                PathArc {x:disk.width/2;y:0.3;radiusX:(disk.width-0.6)/2;radiusY:(disk.height-0.6)/2}
            }
        }
        Item {
            id:face;anchors.fill:parent;anchors.margins:1.5
            Shape {
                anchors.fill:parent;antialiasing:true
                ShapePath {
                    strokeWidth:0.5;strokeColor:"#d9dfe5"
                    fillGradient:ConicalGradient {
                        centerX:face.width/2;centerY:face.height/2;angle:40
                        GradientStop {position:0;color:"#d4dbe1"}
                        GradientStop {position:0.13;color:"#f4f7f9"}
                        GradientStop {position:0.25;color:"#bdc7d0"}
                        GradientStop {position:0.43;color:"#e9eef2"}
                        GradientStop {position:0.56;color:"#b1bdc7"}
                        GradientStop {position:0.73;color:"#f7f9fb"}
                        GradientStop {position:0.87;color:"#c3cdd6"}
                        GradientStop {position:1;color:"#d4dbe1"}
                    }
                    startX:face.width/2;startY:0.3
                    PathArc {x:face.width/2;y:face.height-0.3;radiusX:(face.width-0.6)/2;radiusY:(face.height-0.6)/2}
                    PathArc {x:face.width/2;y:0.3;radiusX:(face.width-0.6)/2;radiusY:(face.height-0.6)/2}
                }
            }
            Repeater {
                model:10
                Rectangle {
                    required property int index
                    anchors.centerIn:parent;width:parent.width*(0.94-index*0.081);height:width;radius:width/2
                    color:"transparent";border.width:0.45;antialiasing:true;border.color:index%2?"#26ffffff":"#14717e8c"
                }
            }
            Rectangle {anchors.fill:parent;radius:width/2;color:Theme.dark?"#1830445a":"transparent"}
            Rectangle {anchors.fill:parent;radius:width/2;color:"#24000000";visible:root.pressed}
        }
    }
}
