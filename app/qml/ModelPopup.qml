import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "ReasoningLevels.js" as Reasoning

AnchoredPidPopup {
    id: root
    objectName: "modelPopup"
    property real heightLimit: 470
    readonly property string role: modelRole.currentIndex === 1 ? "planningModel" : modelRole.currentIndex === 2 ? "executionModel" : ""
    readonly property string roleModel: role ? (backend.sessionModelRoles || {})[role] || "" : ""
    readonly property bool useDshModels: backend.sessionBackend === "dsh" && backend.dshOwnConfig === true
    readonly property bool hasDshPath: backend.dshRuntime ? String(backend.dshRuntime.path || backend.dshRuntime.resolvedPath || "").trim().length > 0 : false
    fullWidth: 365
    fullHeight: Math.max(220, Math.min(470, heightLimit, modelList.contentHeight + (backend.modelGroupSelected ? 185 : 270) + (offNote.visible ? offNote.implicitHeight + reasoningControls.spacing + 3 : 0) + (ownModelsHint.visible ? ownModelsHint.implicitHeight + 10 : 0)))
    signal configure()
    signal dismissed()
    onAboutToShow: { modelSearch.clear(); modelRole.currentIndex = 0 }
    onAboutToHide: { focus = false; dismissed() }
    onOpened: {
        modelSearch.forceActiveFocus()
        if (backend.sessionBackend !== "dsh" && typeof backend.ensureReasoningDetection === "function") backend.ensureReasoningDetection()
    }
    onClosed: dismissed()
    component ModelChoice: Rectangle {
        id: choice
        required property string title
        property string subtitle: ""
        property bool matches: true
        property bool selected: false
        signal chosen()
        height: matches ? 44 : 0
        visible: matches
        radius: 7
        color: modelMouse.containsMouse ? Theme.hover : selected ? Theme.accentBg : "transparent"
        Column {
            x: 11; width: parent.width - 44; anchors.verticalCenter: parent.verticalCenter; spacing: 3
            Text {
                text: choice.title; width: parent.width; elide: Text.ElideRight; textFormat: Text.PlainText
                font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible); color: Theme.ink
            }
            Text {
                text: choice.subtitle; visible: text.length > 0; width: parent.width; elide: Text.ElideRight; textFormat: Text.PlainText
                font.family: Theme.fontFamily; font.pixelSize: Theme.font(9, visible); color: Theme.muted
            }
        }
        Glyph {
            anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter
            name: "check"; width: Theme.icon(15); height: Theme.icon(15); visible: choice.selected
        }
        MouseArea {
            id: modelMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
            onClicked: choice.chosen()
        }
    }
    contentItem: Item {
        clip: true
    ColumnLayout {
        width: root.expandedWidth - root.padding * 2; height: root.expandedHeight - root.padding * 2; spacing: 10
        opacity: root.contentOpacity
        RowLayout {
            Layout.fillWidth: true
            Text { text: I18n.t("会话后端"); color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11) }
            Item { Layout.fillWidth: true }
            BackendChoice { objectName: "choosePiBackend"; text: "Pi Coding Agent"; artwork: "../icons/pi.svg"; selected: backend.sessionBackend === "pi"; enabled: backend.canChooseBackend === true; onClicked: backend.setSessionBackend("pi") }
            BackendChoice { objectName: "chooseDshBackend"; text: "DeepSeek Harness"; artwork: "../icons/dsh.svg"; monochrome: true; experimental: true; visible: root.hasDshPath || backend.sessionBackend === "dsh"; selected: backend.sessionBackend === "dsh"; enabled: backend.canChooseBackend === true; onClicked: backend.setSessionBackend("dsh") }
        }
        ComboBox {
            id: modelRole; objectName: "modelRolePicker"
            visible: backend.sessionBackend === "pi"; Layout.fillWidth: true
            model: [I18n.t("对话模型"), I18n.t("规划模型"), I18n.t("执行模型")]
        }
        ModelChoice {
            objectName: "clearModelRole"
            Layout.fillWidth: true
            title: I18n.t("沿用对话模型")
            matches: !!root.role
            selected: !root.roleModel
            onChosen: if (backend.selectRoleModel(root.role, "")) root.close()
        }
        InputField { id: modelSearch; objectName: "modelSearch"; Layout.fillWidth: true; placeholderText: I18n.t("搜索供应商或模型…"); height: 39 }
        Text {
            id: ownModelsHint; objectName: "dshOwnModelsHint"
            Layout.fillWidth: true; wrapMode: Text.Wrap
            visible: root.useDshModels && modelList.count === 0
            text: I18n.t("连接 dsh 后显示其 ACP profile 的模型")
            textFormat: Text.PlainText; color: Theme.muted
            font.family: Theme.fontFamily; font.pixelSize: Theme.font(12, visible)
        }
        ListView {
            id: modelList; objectName: "modelOptionsList"; Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 9
            model: root.useDshModels ? backend.dshModelProviders : backend.config.providers.filter(p => p.api !== "image")
            ScrollBar.vertical: ScrollBar {}
            delegate: Column {
                required property var modelData
                width: modelList.width; spacing: 3
                property var provider: modelData
                Text { font.family: Theme.fontFamily; x: 9; topPadding: 5; bottomPadding: 7; text: provider.name + "  ·  " + provider.models.length + I18n.t(" 个模型"); color: Theme.muted; font.pixelSize: Theme.font(10, visible) }
                Repeater {
                    model: provider.models
                    ModelChoice {
                        required property var modelData
                        objectName: "modelOption_" + provider.id + "_" + modelData.alias
                        width: modelList.width
                        title: modelData.alias
                        subtitle: root.useDshModels ? "" : modelData.upstream
                        matches: (provider.name + " " + title + " " + subtitle).toLowerCase().includes(modelSearch.text.toLowerCase())
                        selected: root.role ? root.roleModel === modelData.alias : root.useDshModels ? backend.dshCurrentModelValue === modelData.value : !backend.modelGroupSelected && backend.config.selectedProvider === provider.id && backend.config.selectedModel === modelData.alias
                        onChosen: {
                            const controller = backend, providerId = provider.id, alias = modelData.alias, nativeValue = modelData.value, useDshModels = root.useDshModels
                            if (root.role) {
                                if (controller.selectRoleModel(root.role, alias)) root.close()
                                return
                            }
                            root.close()
                            if (useDshModels) controller.selectDshModel(nativeValue)
                            else controller.selectModel(providerId, alias)
                        }
                    }
                }
            }
            footer: ModelChoice {
                objectName: "modelGroupOption"
                width: modelList.width
                title: I18n.t("模型组")
                matches: backend.sessionBackend === "pi" && backend.modelGroupReady === true &&
                         (title + " 模型组 Model group").toLowerCase().includes(modelSearch.text.trim().toLowerCase())
                selected: root.role ? root.roleModel === "@umeko/model group" : backend.modelGroupSelected === true
                onChosen: {
                    if (root.role) {
                        if (backend.selectRoleModel(root.role, "@umeko/model group")) root.close()
                    } else {
                        root.close()
                        backend.selectModelGroup()
                    }
                }
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }
        ColumnLayout {
            id: reasoningControls
            objectName: "reasoningControls"
            visible: !root.role && backend.modelGroupSelected !== true
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
                enabled: reasoningControls.levels.length > 1 && (backend.sessionBackend !== "dsh" || !backend.busy)
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
            visible: !root.useDshModels
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
