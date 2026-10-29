import QtQuick

QtObject {
    id: root
    property real minimumWidth: 200
    property real maximumWidth: 480
    property real collapseThreshold: minimumWidth * 0.7
    property int direction: 1
    property bool active: false
    property real pressX: 0
    property real pressWidth: 0
    property real dragWidth: 0
    property bool limitHintShown: false
    readonly property bool collapseReady: dragWidth <= collapseThreshold
    readonly property real settledWidth: Math.max(minimumWidth, Math.min(maximumWidth, dragWidth))
    signal maximumExceeded()
    function begin(position, width) {
        pressX = position; pressWidth = width; dragWidth = width
        limitHintShown = false; active = true
    }
    function move(position) {
        if (!active) return
        const requested = pressWidth + direction * (position - pressX)
        dragWidth = Math.max(0,Math.min(maximumWidth,requested))
        if (!limitHintShown && requested > maximumWidth + 24) {
            limitHintShown = true
            maximumExceeded()
        }
    }
    function end() { active = false }
}
