import QtQuick

ActionButton {
    id:control
    property bool dangerFill:false
    readonly property color keyTone:dangerFill?"#d9685f":Theme.button
    primary:dangerFill
    textColor:dangerFill?"#ffffff":primary?Theme.buttonText:destructive?Theme.danger:Theme.ink
    glyphColor:dangerFill?"#ffffff":primary?Theme.buttonText:destructive?Theme.danger:interactionHovered?Theme.accent:Theme.muted
    // A shallow keycap: a lit upper edge, darker lower rim and a short shadow.
    // Static primitives keep these small controls independent of blur layers.
    scale:1
    topPadding:down?2:0
    bottomPadding:0
    background:Item {
        readonly property color face:control.primary?control.keyTone:Theme.dark?Qt.lighter(Theme.surface,1.28):Qt.tint(Theme.surface,"#0ce6e2d9")
        readonly property color rim:control.visualFocus?Theme.accent:control.primary?Qt.darker(control.keyTone,1.25):Theme.dark?Qt.lighter(Theme.line,1.25):Qt.darker(Theme.line,1.08)
        readonly property bool sunken:control.down || control.checked
        Rectangle {
            x:-1;y:2;width:parent.width+2;height:parent.height;radius:7
            color:Theme.dark?"#26000000":"#09000000";opacity:parent.sunken?0.2:1
        }
        Rectangle {
            y:2;width:parent.width;height:parent.height;radius:6
            color:Theme.dark?"#30000000":"#14000000";opacity:parent.sunken?0:1
        }
        Rectangle {
            id:keycap
            y:parent.sunken?1:0;width:parent.width;height:parent.height-1;radius:6
            border.color:parent.rim
            gradient:Gradient {
                GradientStop {position:0;color:keycap.parent.sunken?Qt.darker(keycap.parent.face,1.10):Qt.lighter(keycap.parent.face,control.primary?1.25:1.07)}
                GradientStop {position:0.46;color:keycap.parent.sunken?Qt.darker(keycap.parent.face,1.04):control.interactionHovered?Qt.lighter(keycap.parent.face,1.05):keycap.parent.face}
                GradientStop {position:1;color:keycap.parent.sunken?keycap.parent.face:Qt.darker(keycap.parent.face,control.primary?1.12:1.045)}
            }
            Rectangle {
                anchors.fill:parent;anchors.margins:1;radius:5;color:"transparent"
                border.color:Theme.dark?"#14ffffff":control.primary?"#30ffffff":"#a0ffffff"
                opacity:keycap.parent.sunken?0.3:1
            }
            Rectangle {
                x:6;y:1;width:Math.max(0,parent.width-12);height:1
                color:control.primary?"#75ffffff":Theme.dark?"#30ffffff":"#e0ffffff"
                opacity:keycap.parent.sunken?0:1
            }
        }
    }
}
