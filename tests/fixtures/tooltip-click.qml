import QtQuick
import "../../app/qml" as Ui

Item {
    id: root
    width: 500; height: 300
    property int clicks: 0
    Ui.ActionButton {
        objectName: "tooltipClickTarget"
        x: 150; y: 20; width: 160; height: 40; text: "Target"
        onClicked: root.clicks++
    }
    Item {
        x: 200; y: 150; width: 38; height: 38
        Ui.HoverTip {
            objectName: "overlappingHoverTip"
            x: -100; y: -140; width: 260
            active: true
            text: "Line one\nLine two\nLine three\nLine four\nLine five\nLine six"
        }
    }
}
