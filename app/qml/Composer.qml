import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    readonly property Item modelAnchor: modelButton
    readonly property int queueOffset: queued.height
    height: 157 + Theme.control(33) - 33 + (backend.attachments.length ? Theme.control(48) : 0) + queueOffset
    signal openModels()
    signal chooseFiles()
    function focusInput() { prompt.forceActiveFocus() }
    function setText(value) { prompt.text = value; prompt.forceActiveFocus(); prompt.cursorPosition = value.length }
    function sendMessage(steering) {
        if (backend.kernelBusy || backend.loading) return
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
        else { sendMessage(); event.accepted = true }
    }
    Connections { target: backend; function onEditorText(text) { root.setText(text) } }
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
                        Text { id: attachmentName; x: Theme.control(31); anchors.verticalCenter: parent.verticalCenter; width: Math.min(implicitWidth, 165); text: modelData.name; textFormat: Text.PlainText; elide: Text.ElideMiddle; color: Theme.ink; font.pixelSize: Theme.font(10) }
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
                padding: 0; topPadding: 3; font.pixelSize: Theme.font(13)
                background: null
                onTextChanged: backend.setDraft(text)
                Keys.onPressed: event => { if (event.matches(StandardKey.Paste) && backend.pasteAttachments()) event.accepted = true }
                Keys.onReturnPressed: event => root.handleEnter(event)
                Keys.onEnterPressed: event => root.handleEnter(event)
            }
        }
        Row {
            x: 14; anchors.bottom: parent.bottom; anchors.bottomMargin: 12; spacing: 5
            ActionButton { objectName: "attachFilesButton"; glyph: "plus"; quiet: true; width: Theme.control(31); height: Theme.control(31); hint: I18n.t("添加文件"); onClicked: root.chooseFiles() }
            ActionButton { objectName: "openChatDirectoryButton"; glyph: "folder"; quiet: true; width: Theme.control(31); height: Theme.control(31); hint: I18n.t("在文件管理器中打开当前目录"); onClicked: backend.openChatDirectory() }
            Rectangle { width: 1; height: 15; color: Theme.line; anchors.verticalCenter: parent.verticalCenter }
            ContextUsage {}
            ActionButton {
                id: modelButton; objectName: "modelSelector"; quiet: true; height: Theme.control(31)
                width: Math.min(modelRow.implicitWidth + 18, 350)
                onClicked: root.openModels()
                contentItem: Item { Row {
                    id: modelRow; spacing: 7; anchors.verticalCenter: parent.verticalCenter; x: 10
                    Text { text: { let p = backend.config.providers.find(p => p.id === backend.config.selectedProvider); return p ? p.name : I18n.t("选择供应商") } color: Theme.ink; font.pixelSize: Theme.font(11); anchors.verticalCenter: parent.verticalCenter }
                    Text { text: "/"; font.pixelSize: Theme.font(11); color: Theme.muted; anchors.verticalCenter: parent.verticalCenter }
                    Text { text: backend.config.selectedModel; width: Math.min(implicitWidth, 135); elide: Text.ElideRight; color: Theme.muted; font.pixelSize: Theme.font(11); anchors.verticalCenter: parent.verticalCenter }
                    Text { objectName: "reasoningEffortBadge"; visible: backend.reasoningEffort !== "off"; text: "· " + ({low:"Low",high:"High",max:"Max"}[backend.reasoningEffort] || ""); color: Theme.accent; font.pixelSize: Theme.font(11); anchors.verticalCenter: parent.verticalCenter }
                    Glyph { name: "chevron-down"; width: Theme.icon(12); height: Theme.icon(12); anchors.verticalCenter: parent.verticalCenter }
                } }
            }
        }
        Row {
            anchors.right: parent.right; anchors.rightMargin: 14; anchors.bottom: parent.bottom; anchors.bottomMargin: 12; spacing: 13
            Text { objectName: "composerStatus"; visible: backend.compacting || Theme.fontScale <= 1.25; text: backend.compacting ? I18n.t(backend.toolStatus) : backend.loading ? I18n.t(backend.toolStatus || "正在加载 Pi") : backend.running ? I18n.t("Enter 加入队列 · Ctrl+S 优先") : I18n.t("Enter 发送"); font.pixelSize: Theme.font(10); color: Theme.muted; anchors.verticalCenter: parent.verticalCenter }
            Rectangle {
                objectName: "sendButton"
                readonly property bool stopAction: backend.running
                readonly property bool disabled: backend.loading || backend.kernelBusy || (!stopAction && !prompt.text.trim().length && !backend.attachments.length)
                width: Theme.control(33); height: Theme.control(33); radius: Theme.control(11)
                color: !disabled ? Theme.button : Theme.accentBg
                opacity: disabled ? 0.5 : 1
                Behavior on color { ColorAnimation { duration: 150 } }
                scale: sendArea.pressed ? 0.92 : 1
                Behavior on scale { NumberAnimation { duration: 100 } }
                Glyph { objectName: "sendGlyph"; color: parent.disabled ? Theme.muted : Theme.buttonText; anchors.centerIn: parent; name: backend.running ? "stop" : prompt.text.trim().length > 0 && !backend.loading ? (Theme.dark ? "arrow-up" : "send") : "arrow-up"; width: Theme.icon(17); height: Theme.icon(17) }
                MouseArea { id: sendArea; objectName: "sendArea"; anchors.fill: parent; enabled: !parent.disabled; hoverEnabled: true; cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor; onClicked: { if (backend.running) backend.stop(); else root.sendMessage(false) } }
                HoverTip { active: sendArea.containsMouse; text: backend.running ? I18n.t("停止当前会话任务") : I18n.t("发送消息") }
            }
        }
    }
}
