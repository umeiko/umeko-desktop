import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "ReasoningLevels.js" as Reasoning

AnchoredPidPopup {
    id: root
    objectName: "modelPopup"
    property real heightLimit: 470
    fullWidth: 365
    fullHeight: Math.max(220, Math.min(470, heightLimit, modelList.contentHeight + 230))
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
                Text { font.family: Theme.fontFamily; x: 9; topPadding: 5; bottomPadding: 7; text: provider.name + "  ·  " + provider.models.length + I18n.t(" 个模型"); color: Theme.muted; font.pixelSize: Theme.font(10, visible) }
                Repeater {
                    model: provider.models
                    Rectangle {
                        required property var modelData
                        objectName: "modelOption_" + provider.id + "_" + modelData.alias
                        property bool matches: (provider.name + " " + modelData.alias + " " + modelData.upstream).toLowerCase().indexOf(modelSearch.text.toLowerCase()) >= 0
                        width: modelList.width; height: matches ? 44 : 0; visible: matches; radius: 7
                        color: modelMouse.containsMouse ? Theme.hover : backend.config.selectedProvider === provider.id && backend.config.selectedModel === modelData.alias ? Theme.accentBg : "transparent"
                        Column { x: 11; width: parent.width - 44; anchors.verticalCenter: parent.verticalCenter; spacing: 3
                            Text { font.family: Theme.fontFamily; text: modelData.alias; width: parent.width; elide: Text.ElideRight; color: Theme.ink; font.pixelSize: Theme.font(12, visible) }
                            Text { font.family: Theme.fontFamily; text: modelData.upstream; width: parent.width; elide: Text.ElideRight; color: Theme.muted; font.pixelSize: Theme.font(9, visible) }
                        }
                        Glyph { anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; name: "check"; width: Theme.icon(15); height: Theme.icon(15); visible: backend.config.selectedProvider === provider.id && backend.config.selectedModel === modelData.alias }
                        MouseArea { id: modelMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { backend.selectModel(provider.id, modelData.alias); root.close() } }
                    }
                }
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
        ColumnLayout {
            id: reasoningControls
            objectName: "reasoningControls"
            Layout.fillWidth: true; spacing: 3
            readonly property var levels: { let values = ["off"]; for (const level of backend.reasoningLevels) values.push(level); return values }
            RowLayout {
                Layout.fillWidth: true
                Text { text: I18n.t("思考强度"); color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11) }
                Item { Layout.fillWidth: true }
                Text { objectName: "reasoningSelectedLabel"; text: backend.reasoningEffort === "off" ? I18n.t("关闭") : Reasoning.label(backend.reasoningEffort); textFormat: Text.PlainText; color: Theme.accent; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12); Layout.maximumWidth: reasoningControls.width * 0.6; elide: Text.ElideRight }
            }
            Slider {
                id: effortSlider; objectName: "reasoningEffortSlider"
                Layout.fillWidth: true
                from: 0; to: Math.max(1, reasoningControls.levels.length - 1)
                stepSize: 1; snapMode: Slider.SnapAlways
                enabled: reasoningControls.levels.length > 1
                value: Math.max(0, reasoningControls.levels.indexOf(backend.reasoningEffort))
                Accessible.name: I18n.t("思考强度")
                onMoved: backend.setReasoningEffort(reasoningControls.levels[Math.round(value)])
                Keys.onPressed: event => {
                    if (event.key === Qt.Key_Home || event.key === Qt.Key_End) {
                        backend.setReasoningEffort(reasoningControls.levels[event.key === Qt.Key_Home ? 0 : reasoningControls.levels.length - 1])
                        event.accepted = true
                    }
                }
                background: Rectangle { x: effortSlider.leftPadding; y: effortSlider.topPadding + effortSlider.availableHeight / 2 - height / 2; width: effortSlider.availableWidth; height: 4; radius: 2; color: Theme.line
                    Rectangle { width: effortSlider.visualPosition * parent.width; height: parent.height; radius: 2; color: Theme.accent }
                }
                handle: Rectangle { x: effortSlider.leftPadding + effortSlider.visualPosition * (effortSlider.availableWidth - width); y: effortSlider.topPadding + effortSlider.availableHeight / 2 - height / 2; implicitWidth: 16; implicitHeight: 16; radius: 8; color: Theme.accent; border.color: effortSlider.activeFocus ? Theme.ink : Theme.bg; border.width: 2 }
            }
            RowLayout {
                Layout.fillWidth: true
                Text { text: I18n.t("关闭"); color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(10) }
                Item { Layout.fillWidth: true }
                Text { text: reasoningControls.levels.length > 1 ? Reasoning.label(reasoningControls.levels[reasoningControls.levels.length - 1]) : ""; textFormat: Text.PlainText; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(10); Layout.maximumWidth: reasoningControls.width * 0.6; elide: Text.ElideRight }
            }
            HoverHandler { id: reasoningHover }
            HoverTip {
                objectName: "reasoningEffortHint"
                heading: I18n.t("思考强度")
                active: root.desiredOpen && reasoningHover.hovered
                text: I18n.t("关闭时不发送推理强度参数。可在供应商的模型齿轮中配置支持的档位。")
            }
        }
        ActionButton { text: I18n.t("管理供应商与模型"); glyph: "sliders"; quiet: true; Layout.fillWidth: true; onClicked: { root.close(); root.configure() } }
    }
    }
}
