import QtQuick

TextEdit {
    id: root
    objectName: "selectText_" + messageIndex + "_" + blockIndex
    property var selectionController: null
    property int messageIndex: -1
    property int blockIndex: 0
    property bool conditionalSelection: false
    readOnly: true
    font.family: Theme.fontFamily
    selectByMouse: !selectionController
    persistentSelection: true
    selectionColor: Theme.selectionBg
    selectedTextColor: Theme.selectionText
    Component.onCompleted: if (selectionController) selectionController.attach(root)
    Component.onDestruction: if (selectionController) selectionController.detach(root)
    onTextChanged: if (selectionController) selectionController.refreshSoon()
    onVisibleChanged: if (selectionController) selectionController.refreshSoon()
}
