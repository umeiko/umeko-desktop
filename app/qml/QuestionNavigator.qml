import QtQuick
import QtQuick.Controls

Item {
    id: root
    objectName: "questionNavigator"
    property var view
    property int questionCount: backend.messageModel.questionCount
    property int questionRevision: 0
    property int activeQuestion: -1
    property real openY: height / 2
    readonly property bool expanded: panel.visible
    readonly property int rowHeight: Math.max(30, Theme.font(12) + 16)
    width: 24
    visible: enabled && view && view.visible && questionCount > 0

    function updateActive() {
        if (!view || !questionCount) { activeQuestion = -1; return }
        let row = view.atYEnd ? view.count - 1 : view.indexAt(1, view.contentY + 1)
        if (row < 0) row = view.indexAt(1, view.contentY + view.spacing + 2)
        if (row < 0) row = view.indexAt(1, view.contentY + view.height / 2)
        if (row < 0) row = view.atYEnd ? view.count - 1 : 0
        activeQuestion = backend.messageModel.questionIndexForRow(row)
    }
    function reveal(y) {
        if (!enabled || !visible || !questionCount) return
        closeTimer.stop()
        openY = y
        updateActive()
        panel.open()
        Qt.callLater(function() { questionList.positionViewAtIndex(Math.max(0, root.activeQuestion), ListView.Center) })
    }
    function scheduleClose() {
        if (edgeHover.hovered || panelHover.hovered) closeTimer.stop()
        else closeTimer.restart()
    }
    function dismiss() { openTimer.stop(); closeTimer.stop(); panel.close() }
    function jump(index) {
        if (index < 0 || index >= questionCount) return
        activeQuestion = index
        view.jumpToMessage(backend.messageModel.question(index).row)
    }
    onEnabledChanged: if (!enabled) dismiss()
    onVisibleChanged: if (!visible) dismiss()
    Connections { target: backend.messageModel; function onQuestionsChanged() { root.questionRevision++; if (!root.questionCount) root.dismiss(); else if (root.expanded) root.updateActive() } }

    TapHandler { onTapped: root.reveal(point.position.y) }
    HoverHandler {
        id: edgeHover
        cursorShape: Qt.PointingHandCursor
        onHoveredChanged: {
            if (hovered) { closeTimer.stop(); if (!root.expanded) openTimer.restart() }
            else { openTimer.stop(); root.scheduleClose() }
        }
    }
    Timer { id: openTimer; interval: 90; onTriggered: if (edgeHover.hovered) root.reveal(edgeHover.point.position.y) }
    Timer { id: closeTimer; interval: 180; onTriggered: if (!edgeHover.hovered && !panelHover.hovered) panel.close() }
    Timer { id: activeTimer; interval: 60; onTriggered: root.updateActive() }
    Connections {
        target: root.view
        function onContentYChanged() { if (root.expanded && !activeTimer.running) activeTimer.start() }
    }
    Connections { target: backend; function onViewChanged() { root.dismiss() } }

    Item {
        id: rail
        objectName: "questionNavigatorRail"
        anchors.centerIn: parent
        width: 12; height: Math.min(root.height - 16, Math.max(30, Math.min(32, root.questionCount) * 7))
        opacity: root.expanded || edgeHover.hovered ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 100 } }
        Repeater {
            model: rail.opacity > 0 ? Math.min(32, root.questionCount) : 0
            Rectangle {
                required property int index
                width: 5; height: 2; radius: 1; color: Theme.line
                anchors.horizontalCenter: parent.horizontalCenter
                y: index * (rail.height - height) / Math.max(1, Math.min(32, root.questionCount) - 1)
            }
        }
        Rectangle {
            width: 11; height: 3; radius: 1.5; color: Theme.accent
            y: Math.max(0, root.activeQuestion) * (rail.height - height) / Math.max(1, root.questionCount - 1)
        }
    }
    Popup {
        id: panel
        objectName: "questionNavigatorPanel"
        x: -width - 2
        y: Math.max(6, Math.min(root.height - height - 6, root.openY - height / 2))
        width: Math.min(360, root.parent.width - 52)
        readonly property int visibleRows: Math.max(1, Math.floor((Math.min(360, root.height - 12) - 16) / root.rowHeight))
        height: Math.min(root.questionCount, visibleRows) * root.rowHeight + 16
        padding: 8; margins: 8; focus: false
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
        background: Item {
            Repeater {
                model: 8
                Rectangle {
                    required property int index
                    readonly property real spread: (index + 1) * 0.6
                    x: -spread; y: 3 - spread
                    width: parent.width + spread * 2; height: parent.height + spread * 2
                    radius: 10 + spread; color: "#03000000"
                }
            }
            Rectangle { anchors.fill: parent; radius: 10; color: Theme.surface; border.color: Theme.line }
        }
        contentItem: ListView {
            id: questionList
            objectName: "questionNavigationList"
            clip: true; model: root.questionCount; boundsBehavior: Flickable.StopAtBounds; snapMode: ListView.SnapToItem
            HoverHandler { id: panelHover; onHoveredChanged: root.scheduleClose() }
            delegate: ItemDelegate {
                id: option
                required property int index
                readonly property var questionData: { const revision = root.questionRevision; return backend.messageModel.question(index) }
                objectName: "questionNavigationItem_" + index
                width: questionList.width; height: root.rowHeight
                focusPolicy: Qt.NoFocus; hoverEnabled: true
                Accessible.name: questionData.title || ""
                onClicked: root.jump(index)
                background: Rectangle {
                    radius: 5
                    color: option.index === root.activeQuestion ? Theme.accentBg : option.hovered ? Theme.hover : "transparent"
                }
                contentItem: Row {
                    id: questionLine
                    spacing: 9
                    Text {
                        id: ordinal
                        width: Math.max(18, String(root.questionCount).length * Theme.font(7)); anchors.verticalCenter: parent.verticalCenter
                        text: option.index + 1; color: Theme.muted; font.pixelSize: Theme.font(10)
                        horizontalAlignment: Text.AlignRight
                    }
                    Text {
                        width: Math.max(0, questionLine.width - ordinal.width - questionLine.spacing); anchors.verticalCenter: parent.verticalCenter
                        text: option.questionData.title || ""; textFormat: Text.PlainText
                        font.pixelSize: Theme.font(12); color: Theme.ink; elide: Text.ElideRight
                    }
                }
                HoverHandler { cursorShape: Qt.PointingHandCursor }
            }
        }
        enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 110 } }
        exit: Transition { NumberAnimation { property: "opacity"; to: 0; duration: 80 } }
    }
}
