import QtQuick
import QtQuick.Templates as T
T.RadioButton {
    id:control
    padding:4*SurfaceStyle.uiScale;spacing:8*SurfaceStyle.uiScale;hoverEnabled:true
    implicitWidth:Math.max(implicitBackgroundWidth+leftInset+rightInset,implicitContentWidth+leftPadding+rightPadding,implicitIndicatorWidth+leftPadding+rightPadding)
    implicitHeight:Math.max(28*SurfaceStyle.uiScale,implicitContentHeight+topPadding+bottomPadding,implicitIndicatorHeight+topPadding+bottomPadding)
    palette.windowText:SurfaceStyle.colors.ink
    opacity:enabled?1:0.42
    HoverHandler {cursorShape:control.enabled?Qt.PointingHandCursor:Qt.ArrowCursor}
    indicator:SelectionIndicator {
        radio:true;checkState:control.checked?Qt.Checked:Qt.Unchecked;pressed:control.down;hovered:control.hovered;focused:control.visualFocus
        x:control.text?(control.mirrored?control.width-width-control.rightPadding:control.leftPadding):control.leftPadding+(control.availableWidth-width)/2
        y:control.topPadding+(control.availableHeight-height)/2
    }
    contentItem:Text {
        text:control.text;font:control.font;color:control.palette.windowText;verticalAlignment:Text.AlignVCenter
        leftPadding:control.text && !control.mirrored?control.indicator.width+control.spacing:0
        rightPadding:control.text && control.mirrored?control.indicator.width+control.spacing:0
    }
}
