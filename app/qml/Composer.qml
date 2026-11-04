import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    readonly property Item modelAnchor: modelButton
    readonly property int queueOffset: queued.height
    height: 157 + footer.height - 33 + (backend.attachments.length ? Theme.control(48) : 0) + queueOffset
    signal openModels()
    signal chooseFiles()
    property bool slashDismissed: false
    readonly property bool slashVisible: prompt.activeFocus && !prompt.inputMethodComposing && /^\//.test(prompt.text) && !slashDismissed
    function chooseSlash(entry) {
        if (entry.group === "命令") {
            setText(entry.command + " ")
            slashDismissed = true
        } else if (backend.slashCommands.choose(entry.id)) {
            setText("")
        }
    }
    function focusInput() { prompt.forceActiveFocus() }
    function setText(value) { prompt.text = value; prompt.forceActiveFocus(); prompt.cursorPosition = value.length }
    function sendMessage(steering) {
        if (backend.kernelBusy || backend.loading) return
        if (/^\//.test(prompt.text)) {
            if (backend.slashCommands.execute(prompt.text)) setText("")
            return
        }
        if (steering) backend.steer(prompt.text)
        else if (prompt.text.trim().length || backend.attachments.length) backend.send(prompt.text)
    }
    function handleEnter(event) {
        if (prompt.inputMethodComposing) { event.accepted = false; return }
        if (event.modifiers & Qt.AltModifier) {
            const position = prompt.selectionStart
            prompt.remove(position, prompt.selectionEnd)
            prompt.insert(position, "\n")
            prompt.cursorPosition = position + 1
            event.accepted = true
        } else if (event.modifiers & Qt.ShiftModifier) event.accepted = false
        else if (root.slashVisible) { slashMenu.chooseSelection(); event.accepted = true }
        else { sendMessage(); event.accepted = true }
    }
    Connections { target: backend; function onEditorText(text) { root.setText(text) } }
    Connections { target: backend; function onViewChanged() { root.slashDismissed = false } }
    onSlashVisibleChanged: if (slashVisible) backend.slashCommands.refresh()
    CompactCommandMenu {
        id: slashMenu
        z: 20; width: parent.width
        anchors.bottom: parent.top; anchors.bottomMargin: 8
        // Track y explicitly: mapToItem() alone does not notify when the
        // bottom-anchored composer moves after its first layout pass.
        maximumHeight: Math.min(Theme.control(360), Math.max(Theme.control(66), root.y + root.parent.mapToItem(null, 0, 0).y - 90))
        visible: root.slashVisible
        entries: backend.slashCommands.entries
        query: prompt.text
        onChosen: entry => root.chooseSlash(entry)
    }
    QueuedMessages { id: queued; width: parent.width }
    Rectangle { x: 0; y: root.queueOffset + 6; width: parent.width; height: parent.height - root.queueOffset; radius: 17; color: "#090f0a"; opacity: Theme.dark ? 0.1 : 0.035 }
    Rectangle {
        x: 0; y: root.queueOffset; width: parent.width; height: parent.height - root.queueOffset; radius: 15; color: Theme.surface
        border.color: prompt.activeFocus && Theme.yanami ? Theme.accent : prompt.activeFocus ? (Theme.dark ? "#59735e" : "#b3c3b0") : Theme.line
        Behavior on border.color { ColorAnimation { duration: 180 } }
        Flickable {
            x: 16; y: 12; width: parent.width - 32; height: Theme.control(36); visible: backend.attachments.length > 0
            contentWidth: attachmentRow.width; contentHeight: height; clip: true
            Row { id: attachmentRow; spacing: 7
                Repeater {
                    model: backend.attachments
                    Rectangle {
                        required property var modelData
                        width: Math.min(attachmentName.implicitWidth, 165) + Theme.control(63); height: Theme.control(33); radius: 7; color: Theme.accentBg
                        Glyph { x: 9; anchors.verticalCenter: parent.verticalCenter; name: modelData.kind === "web" ? "globe" : modelData.kind === "folder" ? "folder" : modelData.kind === "image" ? "image" : "file"; width: Theme.icon(15); height: Theme.icon(15) }
                        Text { font.family: Theme.fontFamily; id: attachmentName; x: Theme.control(31); anchors.verticalCenter: parent.verticalCenter; width: Math.min(implicitWidth, 165); text: modelData.name; textFormat: Text.PlainText; elide: Text.ElideMiddle; color: Theme.ink; font.pixelSize: Theme.font(10, visible) }
                        ActionButton { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; width: Theme.control(27); height: Theme.control(27); quiet: true; glyph: "x"; onClicked: backend.removeAttachment(modelData.id) }
                    }
                }
            }
        }
        ScrollView {
            x: 20; y: backend.attachments.length ? Theme.control(48) + 15 : 15; width: parent.width - 40; height: 82; clip: true
            TextArea {
                id: prompt; objectName: "promptInput"
                color: Theme.ink; placeholderTextColor: Theme.muted
                placeholderText: backend.config.workspace ? I18n.t("在 ") + backend.workspaceName + I18n.t(" 项目下开展工作") : I18n.t("输入任务…")
                wrapMode: TextArea.Wrap; selectByMouse: true
                padding: 0; topPadding: 3; font.pixelSize: Theme.font(13, visible)
                font.family: Theme.fontFamily
                background: null
                onTextChanged: { root.slashDismissed = false; backend.setDraft(text) }
                Keys.onPressed: event => {
                    if (event.matches(StandardKey.Paste) && backend.pasteAttachments()) event.accepted = true
                    else if (root.slashVisible && !inputMethodComposing) {
                        if (event.key === Qt.Key_Up || event.key === Qt.Key_Down) {
                            slashMenu.moveSelection(event.key === Qt.Key_Up ? -1 : 1); event.accepted = true
                        } else if (event.key === Qt.Key_Tab) {
                            slashMenu.chooseSelection(); event.accepted = true
                        } else if (event.key === Qt.Key_Escape) {
                            root.slashDismissed = true; event.accepted = true
                        }
                    }
                }
                Keys.onReturnPressed: event => root.handleEnter(event)
                Keys.onEnterPressed: event => root.handleEnter(event)
            }
        }
        Item {
            id: footer; objectName: "composerToolbar"
            x: 14; width: parent.width - 28; anchors.bottom: parent.bottom; anchors.bottomMargin: 12
            readonly property real gap: 8
            readonly property real minimumModelWidth: Theme.control(96)
            readonly property bool permissionTextVisible: width >= utilityIcons.implicitWidth + permissionMetrics.width + Theme.icon(17) + 36 + minimumModelWidth + sendButton.width + gap * 3
            readonly property bool stacked: width < utilityRow.implicitWidth + minimumModelWidth + sendButton.width + gap * 2
            readonly property real trailingBudget: width - (stacked ? 0 : utilityRow.implicitWidth + gap) - minimumModelWidth - gap
            height: Theme.control(33) * (stacked ? 2 : 1) + (stacked ? gap : 0)
            TextMetrics { id: permissionMetrics; text: permissionButton.fullText; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12) }
            TextMetrics { id: statusMetrics; text: statusText.text; font.family: Theme.fontFamily; font.pixelSize: Theme.font(10) }
            Row {
                id: utilityRow; objectName: "composerUtilityControls"; spacing: 5
                y: (Theme.control(33) - height) / 2
                Row {
                    id: utilityIcons; spacing: 5
                    ActionButton { objectName: "attachFilesButton"; glyph: "plus"; quiet: true; width: Theme.control(31); height: Theme.control(31); hint: I18n.t("添加文件"); onClicked: root.chooseFiles() }
                    ActionButton { objectName: "openChatDirectoryButton"; glyph: "folder"; quiet: true; width: Theme.control(31); height: Theme.control(31); hint: I18n.t("在文件管理器中打开当前目录"); onClicked: backend.openChatDirectory() }
                    Rectangle { width: 1; height: 15; color: Theme.line; anchors.verticalCenter: parent.verticalCenter }
                    ContextUsage {}
                }
                ActionButton {
                    id: permissionButton; objectName: "composerPermissionStatus"
                    glyph: "lock"; quiet: true; height: Theme.control(31)
                    readonly property string fullText: (backend.config.agent.toolPermissionMode === "ask" ? I18n.t("询问") : I18n.t("自动")) + (backend.dangerousAllowed ? " · " + I18n.t("本会话已授权") : "")
                    text: footer.permissionTextVisible ? fullText : ""
                    width: footer.permissionTextVisible ? implicitWidth : Theme.control(31)
                    Accessible.name: fullText
                    hint: fullText + "\n" + (backend.dangerousAllowed ? I18n.t("本会话已允许全部危险操作，可在菜单中撤销。") : I18n.t("工具执行权限"))
                    onClicked: permissionMenu.openAt(Qt.point(0, -permissionMenu.implicitHeight - 8))
                    FloatingMenu {
                        id: permissionMenu; objectName: "composerPermissionMenu"
                        parent: permissionButton
                        onHeightChanged: if (visible) {
                            requestedPosition = Qt.point(0, -height - 8)
                            y = requestedPosition.y
                            Qt.callLater(fitToWindow)
                        }
                        ContextAction { text: I18n.t("自动"); glyph: backend.config.agent.toolPermissionMode === "auto" ? "check" : ""; onTriggered: backend.setToolPermissionMode("auto") }
                        ContextAction { text: I18n.t("询问"); glyph: backend.config.agent.toolPermissionMode === "ask" ? "check" : ""; onTriggered: backend.setToolPermissionMode("ask") }
                        MenuSeparator { visible: backend.dangerousAllowed; height: visible ? implicitHeight : 0 }
                        ContextAction {
                            objectName: "revokeDangerousApproval"
                            text: I18n.t("撤销本会话授权"); visible: backend.dangerousAllowed
                            onTriggered: backend.revokeDangerousApproval()
                        }
                    }
                }
            }
            ActionButton {
                id: modelButton; objectName: "modelSelector"; quiet: true; height: Theme.control(31)
                x: footer.stacked ? 0 : utilityRow.implicitWidth + footer.gap
                y: footer.height - Theme.control(33) + (Theme.control(33) - height) / 2
                width: Math.max(0, Math.min(Theme.control(350), naturalWidth, footer.width - x - trailingRow.width - footer.gap))
                readonly property string providerName: { const p = backend.config.providers.find(p => p.id === backend.config.selectedProvider); return p ? p.name : I18n.t("选择供应商") }
                readonly property string modelName: backend.config.selectedModel
                readonly property string effort: backend.reasoningEffort !== "off" ? "· " + ({low:"Low",high:"High",max:"Max"}[backend.reasoningEffort] || "") : ""
                readonly property real naturalWidth: providerMetrics.width + (modelName.length ? slashMetrics.width + Math.min(modelMetrics.width, Theme.control(135)) + 14 : 0) + (effort.length ? effortMetrics.width + 7 : 0) + Theme.icon(12) + 27
                readonly property real namesWidth: Math.max(0, width - 20 - Theme.icon(12) - 7 - (effortBadge.visible ? effortMetrics.width + 7 : 0))
                readonly property bool showProvider: !modelName.length || namesWidth >= Math.min(providerMetrics.width, Theme.control(48)) + Math.min(modelMetrics.width, Theme.control(90)) + slashMetrics.width + 14
                readonly property real providerWidth: Math.min(providerMetrics.width, modelName.length ? Math.max(Math.min(providerMetrics.width, Theme.control(48)), namesWidth - Math.min(modelMetrics.width, Theme.control(135)) - slashMetrics.width - 14) : namesWidth)
                hint: providerName + (modelName.length ? " / " + modelName : "") + (effort.length ? " " + effort : "")
                Accessible.name: hint
                TextMetrics { id: providerMetrics; text: modelButton.providerName; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11) }
                TextMetrics { id: modelMetrics; text: modelButton.modelName; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11) }
                TextMetrics { id: slashMetrics; text: "/"; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11) }
                TextMetrics { id: effortMetrics; text: modelButton.effort; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11) }
                onClicked: root.openModels()
                contentItem: Item { clip: true; Row {
                    id: modelRow; spacing: 7; anchors.verticalCenter: parent.verticalCenter; x: 10
                    Text { id: providerText; objectName: "composerProviderName"; visible: modelButton.showProvider; width: modelButton.providerWidth; text: modelButton.providerName; textFormat: Text.PlainText; elide: Text.ElideRight; color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11); anchors.verticalCenter: parent.verticalCenter }
                    Text { visible: providerText.visible && modelButton.modelName.length > 0; text: "/"; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11); color: Theme.muted; anchors.verticalCenter: parent.verticalCenter }
                    Text { objectName: "composerModelName"; visible: modelButton.modelName.length > 0; width: Math.min(modelMetrics.width, Math.max(0, modelButton.namesWidth - (providerText.visible ? providerText.width + slashMetrics.width + 14 : 0))); text: modelButton.modelName; textFormat: Text.PlainText; elide: Text.ElideRight; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11); anchors.verticalCenter: parent.verticalCenter }
                    Text { id: effortBadge; objectName: "reasoningEffortBadge"; visible: modelButton.effort.length > 0 && modelButton.width >= effortMetrics.width + Theme.icon(12) + Theme.control(36) + 34; text: modelButton.effort; color: Theme.accent; font.family: Theme.fontFamily; font.pixelSize: Theme.font(11); anchors.verticalCenter: parent.verticalCenter }
                    Glyph { name: "chevron-down"; width: Theme.icon(12); height: Theme.icon(12); anchors.verticalCenter: parent.verticalCenter }
                } }
            }
            Row {
                id: trailingRow; objectName: "composerSendControls"
                anchors.right: parent.right; anchors.bottom: parent.bottom; spacing: 13
                TaskStatus { id: taskStatus; objectName: "composerTaskStatus"; status: backend.turnStatus; compact: true; visible: state.length > 0 && footer.trailingBudget >= sendButton.width + implicitWidth + 13; anchors.verticalCenter: parent.verticalCenter }
                Text { id: statusText; font.family: Theme.fontFamily; objectName: "composerStatus"; visible: footer.trailingBudget >= sendButton.width + (taskStatus.visible ? taskStatus.width + 13 : 0) + statusMetrics.width + 13; text: backend.compacting ? I18n.t(backend.toolStatus) : backend.loading ? I18n.t(backend.toolStatus || "正在加载 Pi") : backend.running ? I18n.t("Enter 加入队列 · Ctrl+S 优先") : I18n.t("Enter 发送"); font.pixelSize: Theme.font(10); color: Theme.muted; anchors.verticalCenter: parent.verticalCenter }
                Rectangle {
                    id: sendButton; objectName: "sendButton"
                    readonly property bool stopAction: backend.running
                    readonly property bool disabled: backend.loading || backend.kernelBusy || (!stopAction && !prompt.text.trim().length && !backend.attachments.length)
                    Accessible.role: Accessible.Button
                    Accessible.name: backend.running ? I18n.t("停止当前会话任务") : I18n.t("发送消息")
                    Accessible.onPressAction: { if (!disabled) { if (backend.running) backend.stop(); else root.sendMessage(false) } }
                    width: Theme.control(33); height: Theme.control(33); radius: Theme.control(11)
                    color: !disabled ? Theme.button : Theme.accentBg
                    opacity: disabled ? 0.5 : 1
                    Behavior on color { ColorAnimation { duration: 150 } }
                    scale: sendArea.pressed ? 0.92 : 1
                    Behavior on scale { NumberAnimation { duration: 100 } }
                    Glyph { objectName: "sendGlyph"; color: parent.disabled ? Theme.muted : Theme.buttonText; anchors.centerIn: parent; name: backend.running ? "stop" : prompt.text.trim().length > 0 && !backend.loading ? (Theme.dark ? "arrow-up" : "send") : "arrow-up"; width: Theme.icon(17); height: Theme.icon(17) }
                    MouseArea { id: sendArea; objectName: "sendArea"; anchors.fill: parent; enabled: !parent.disabled; hoverEnabled: true; cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor; onClicked: { if (backend.running) backend.stop(); else root.sendMessage(false) } }
                    HoverTip { active: sendArea.containsMouse; text: (backend.running ? I18n.t("停止当前会话任务") : I18n.t("发送消息")) + "\n" + statusText.text }
                }
            }
        }
    }
}
