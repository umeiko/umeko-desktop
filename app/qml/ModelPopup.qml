import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "ReasoningLevels.js" as Reasoning

AnchoredPidPopup {
    id: root
    objectName: "modelPopup"
    property real heightLimit: 470
    fullWidth: 365
    fullHeight: Math.max(220, Math.min(470, heightLimit, modelList.contentHeight + 230 + (offNote.visible ? offNote.implicitHeight + reasoningControls.spacing + 3 : 0)))
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
            // Effective levels; detection results can replace them while the popup is open.
            readonly property var levels: { backend.reasoningDetectionState; let values = ["off"]; for (const level of backend.reasoningLevels) values.push(level); return values }
            RowLayout {
                Layout.fillWidth: true
                Text { text: I18n.t("思考强度"); color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11) }
                Item { Layout.fillWidth: true }
                Text { objectName: "reasoningSelectedLabel"; text: backend.reasoningEffort === "off" ? I18n.t("关闭") : Reasoning.label(backend.reasoningEffort); textFormat: Text.PlainText; color: Theme.accent; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12); Layout.maximumWidth: reasoningControls.width * 0.6; elide: Text.ElideRight }
            }
            Slider {
                id: effortSlider; objectName: "reasoningEffortSlider"
                Layout.fillWidth: true
                implicitHeight: Theme.control(36); padding: 0
                readonly property real travel: Math.max(0, availableWidth - handle.width)
                readonly property real handleCenter: leftPadding + handle.width / 2 + visualPosition * travel
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
                background: Rectangle {
                    x: 0; y: (effortSlider.height - height) / 2
                    width: effortSlider.width; height: Theme.control(24); radius: height / 2
                    color: Theme.line; antialiasing: true
                    Rectangle {
                        width: effortSlider.enabled && effortSlider.value > effortSlider.from ? effortSlider.handleCenter : 0
                        height: parent.height
                        topLeftRadius: height / 2; bottomLeftRadius: height / 2
                        topRightRadius: 0; bottomRightRadius: 0
                        color: Theme.accent; antialiasing: true
                    }
                    Repeater {
                        model: reasoningControls.levels
                        Rectangle {
                            required property int index
                            width: 4; height: 4; radius: width / 2; antialiasing: true
                            x: effortSlider.leftPadding + effortSlider.handle.width / 2 + (reasoningControls.levels.length > 1 ? index / (reasoningControls.levels.length - 1) : 0) * effortSlider.travel - width / 2
                            anchors.verticalCenter: parent.verticalCenter
                            color: index <= effortSlider.value && effortSlider.enabled ? "#65ffffff" : Theme.muted
                            opacity: index <= effortSlider.value && effortSlider.enabled ? 1 : 0.45
                        }
                    }
                }
                handle: Rectangle {
                    x: effortSlider.leftPadding + effortSlider.visualPosition * effortSlider.travel
                    y: (effortSlider.height - height) / 2
                    implicitWidth: Theme.control(32); implicitHeight: implicitWidth; radius: width / 2
                    color: "white"; border.color: "#26000000"; border.width: 1; antialiasing: true
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Text { text: I18n.t("关闭"); color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(10) }
                Item { Layout.fillWidth: true }
                Text { text: reasoningControls.levels.length > 1 ? Reasoning.label(reasoningControls.levels[reasoningControls.levels.length - 1]) : ""; textFormat: Text.PlainText; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(10); Layout.maximumWidth: reasoningControls.width * 0.6; elide: Text.ElideRight }
            }
            Text {
                id: offNote; objectName: "reasoningOffNote"
                visible: backend.reasoningOffSupported === false
                text: I18n.t("这个模型总会思考，选「关闭」也会思考")
                Layout.fillWidth: true; Layout.topMargin: 3; wrapMode: Text.Wrap
                color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(10)
            }
        }
        ActionButton {
            id: manageProviders; objectName: "manageProvidersButton"
            text: I18n.t("管理供应商与模型"); quiet: true; Layout.fillWidth: true
            contentItem: Item {
                Row {
                    anchors.centerIn: parent; spacing: 8
                    Glyph {
                        id: providersIcon; name: "providers-stack"
                        width: Theme.icon(51); height: Theme.icon(17); anchors.verticalCenter: parent.verticalCenter
                        color: manageProviders.interactionHovered ? Theme.accent : Theme.muted
                    }
                    Text {
                        text: manageProviders.text; textFormat: Text.PlainText
                        width: Math.min(implicitWidth, Math.max(0, manageProviders.availableWidth - providersIcon.width - 8))
                        anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight
                        font.family: Theme.fontFamily; font.pixelSize: Theme.font(12); color: Theme.ink
                    }
                }
            }
            onClicked: { root.close(); root.configure() }
        }
    }
    }
}
