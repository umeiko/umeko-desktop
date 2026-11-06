import QtQuick
import QtQuick.Controls

ListView {
    id: root
    required property var sdk
    property var entries: []
    property string selectedId: ""
    property bool available: true
    signal selectedLeaf(string identifier)
    signal fold(string identifier)
    signal toggled(string identifier, bool value)
    objectName: "systemPromptTree"
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    model: entries
    ScrollBar.vertical: ScrollBar {}
    delegate: PromptTreeRow {
        required property var modelData
        objectName: "systemPromptRow_" + modelData.id
        width: ListView.view.width
        sdk: root.sdk
        entry: modelData
        selected: !modelData.folder && modelData.id === root.selectedId
        available: root.available
        onSelectedLeaf: identifier => root.selectedLeaf(identifier)
        onFold: identifier => root.fold(identifier)
        onToggled: (identifier, value) => root.toggled(identifier, value)
    }
}
