import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

AnchoredPidPopup {
    id: root
    objectName: "modelPopup"
    property real heightLimit: 470
    fullWidth: 365
    fullHeight: Math.max(220, Math.min(470, heightLimit, modelList.contentHeight + 200))
    signal configure()
    signal dismissed()
    onAboutToShow: modelSearch.clear()
    onAboutToHide: { focus = false; dismissed() }
    onOpened: modelSearch.forceActiveFocus()
    onClosed: dismissed()
    contentItem: Item {
        clip: true
    ColumnLayout {
        width: root.expandedWidth - root.padding * 2; height: root.expandedHeight - root.padding * 2; spacing: 10
        opacity: root.contentOpacity
        InputField { id: modelSearch; objectName: "modelSearch"; Layout.fillWidth: true; placeholderText: I18n.t("搜索供应商或模型…"); height: 39 }
        ListView {
            id: modelList; Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 9
            model: backend.config.providers
            ScrollBar.vertical: ScrollBar {}
            delegate: Column {
                required property var modelData
                width: modelList.width; spacing: 3
                property var provider: modelData
                Text { font.family: Theme.fontFamily; x: 9; topPadding: 5; bottomPadding: 7; text: provider.name + "  ·  " + provider.models.length + I18n.t(" 个模型"); color: Theme.muted; font.pixelSize: Theme.font(10) }
                Repeater {
                    model: provider.models
                    Rectangle {
                        required property var modelData
                        objectName: "modelOption_" + provider.id + "_" + modelData.alias
                        property bool matches: (provider.name + " " + modelData.alias + " " + modelData.upstream).toLowerCase().indexOf(modelSearch.text.toLowerCase()) >= 0
                        width: modelList.width; height: matches ? 44 : 0; visible: matches; radius: 7
                        color: modelMouse.containsMouse ? Theme.hover : backend.config.selectedProvider === provider.id && backend.config.selectedModel === modelData.alias ? Theme.accentBg : "transparent"
                        Column { x: 11; width: parent.width - 44; anchors.verticalCenter: parent.verticalCenter; spacing: 3
                            Text { font.family: Theme.fontFamily; text: modelData.alias; width: parent.width; elide: Text.ElideRight; color: Theme.ink; font.pixelSize: Theme.font(12) }
                            Text { font.family: Theme.fontFamily; text: modelData.upstream; width: parent.width; elide: Text.ElideRight; color: Theme.muted; font.pixelSize: Theme.font(9) }
                        }
                        Glyph { anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; name: "check"; width: Theme.icon(15); height: Theme.icon(15); visible: backend.config.selectedProvider === provider.id && backend.config.selectedModel === modelData.alias }
                        MouseArea { id: modelMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { backend.selectModel(provider.id, modelData.alias); root.close() } }
                    }
                }
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
        RowLayout {
            id: reasoningControls
            objectName: "reasoningControls"
            Layout.fillWidth: true; spacing: 8
            Repeater {
                model: [{value:"off",label:I18n.t("关闭")},{value:"low",label:"Low"},{value:"high",label:"High"},{value:"max",label:"Max"}]
                ActionButton {
                    required property var modelData
                    Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.minimumWidth: 0
                    objectName: "reasoningEffort_" + modelData.value
                    text: modelData.label; quiet: true; primary: backend.reasoningEffort === modelData.value
                    onClicked: backend.setReasoningEffort(modelData.value)
                }
            }
            HoverHandler { id: reasoningHover }
            HoverTip {
                objectName: "reasoningEffortHint"
                heading: I18n.t("思考强度")
                active: root.desiredOpen && reasoningHover.hovered
                text: I18n.t("关闭：不发送推理强度参数。\nLow / High / Max：以模型支持的档位为准。")
            }
        }
        ActionButton { text: I18n.t("管理供应商与模型"); glyph: "sliders"; quiet: true; Layout.fillWidth: true; onClicked: { root.close(); root.configure() } }
    }
    }
}
