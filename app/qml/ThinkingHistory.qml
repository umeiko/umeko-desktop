import QtQuick
import QtQuick.Controls
import Umeko.Text 1.0

Column {
    id: root
    property string text: ""
    property var expansionState: ({expanded:false})
    property bool expanded: expansionState.expanded
    onExpansionStateChanged: expanded = expansionState.expanded
    property var selectionController: null
    property int messageIndex: -1
    property int blockOffset: 0
    spacing: 6
    Item {
        width: heading.implicitWidth; height: Theme.control(24)
        Row {
            id: heading; height: parent.height; spacing: 7
            Glyph { name: "bulb"; width: Theme.icon(14); height: Theme.icon(14); anchors.verticalCenter: parent.verticalCenter }
            Text { font.family: Theme.fontFamily; text: I18n.t("思考过程"); color: hover.interactionHovered ? Theme.ink : Theme.muted; font.pixelSize: Theme.font(12, visible); anchors.verticalCenter: parent.verticalCenter }
            Glyph { name: root.expanded ? "chevron-down" : "chevron-right"; width: Theme.icon(12); height: Theme.icon(12); anchors.verticalCenter: parent.verticalCenter }
        }
        ChatHitArea {
            id: hover; objectName: "toggleThinking_" + root.messageIndex + "_" + root.blockOffset
            anchors.fill: parent; selectionController: root.selectionController
            onClicked: { root.expanded = !root.expanded; root.expansionState.expanded = root.expanded }
        }
        Accessible.role: Accessible.Button; Accessible.name: I18n.t("思考过程"); Accessible.description: root.expanded ? I18n.t("已展开") : I18n.t("已折叠")
    }
    Item {
        visible: root.expanded; width: parent.width; height: thinkingText.implicitHeight
        Rectangle { width: 1; height: parent.height; color: Theme.line; x: 6 }
        SelectableText {
            id: thinkingText; objectName: "thinkingText_" + root.messageIndex + "_" + root.blockOffset
            x: 23; width: parent.width - x; text: root.text
            color: Theme.muted; font.pixelSize: Theme.font(13, visible); wrapMode: TextEdit.Wrap; textFormat: TextEdit.PlainText
            selectionController: root.selectionController; messageIndex: root.messageIndex; blockIndex: root.blockOffset
            conditionalSelection: true
            TextSpacing { document: thinkingText.textDocument; factor: Theme.proseLineHeight }
        }
    }
}
