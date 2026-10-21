import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: root
    objectName: "modelPopup"
    property real heightLimit: 470
    property bool desiredOpen: false
    readonly property bool animating: motion.moving
    readonly property real fullWidth: 365
    readonly property real fullHeight: Math.max(150, Math.min(470, heightLimit, modelList.contentHeight + 150))
    readonly property real buttonWidth: parent ? parent.width : 180
    readonly property real buttonHeight: parent ? parent.height : 31
    function toggle() { if (desiredOpen) close(); else open() }
    width: Math.max(1,motion.value.width); height: Math.max(1,motion.value.height)
    x: motion.value.x; y: motion.value.y
    margins: 12; padding: 10; focus: true
    signal configure()
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
    background: Rectangle { radius: 12; color: Theme.surface; border.color: Theme.line }
    enter: Transition {}
    exit: Transition { PauseAnimation { duration: 800 } }
    onAboutToShow: { desiredOpen = true; modelSearch.clear() }
    onAboutToHide: desiredOpen = false
    onOpened: modelSearch.forceActiveFocus()
    onClosed: motion.snap()
    PidMotion { id: motion; targetRect: root.desiredOpen ? Qt.rect(0,-root.fullHeight-8,root.fullWidth,root.fullHeight) : Qt.rect(0,-root.buttonHeight-8,root.buttonWidth,root.buttonHeight) }
    contentItem: Item {
        clip: true
    ColumnLayout {
        width: root.fullWidth - root.padding * 2; height: root.fullHeight - root.padding * 2; spacing: 10
        opacity: Math.max(0,Math.min(1,((root.height-root.buttonHeight)/Math.max(1,root.fullHeight-root.buttonHeight)-0.15)/0.65))
        InputField { id: modelSearch; objectName: "modelSearch"; Layout.fillWidth: true; placeholderText: "搜索供应商或模型…"; height: 39 }
        ListView {
            id: modelList; Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 9
            model: backend.config.providers
            ScrollBar.vertical: ScrollBar {}
            delegate: Column {
                required property var modelData
                width: modelList.width; spacing: 3
                property var provider: modelData
                Text { x: 9; topPadding: 5; bottomPadding: 7; text: provider.name + "  ·  " + provider.models.length + " 个模型"; color: Theme.muted; font.pixelSize: 10 }
                Repeater {
                    model: provider.models
                    Rectangle {
                        required property var modelData
                        objectName: "modelOption_" + provider.id + "_" + modelData.alias
                        property bool matches: (provider.name + " " + modelData.alias + " " + modelData.upstream).toLowerCase().indexOf(modelSearch.text.toLowerCase()) >= 0
                        width: modelList.width; height: matches ? 44 : 0; visible: matches; radius: 7
                        color: modelMouse.containsMouse ? Theme.hover : backend.config.selectedProvider === provider.id && backend.config.selectedModel === modelData.alias ? Theme.accentBg : "transparent"
                        Column { x: 11; width: parent.width - 44; anchors.verticalCenter: parent.verticalCenter; spacing: 3
                            Text { text: modelData.alias; width: parent.width; elide: Text.ElideRight; color: Theme.ink; font.pixelSize: 12 }
                            Text { text: modelData.upstream; width: parent.width; elide: Text.ElideRight; color: Theme.muted; font.pixelSize: 9 }
                        }
                        Glyph { anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; name: "check"; width: 15; height: 15; visible: backend.config.selectedProvider === provider.id && backend.config.selectedModel === modelData.alias }
                        MouseArea { id: modelMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { backend.selectModel(provider.id, modelData.alias); root.close() } }
                    }
                }
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
        ActionButton { text: "管理供应商与模型"; glyph: "sliders"; quiet: true; Layout.fillWidth: true; onClicked: { root.close(); root.configure() } }
    }
    }
}
