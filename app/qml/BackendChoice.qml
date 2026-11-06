import QtQuick
import QtQuick.Controls
import QtQuick.Controls.impl

Button {
    id: control
    property url artwork
    property bool monochrome: false
    property bool selected: false
    property bool experimental: false
    readonly property string hint: text + (experimental ? " · " + I18n.t("实验版") : "")
    Accessible.name: hint
    implicitWidth: contents.implicitWidth + 24
    implicitHeight: Math.max(38, contents.implicitHeight + 12)
    padding: 0
    hoverEnabled: true
    opacity: enabled ? 1 : 0.45
    scale: down ? 0.97 : 1
    Behavior on scale { NumberAnimation { duration: 110; easing.type: Easing.OutCubic } }
    HoverHandler { cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }
    background: Rectangle {
        radius: 8
        color: control.down || control.selected ? Theme.accentBg : control.hovered ? Theme.hover : "transparent"
        border.color: control.activeFocus ? Theme.accent : control.selected ? Theme.line : "transparent"
        Behavior on color { ColorAnimation { duration: 140 } }
    }
    contentItem: Item {
        Row {
            id: contents
            anchors.centerIn: parent
            spacing: 7
            Loader {
                width: Theme.icon(26); height: width
                anchors.verticalCenter: parent.verticalCenter
                sourceComponent: control.monochrome ? tintedArtwork : originalArtwork
            }
            ExperimentalBadge {
                objectName: control.objectName + "Badge"
                visible: control.experimental
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }
    Component {
        id: originalArtwork
        Image { source: control.artwork; sourceSize: Qt.size(96, 96); fillMode: Image.PreserveAspectFit }
    }
    Component {
        id: tintedArtwork
        IconImage { source: control.artwork; color: Theme.ink; sourceSize: Qt.size(96, 96); fillMode: Image.PreserveAspectFit }
    }
    HoverTip { active: control.hovered && !control.down; text: control.hint }
}
