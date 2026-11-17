import QtQuick
import QtQuick.Templates as T

T.Switch {
    id:control
    readonly property real uiScale: typeof backend!=="undefined" ? Math.max(1,backend.fontScale) : 1
    readonly property bool darkSurface: typeof backend!=="undefined" ? (backend.themeStyle.base || backend.config.theme)==="dark" : palette.window.hslLightness<0.45
    implicitWidth:Math.max(implicitBackgroundWidth+leftInset+rightInset,implicitContentWidth+leftPadding+rightPadding,implicitIndicatorWidth+leftPadding+rightPadding)
    implicitHeight:Math.max(implicitBackgroundHeight+topInset+bottomInset,implicitContentHeight+topPadding+bottomPadding,implicitIndicatorHeight+topPadding+bottomPadding)
    padding:4*uiScale;spacing:10*uiScale
    palette.windowText:SurfaceStyle.colors.ink
    hoverEnabled:true
    opacity:enabled?1:0.42
    HoverHandler {cursorShape:control.enabled?Qt.PointingHandCursor:Qt.ArrowCursor}
    indicator:Item {
        objectName:"umekoSoftSwitchIndicator"
        implicitWidth:44*control.uiScale;implicitHeight:24*control.uiScale
        x:control.text ? (control.mirrored?control.width-width-control.rightPadding:control.leftPadding) : control.leftPadding+(control.availableWidth-width)/2
        y:control.topPadding+(control.availableHeight-height)/2
        Rectangle {
            anchors.centerIn:parent;width:parent.width;height:18*control.uiScale;radius:height/2
            border.width:1;border.color:control.darkSurface?"#52555d":"#cfd3d8"
            gradient:Gradient {
                GradientStop {position:0;color:control.darkSurface?"#292c32":"#e6e8eb"}
                GradientStop {position:1;color:control.darkSurface?"#35383e":"#ffffff"}
            }
        }
        Rectangle {x:2*control.uiScale;y:(parent.height-18*control.uiScale)/2+1;width:parent.width-4*control.uiScale;height:2*control.uiScale;radius:height/2;color:control.darkSurface?"#18000000":"#09000000"}
        Rectangle {
            width:6*control.uiScale;height:width;radius:width/2
            x:control.mirrored?parent.width-width-6*control.uiScale:6*control.uiScale
            anchors.verticalCenter:parent.verticalCenter
            color:control.darkSurface?"#94b7ff":"#85aaff";visible:control.checked
        }
        Item {
            id:thumb;objectName:"umekoSoftSwitchThumb"
            width:20*control.uiScale;height:width
            x:2*control.uiScale+control.visualPosition*(parent.width-width-4*control.uiScale)
            y:(parent.height-height)/2
            // Small, static layers give a soft shadow without an offscreen blur texture.
            Rectangle {x:-3;y:0;width:parent.width+6;height:parent.height+6;radius:width/2;color:control.darkSurface?"#0c000000":"#03000000"}
            Rectangle {x:-2;y:1;width:parent.width+4;height:parent.height+4;radius:width/2;color:control.darkSurface?"#16000000":"#07000000"}
            Rectangle {x:-1;y:2;width:parent.width+2;height:parent.height+2;radius:width/2;color:control.darkSurface?"#24000000":"#11000000"}
            Rectangle {
                anchors.fill:parent;radius:width/2;border.width:1;border.color:control.visualFocus?"#85aaff":control.darkSurface?"#72757b":"#dedfe3"
                gradient:Gradient {
                    GradientStop {position:0;color:control.down?"#f4f5f7":"#ffffff"}
                    GradientStop {position:1;color:control.down?"#e8e9ed":"#eceef1"}
                }
            }
            Behavior on x {enabled:!control.down;NumberAnimation {duration:150;easing.type:Easing.OutCubic}}
        }
    }
    contentItem:Text {
        text:control.text;font:control.font;color:control.palette.windowText;verticalAlignment:Text.AlignVCenter
        leftPadding:control.indicator&&!control.mirrored?control.indicator.width+control.spacing:0
        rightPadding:control.indicator&&control.mirrored?control.indicator.width+control.spacing:0
    }
}
