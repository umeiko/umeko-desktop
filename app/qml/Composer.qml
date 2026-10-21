import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    readonly property Item modelAnchor: modelButton
    property int queueOffset: backend.queuedMessages.length ? Math.min(112, 31 + backend.queuedMessages.length * 25) + 12 : 0
    height: 157 + (backend.attachments.length ? 48 : 0) + queueOffset
    signal openModels()
    signal chooseFiles()
    function focusInput() { prompt.forceActiveFocus() }
    function setText(value) { prompt.text = value; prompt.forceActiveFocus(); prompt.cursorPosition = value.length }
    function sendMessage(steering) {
        if (backend.loading || backend.kernelBusy) return
        if (steering) backend.steer(prompt.text)
        else if (prompt.text.trim().length || backend.attachments.length) backend.send(prompt.text)
    }
    Connections { target: backend; function onEditorText(text) { root.setText(text) } }
    Rectangle { x: 0; y: 6; width: parent.width; height: parent.height; radius: 17; color: "#090f0a"; opacity: Theme.dark ? 0.1 : 0.035 }
    Rectangle {
        anchors.fill: parent; radius: 15; color: Theme.surface
        border.color: fileDrop.containsDrag || (prompt.activeFocus && Theme.yanami) ? Theme.accent : prompt.activeFocus ? (Theme.dark ? "#59735e" : "#b3c3b0") : Theme.line
        Behavior on border.color { ColorAnimation { duration: 180 } }
        Column {
            x: 20; y: 10; width: parent.width - 40; spacing: 5; visible: backend.queuedMessages.length > 0
            Row {
                width: parent.width; height: 25; spacing: 10
                Text { text: "待处理 " + backend.queuedMessages.length + " · 点击编辑"; color: Theme.accent; font.pixelSize: 10; anchors.verticalCenter: parent.verticalCenter }
                ActionButton { objectName: "promoteQueueButton"; text: "Ctrl+S 优先处理"; height: 25; quiet: true; onClicked: backend.steer("") }
            }
            Flickable { width: parent.width; height: Math.min(75, queueRows.implicitHeight); contentHeight: queueRows.implicitHeight; clip: true; acceptedButtons: Qt.NoButton
                Column { id: queueRows; width: parent.width; spacing: 4
                    Repeater { model: backend.queuedMessages
                        Rectangle { required property var modelData; required property int index; width: parent.width; height: 23; radius: 5
                            color: editArea.containsMouse ? Theme.accentBg : "transparent"
                            Row { anchors.fill: parent; anchors.leftMargin: 4; spacing: 9
                                Text { text: modelData.mode === "steering" ? "优先" : "队列"; color: Theme.accent; font.pixelSize: 10; anchors.verticalCenter: parent.verticalCenter }
                                Text { width: parent.width - 45; text: [modelData.text.replace(/\n/g, " "), ...(modelData.attachments || []).map(item => item.name)].filter(part => part.length).join(" · "); elide: Text.ElideRight; color: Theme.muted; font.pixelSize: 11; anchors.verticalCenter: parent.verticalCenter }
                            }
                            MouseArea { id: editArea; objectName: "editQueued_" + index; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: backend.editQueued(modelData.id) }
                            ToolTip.visible: editArea.containsMouse
                            ToolTip.text: modelData.mode === "steering" ? "等待当前工具或回复结束后优先处理；点击撤回编辑" : "点击撤回到输入框编辑"
                        }
                    }
                }
            }
        }
        Flickable {
            x: 16; y: root.queueOffset + 12; width: parent.width - 32; height: 36; visible: backend.attachments.length > 0
            contentWidth: attachmentRow.width; contentHeight: height; clip: true
            Row { id: attachmentRow; spacing: 7
                Repeater {
                    model: backend.attachments
                    Rectangle {
                        required property var modelData
                        width: Math.min(attachmentName.implicitWidth, 165) + 63; height: 33; radius: 7; color: Theme.accentBg
                        Glyph { x: 9; anchors.verticalCenter: parent.verticalCenter; name: modelData.kind === "folder" ? "folder" : modelData.kind === "image" ? "image" : "file"; width: 15; height: 15 }
                        Text { id: attachmentName; x: 31; anchors.verticalCenter: parent.verticalCenter; width: Math.min(implicitWidth, 165); text: modelData.name; elide: Text.ElideMiddle; color: Theme.ink; font.pixelSize: 10 }
                        ActionButton { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; width: 27; height: 27; quiet: true; glyph: "x"; onClicked: backend.removeAttachment(modelData.id) }
                    }
                }
            }
        }
        ScrollView {
            x: 20; y: root.queueOffset + (backend.attachments.length ? 63 : 15); width: parent.width - 40; height: 82; clip: true
            TextArea {
                id: prompt; objectName: "promptInput"
                color: Theme.ink; placeholderTextColor: Theme.muted
                placeholderText: backend.config.workspace ? "在 " + backend.workspaceName + " 项目下开展工作" : "输入任务…"
                wrapMode: TextArea.Wrap; selectByMouse: true
                padding: 0; topPadding: 3; font.pixelSize: 13
                background: null
                onTextChanged: backend.setDraft(text)
                Keys.onPressed: event => { if (event.matches(StandardKey.Paste) && backend.pasteAttachments()) event.accepted = true }
                Keys.onReturnPressed: event => { if (!(event.modifiers & Qt.ShiftModifier) && !inputMethodComposing) { root.sendMessage(); event.accepted = true } else event.accepted = false }
                Keys.onEnterPressed: event => { if (!(event.modifiers & Qt.ShiftModifier) && !inputMethodComposing) { root.sendMessage(); event.accepted = true } else event.accepted = false }
            }
        }
        Row {
            x: 14; anchors.bottom: parent.bottom; anchors.bottomMargin: 12; spacing: 5
            ActionButton { objectName: "attachFilesButton"; glyph: "plus"; quiet: true; width: 31; height: 31; hint: "添加文件"; onClicked: root.chooseFiles() }
            ActionButton { objectName: "openChatDirectoryButton"; glyph: "folder"; quiet: true; width: 31; height: 31; hint: "在文件管理器中打开当前目录"; onClicked: backend.openChatDirectory() }
            Rectangle { width: 1; height: 15; color: Theme.line; anchors.verticalCenter: parent.verticalCenter }
            ContextUsage {}
            ActionButton {
                id: modelButton; objectName: "modelSelector"; quiet: true; height: 31
                width: Math.min(modelRow.implicitWidth + 18, 310)
                onClicked: root.openModels()
                contentItem: Item { Row {
                    id: modelRow; spacing: 7; anchors.verticalCenter: parent.verticalCenter; x: 10
                    Text { text: { let p = backend.config.providers.find(p => p.id === backend.config.selectedProvider); return p ? p.name : "选择供应商" } color: Theme.ink; font.pixelSize: 11; anchors.verticalCenter: parent.verticalCenter }
                    Text { text: "/"; font.pixelSize: 11; color: Theme.muted; anchors.verticalCenter: parent.verticalCenter }
                    Text { text: backend.config.selectedModel; width: Math.min(implicitWidth, 135); elide: Text.ElideRight; color: Theme.muted; font.pixelSize: 11; anchors.verticalCenter: parent.verticalCenter }
                    Glyph { name: "chevron-down"; width: 12; height: 12; anchors.verticalCenter: parent.verticalCenter }
                } }
            }
        }
        Row {
            anchors.right: parent.right; anchors.rightMargin: 14; anchors.bottom: parent.bottom; anchors.bottomMargin: 12; spacing: 13
            Text { text: backend.loading ? backend.toolStatus || "正在加载 Pi" : backend.running ? "Enter 加入队列 · Ctrl+S 优先" : "Enter 发送"; font.pixelSize: 10; color: Theme.muted; anchors.verticalCenter: parent.verticalCenter }
            Rectangle {
                objectName: "sendButton"
                readonly property bool stopAction: backend.running
                readonly property bool disabled: backend.loading || backend.kernelBusy || (!stopAction && !prompt.text.trim().length && !backend.attachments.length)
                width: 33; height: 33; radius: 11
                color: !disabled ? Theme.button : Theme.accentBg
                opacity: disabled ? 0.5 : 1
                Behavior on color { ColorAnimation { duration: 150 } }
                scale: sendArea.pressed ? 0.92 : 1
                Behavior on scale { NumberAnimation { duration: 100 } }
                Glyph { objectName: "sendGlyph"; anchors.centerIn: parent; name: backend.running ? "stop" : prompt.text.trim().length > 0 && !backend.loading ? (Theme.dark ? "arrow-up" : "send") : "arrow-up"; width: 17; height: 17 }
                MouseArea { id: sendArea; objectName: "sendArea"; anchors.fill: parent; enabled: !parent.disabled; hoverEnabled: true; cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor; onClicked: { if (backend.running) backend.stop(); else root.sendMessage(false) } }
                ToolTip.visible: sendArea.containsMouse
                ToolTip.text: backend.running ? "停止当前会话任务" : "发送消息"
            }
        }
    }
    DropArea {
        id: fileDrop; objectName: "composerDropArea"; anchors.fill: parent
        onEntered: drag => { drag.accepted = drag.urls.length > 0 }
        onDropped: drop => { backend.addAttachments(JSON.stringify(drop.urls.map(url => url.toString()))); drop.acceptProposedAction(); prompt.forceActiveFocus() }
    }
    Rectangle {
        anchors.fill: parent; radius: 15; color: Theme.accentBg; opacity: 0.95; visible: fileDrop.containsDrag; border.color: Theme.accent
        Row { anchors.centerIn: parent; spacing: 10; Glyph { name: "plus"; width: 19; height: 19 } Text { text: "添加文件或文件夹"; color: Theme.accent; font.pixelSize: 13 } }
    }
}
