import QtQuick
import QtQuick.Controls

ListView {
    id: root
    required property var sdk
    property var entries: []
    property string selectedId: ""
    property bool available: true
    property color changedColor: "#d7b65b"
    property color changedBg: "transparent"
    property bool dark: true
    signal selectedLeaf(string identifier)
    signal fold(string identifier)
    signal toggled(string identifier, bool value)
    objectName: "systemPromptTree"
    clip: true
    spacing: 1
    boundsBehavior: Flickable.StopAtBounds
    // A new array model resets the view to the top. Refreshes and folding keep
    // the scroll position, so the model is assigned here instead of bound.
    onEntriesChanged: {
        const kept = contentY
        model = entries
        Qt.callLater(() => {
            contentY = Math.max(originY, Math.min(kept, originY + contentHeight - height))
            reveal()
        })
    }
    Component.onCompleted: model = entries
    ScrollBar.vertical: ScrollBar {}
    // Keep the selected segment in view, e.g. after the selection is restored on refresh.
    function reveal() {
        const index = entries.findIndex(entry => entry.id === selectedId)
        if (index >= 0) positionViewAtIndex(index, ListView.Contain)
    }
    onSelectedIdChanged: Qt.callLater(reveal)
    delegate: PromptTreeRow {
        required property var modelData
        objectName: "systemPromptRow_" + modelData.id
        width: ListView.view.width
        sdk: root.sdk
        entry: modelData
        selected: !modelData.folder && !modelData.hint && modelData.id === root.selectedId
        available: root.available
        changedColor: root.changedColor
        changedBg: root.changedBg
        dark: root.dark
        onSelectedLeaf: identifier => root.selectedLeaf(identifier)
        onFold: identifier => root.fold(identifier)
        onToggled: (identifier, value) => root.toggled(identifier, value)
    }
}
