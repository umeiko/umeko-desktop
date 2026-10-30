import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Window

Rectangle {
    id: root
    objectName: "subagentPane"
    color: Theme.surface
    property var agent: backend.subagents.selected
    property var contextState: backend.subagents.context
    readonly property bool running: agent.status === "running"
    readonly property bool inputFocused: prompt.activeFocus
    readonly property var attachments: root.contextState.attachments || []
    clip: true
    signal closed()
    function focusInput() { prompt.forceActiveFocus() }
    function acceptChatFiles(urls) {
        const accepted = backend.subagents.addAttachments(JSON.stringify(urls))
        if (accepted) {
            backend.activateChatWindow()
            if (root.Window.window) { root.Window.window.raise(); root.Window.window.requestActivate() }
            focusInput(); dropFocus.restart()
        }
        return accepted
    }
    Timer { id: dropFocus; interval: 80; onTriggered: { backend.activateChatWindow(); root.focusInput() } }
    FileDialog { id: files; title: I18n.t("添加文件"); fileMode: FileDialog.OpenFiles; onAccepted: root.acceptChatFiles(selectedFiles.map(url => url.toString())) }
    function statusLabel(status) { return I18n.t(({running:"运行中",queued:"排队中",completed:"已完成",error:"出错",stopped:"已停止",aborted:"已中断"})[status] || "子代理") }
    Item {
        id: header; width: parent.width; height: Theme.control(76)
        SubagentAvatar { x: Theme.control(16); anchors.verticalCenter: parent.verticalCenter; width: Theme.icon(41); height: width; slot: root.agent.avatarSlot || 0 }
        Column { x: Theme.control(68); width: Math.max(0,parent.width-x-Theme.control(55)); anchors.verticalCenter: parent.verticalCenter; spacing: 6
            Text { width: parent.width; text: (root.agent.name || I18n.t("子代理")) + " · " + root.statusLabel(root.agent.status); textFormat: Text.PlainText; maximumLineCount: 1; wrapMode: Text.NoWrap; color: Theme.ink; font.pixelSize: Theme.font(12); elide: Text.ElideRight }
            Text { objectName: "subagentHeaderSummary"; width: parent.width; text: String(root.agent.task || root.agent.type || "").replace(/\s+/g," "); maximumLineCount: 1; wrapMode: Text.NoWrap; textFormat: Text.PlainText; color: Theme.muted; font.pixelSize: Theme.font(10); elide: Text.ElideRight }
        }
        ActionButton { objectName: "closeSubagentPaneButton"; anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter; width: Theme.control(29); height: width; quiet: true; glyph: "x"; hint: I18n.t("关闭子代理对话"); onClicked: root.closed() }
    }
    Rectangle { anchors.top: header.bottom; width: parent.width; height: 1; color: Theme.line }
    ListView {
        id: conversation; objectName: "subagentConversation"
        anchors.top: header.bottom; anchors.topMargin: 18; anchors.bottom: activity.top; anchors.bottomMargin: 12
        anchors.left: parent.left; anchors.right: parent.right; clip: true; spacing: 15
        model: backend.subagents.messageModel
        reuseItems: true; cacheBuffer: 250
        property bool followTail: true
        property bool dragging: false
        function beginBrowsing() { followTail = false; cancelFlick() }
        function scrollBy(delta) { beginBrowsing(); contentY = Math.max(originY,Math.min(Math.max(originY,originY+contentHeight-height),contentY+delta)); if (atYEnd) followTail = true }
        onMovementStarted: followTail = false
        onAtYEndChanged: if (atYEnd) followTail = true
        onCountChanged: if (followTail) tail.restart()
        onContentHeightChanged: if (followTail) tail.restart()
        onContentYChanged: prefetch.restart()
        Timer { id: tail; interval: 0; onTriggered: if (conversation.followTail) conversation.positionViewAtEnd() }
        Timer { id: prefetch; interval: 0; onTriggered: {
            let first = conversation.indexAt(1,conversation.contentY+1)
            backend.subagents.messageModel.requestRange(Math.max(0,first),Math.max(0,first)+8)
        } }
        delegate: Column {
            id: message
            required property int index
            required property var modelData
            readonly property bool user: modelData.role === "user"
            width: conversation.width; spacing: 5
            Rectangle {
                x: message.user ? 35 : 17; width: parent.width-x-17
                height: body.implicitHeight + 20; radius: 11
                color: message.user ? Theme.userBubble : "transparent"
                Column {
                    id: body; x: 10; y: 10; width: parent.width-20; spacing: 6
                    Text { visible: !!message.modelData._loading; text: I18n.t("正在加载历史…"); color: Theme.muted; font.pixelSize: Theme.font(11) }
                    UserMessageBody { visible: message.user; width: parent.width; text: message.modelData.text || ""; attachments: message.modelData.attachments || []; selectionController: selection; messageIndex: message.index }
                    ActivityHistory { visible: !message.user; width: parent.width; activity: message.modelData.activity || []; selectionController: selection; messageIndex: message.index }
                    MessageBody { width: parent.width; text: !message.user && !(message.modelData.activity || []).length ? message.modelData.text || "" : ""; visible: text.length>0; markdown: true; selectionController: selection; messageIndex: message.index }
                }
            }
            SubagentReplyMascot {
                objectName: "subagentReplyMascot_" + message.index
                x: 27
                avatarSlot: root.agent.avatarSlot || 0; characterName: root.agent.name || ""
                selectionController: selection
                visible: !message.user && !message.modelData._loading && !root.contextState.loading && !root.contextState.pending
                         && message.index === conversation.count-1 && message.modelData.segmentLast !== false
                         && root.agent.status === "completed" && !message.modelData.error && (message.modelData.text || "").trim().length > 0
            }
        }
    }
    ChatSelection { id: selection; anchors.fill: conversation; view: conversation; dataSource: backend.subagents }
    Shortcut { sequences: [StandardKey.Copy]; enabled: selection.activeFocus && selection.hasSelection; onActivated: selection.copy() }
    Shortcut { sequences: [StandardKey.SelectAll]; enabled: selection.activeFocus; onActivated: selection.selectAll() }
    Shortcut { sequence: "Ctrl+S"; enabled: prompt.activeFocus && !root.contextState.loading && !root.contextState.pending; onActivated: composer.send(true) }
    Item {
        id: empty; anchors.fill: conversation; visible: root.contextState.loading || !!root.contextState.error || conversation.count === 0
        Column { anchors.centerIn: parent; width: parent.width-48; spacing: 15
            ActivitySpinner { anchors.horizontalCenter: parent.horizontalCenter; width: 20; height: 20; visible: root.contextState.loading }
            Text { width: parent.width; text: root.contextState.error || (root.contextState.loading ? I18n.t("正在加载子代理上下文…") : root.running ? I18n.t("子代理已开始工作…") : I18n.t("发送消息继续这个子代理的工作")); color: Theme.muted; font.pixelSize: Theme.font(12); wrapMode: Text.WrapAnywhere; horizontalAlignment: Text.AlignHCenter }
        }
    }
    Text {
        id: activity; x: 20; width: Math.max(0,parent.width-40); anchors.bottom: queued.top; anchors.bottomMargin: 10
        text: root.running ? (root.agent.activity || I18n.t("正在工作")) + " · " + I18n.t("调用工具 %1 次").replace("%1",root.agent.toolUses || 0) : root.contextState.truncated ? I18n.t("当前显示最近的对话内容") : ""
        textFormat: Text.PlainText; maximumLineCount: 1; wrapMode: Text.NoWrap; elide: Text.ElideRight; color: Theme.muted; font.pixelSize: Theme.font(10)
    }
    QueuedMessages {
        id: queued; objectName: "subagentQueuedMessages"
        controller: backend.subagents; objectPrefix: "subagent_"
        x: composer.x; width: composer.width; anchors.bottom: composer.top
        heightLimit: Math.max(Theme.control(32),Math.min(Theme.control(170),root.height-header.height-composer.height-Theme.control(150)))
    }
    Rectangle {
        id: composer; objectName: "subagentComposer"; x: 16; width: parent.width-32; height: Theme.control(142) + (root.attachments.length ? Theme.control(45) : 0); anchors.bottom: parent.bottom; anchors.bottomMargin: 18
        radius: 14; color: Theme.bg; border.color: prompt.activeFocus ? Qt.alpha(Theme.accent,0.5) : Theme.line
        function send(priority) {
            if (prompt.inputMethodComposing) return
            const accepted = priority ? backend.subagents.steer(prompt.text) : backend.subagents.send(prompt.text)
            if (accepted) prompt.focus = true
        }
        Flickable {
            x: 12; y: 9; width: parent.width-24; height: Theme.control(36); visible: root.attachments.length > 0
            contentWidth: chips.width; contentHeight: height; clip: true
            Row { id: chips; spacing: 6
                Repeater { model: root.attachments
                    Rectangle {
                        required property var modelData
                        width: Math.min(label.implicitWidth,160) + Theme.control(44); height: Theme.control(32); radius: 6; color: Theme.accentBg
                        Text { id: label; x: 9; width: Math.min(implicitWidth,160); anchors.verticalCenter: parent.verticalCenter; text: modelData.name; font.pixelSize: Theme.font(10); color: Theme.ink; textFormat: Text.PlainText; elide: Text.ElideMiddle }
                        ActionButton { objectName: "removeSubagentAttachment_" + modelData.id; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; glyph: "x"; quiet: true; width: Theme.control(27); height: width; onClicked: backend.subagents.removeAttachment(modelData.id) }
                    }
                }
            }
        }
        ScrollView { x: 14; y: 11 + (root.attachments.length ? Theme.control(45) : 0); width: parent.width-28; height: parent.height-58-(root.attachments.length ? Theme.control(45) : 0)
            TextArea {
                id: prompt; objectName: "subagentPromptInput"
                text: root.contextState.draft || ""; selectByMouse: true; wrapMode: TextArea.Wrap
                color: Theme.ink; placeholderTextColor: Theme.muted; font.pixelSize: Theme.font(12)
                placeholderText: root.running ? I18n.t("向这个子代理发送指引…") : I18n.t("发送消息，从当前上下文继续…")
                background: null; padding: 0
                onTextChanged: backend.subagents.setDraft(text)
                function enter(event) {
                    if (inputMethodComposing) { event.accepted = false; return }
                    if (event.modifiers & Qt.AltModifier) {
                        const position = selectionStart
                        remove(position,selectionEnd); insert(position,"\n"); cursorPosition = position+1
                        event.accepted = true; return
                    }
                    if (event.modifiers & Qt.ShiftModifier) { event.accepted = false; return }
                    if (!root.contextState.loading && !root.contextState.pending) composer.send(false)
                    event.accepted = true
                }
                Keys.onReturnPressed: event => enter(event)
                Keys.onEnterPressed: event => enter(event)
            }
        }
        Row {
            anchors.right: parent.right; anchors.rightMargin: 10; anchors.bottom: parent.bottom; anchors.bottomMargin: 9; spacing: 8
            ActionButton { objectName: "stopSubagentButton"; visible: !!root.agent.active; quiet: true; width: Theme.control(31); height: width; glyph: "stop"; hint: I18n.t("停止这个子代理"); onClicked: backend.subagents.stop() }
            ActionButton { objectName: "sendSubagentButton"; primary: true; width: Theme.control(32); height: width; glyph: root.running ? "queue" : "arrow-up"; enabled: !root.contextState.loading && !root.contextState.pending && root.agent.status !== "queued" && (prompt.text.trim().length>0 || root.attachments.length>0); hint: root.running ? I18n.t("Enter 加入队列 · Ctrl+S 优先") : I18n.t("继续子代理"); onClicked: composer.send(false) }
        }
        ActionButton { objectName: "addSubagentAttachmentButton"; x: 9; anchors.bottom: parent.bottom; anchors.bottomMargin: 9; width: Theme.control(30); height: width; glyph: "plus"; quiet: true; hint: I18n.t("添加文件"); onClicked: files.open() }
        Text { x: Theme.control(47); anchors.bottom: parent.bottom; anchors.bottomMargin: 17; width: Math.max(0,parent.width-x-105); visible: Theme.fontScale <= 1.25; text: root.contextState.pending ? I18n.t("正在发送…") : root.running ? I18n.t("Enter 加入队列 · Ctrl+S 优先") : I18n.t("继续当前上下文"); elide: Text.ElideRight; color: Theme.muted; font.pixelSize: Theme.font(10) }
    }
    Connections { target: backend.subagents
        function onMessageSent(id) { if (id === root.agent.id) prompt.text = backend.subagents.context.draft || "" }
        function onDraftRestored(id) { if (id === root.agent.id) { prompt.text = backend.subagents.context.draft || ""; root.focusInput() } }
        function onRequested() { conversation.followTail = true; selection.clear() }
    }
    ChatFileDrop {
        anchors.fill: parent; z: 70; chatWindow: root
        objectName: "subagentFileDropArea"; overlayName: "subagentFileDropOverlay"; mascotName: "subagentFileCatchMascot"
        mascotSource: Character.roleAsset(root.agent.avatarSlot || 0, "catch", "../icons/subagents/" + ["lemon-yakishio","chika-komari","kaju-nukumizu","yumeko-shikiya"][root.agent.avatarSlot || 0] + "-catch.png")
        promptText: Character.roleLine(root.agent.avatarSlot || 0, "fileDrop", Character.scene("files.drop", ""))
    }
}
