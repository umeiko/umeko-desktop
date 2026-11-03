import QtQuick
import QtQuick.Controls

Item {
    id: pane
    required property var window
    required property var messageModel
    required property string viewKey
    required property var requestInspector
    property bool current: false
    property bool blocked: false
    property bool initialized: false
    property bool layoutDirty: false
    property bool released: false
    property bool busy: false
    property bool running: false
    property string toolStatus: ""
    property string workspace: ""
    property var turnStatus: ({})
    property alias view: conversation
    property alias selection: chatSelection
    visible: current
    enabled: current
    function refreshState() {
        if (!current)
            return;
        busy = backend.busy;
        running = backend.running;
        toolStatus = backend.toolStatus;
        turnStatus = backend.turnStatus;
        workspace = backend.conversationWorkspace;
    }
    function activate() {
        current = true;
        refreshState();
        if (!initialized || layoutDirty || conversation.restoring) {
            initialized = true;
            layoutDirty = false;
            conversation.restoreViewport();
        } else {
            conversation.requestVisibleRange();
        }
    }
    function deactivate() {
        conversation.saveViewport();
        current = false;
        tailTimer.stop();
        restoreTimer.stop();
        pagePrefetch.stop();
        chatSelection.clear();
    }
    function release() {
        deactivate();
        released = true;
        conversation.model = null;
    }
    ListView {
        id: conversation
        objectName: pane.current ? "conversation" : "cachedConversation_" + pane.viewKey
        property bool followTail: true
        property bool restoring: false
        property real restoreOffset: -1
        property int restoreIndex: -1
        property int restoreAttempts: 0
        readonly property string layoutKey: width + "/" + Theme.fontScale + "/" + Theme.proseLineHeight + "/" + window.font.family
        onLayoutKeyChanged: {
            pane.messageModel.setLayout(layoutKey);
            if (!pane.current)
                pane.layoutDirty = true;
            else if (!followTail && count)
                restoreViewport();
        }
        function beginBrowsing() {
            tailTimer.stop();
            restoreTimer.stop();
            restoring = false;
            cancelFlick();
            followTail = false;
        }
        function jumpToMessage(row) {
            if (row < 0 || row >= count)
                return;
            beginBrowsing();
            chatSelection.clear();
            restoring = true;
            restoreIndex = row;
            restoreOffset = 0;
            restoreAttempts = 0;
            restoreTimer.restart();
        }
        function jumpToLatest() {
            beginBrowsing();
            chatSelection.clear();
            followTail = true;
            restoring = true;
            restoreIndex = -1;
            restoreOffset = 0;
            restoreAttempts = 0;
            pane.messageModel.requestRange(Math.max(0, count - 4), count - 1);
            restoreTimer.restart();
        }
        function scrollBy(delta) {
            beginBrowsing();
            const top = originY;
            const bottom = Math.max(top, originY + contentHeight - height);
            contentY = Math.max(top, Math.min(bottom, contentY + delta));
            if (atYEnd && !chatSelection.dragging)
                followTail = true;
        }
        function saveViewport() {
            if (restoring || !pane.current)
                return;
            let index = indexAt(1, contentY + 1);
            if (index < 0)
                index = indexAt(1, contentY + spacing + 2);
            const item = index >= 0 ? itemAtIndex(index) : null;
            backend.saveViewport(index, item ? contentY - item.y : 0, followTail);
        }
        function restoreViewport() {
            restoring = true;
            tailTimer.stop();
            followTail = backend.followTail;
            restoreOffset = backend.scrollPosition;
            restoreIndex = backend.scrollAnchor;
            restoreAttempts = 0;
            restoreTimer.restart();
        }
        acceptedButtons: Qt.NoButton
        visible: count > 0
        anchors.fill: parent
        clip: true
        spacing: 27
        model: pane.messageModel
        cacheBuffer: Math.max(0, height * 0.25)
        currentIndex: -1
        // A hidden attached ScrollBar still writes contentY when its
        // size changes. Variable-height rows must have one scroll owner.
        onFollowTailChanged: saveViewport()
        onContentYChanged: {
            saveViewport();
            scheduleRange();
        }
        function scheduleRange() {
            if (pane.current && pane.messageModel.paged && !pagePrefetch.running)
                pagePrefetch.start();
        }
        function requestVisibleRange() {
            if (!pane.current || !count || !pane.messageModel.paged)
                return;
            forceLayout();
            const top = contentY, bottom = top + height, margin = height * 0.25;
            const visibleRows = [], nearbyRows = [];
            // indexAt() returns -1 in spacing and outside instantiated delegates.
            // Inspect the actual intersecting slots so a gap cannot starve rows.
            for (const item of contentItem.children) {
                if (item.messageSlot !== true)
                    continue;
                if (item.y + item.height > top && item.y < bottom)
                    visibleRows.push(item.index);
                else if (item.y + item.height > top - margin && item.y < bottom + margin)
                    nearbyRows.push(item.index);
            }
            visibleRows.sort((a, b) => a - b);
            nearbyRows.sort((a, b) => a - b);
            if (visibleRows.length)
                pane.messageModel.requestViewport(visibleRows, nearbyRows);
            else
                scheduleRange();
        }
        Timer {
            id: pagePrefetch
            interval: 16
            onTriggered: {
                if (!conversation.restoring)
                    conversation.requestVisibleRange();
            }
        }
        onContentHeightChanged: {
            scheduleRange();
            if (pane.current && followTail && !restoring)
                tailTimer.restart();
        }
        onCountChanged: {
            scheduleRange();
            if (pane.current && followTail && !restoring)
                tailTimer.restart();
        }
        onMovementEnded: scheduleRange()
        Timer {
            id: tailTimer
            interval: 0
            onTriggered: {
                if (pane.current && conversation.followTail && !conversation.restoring)
                    conversation.positionViewAtEnd();
            }
        }
        Timer {
            id: restoreTimer
            interval: 16
            repeat: true
            onTriggered: {
                if (!pane.current) {
                    stop();
                    return;
                }
                conversation.forceLayout();
                conversation.restoreAttempts++;
                if (conversation.followTail || conversation.restoreIndex < 0) {
                    conversation.positionViewAtEnd();
                    pane.messageModel.requestRange(Math.max(0, conversation.count - 4), conversation.count - 1);
                    const tail = conversation.itemAtIndex(conversation.count - 1);
                    if (conversation.count && (!tail || !tail.bodyReady) && conversation.restoreAttempts < 200)
                        return;
                } else {
                    const index = Math.min(conversation.restoreIndex, conversation.count - 1);
                    pane.messageModel.requestRange(index, index + 3);
                    if (conversation.restoreAttempts === 1) {
                        conversation.positionViewAtIndex(index, ListView.Beginning);
                        conversation.forceLayout();
                        return;
                    }
                    if (!pane.messageModel.isReady(index) && conversation.restoreAttempts < 200)
                        return;
                    const item = conversation.itemAtIndex(index);
                    if ((!item || !item.bodyReady) && conversation.restoreAttempts < 200)
                        return;
                    if (item) {
                        conversation.positionViewAtIndex(index, ListView.Beginning);
                        if (!conversation.atYEnd)
                            conversation.contentY += Math.min(conversation.restoreOffset, item.height - 1);
                    }
                }
                if (conversation.restoreAttempts >= 2) {
                    stop();
                    conversation.restoring = false;
                    conversation.saveViewport();
                    conversation.requestVisibleRange();
                }
            }
        }
        Connections {
            target: backend
            function onTranscriptChanged() {
                if (pane.current && conversation.followTail && !conversation.restoring)
                    tailTimer.restart();
            }
            enabled: pane.current
            function onChatChanged() {
                pane.refreshState();
            }
        }
        Connections {
            target: pane.messageModel
            enabled: pane.current
            function onViewportChanged() {
                // A page arrival is not a navigation request. ListView keeps
                // its anchor while asynchronous delegate heights settle.
                conversation.scheduleRange();
            }
        }
        footer: Item {
            width: conversation.width
            height: turnStatus.visible ? turnStatus.implicitHeight + 20 : 0
            TaskStatus {
                id: turnStatus
                objectName: "turnStatus"
                x: 33
                y: 8
                status: pane.turnStatus
            }
        }
        delegate: Item {
            id: rowShell
            Component.onDestruction: bodyLoader.active = false
            required property var modelData
            required property int index
            readonly property bool messageSlot: true
            Component.onCompleted: conversation.scheduleRange()
            onYChanged: conversation.scheduleRange()
            onHeightChanged: conversation.scheduleRange()
            readonly property bool bodyReady: bodyLoader.item !== null && bodyLoader.status === Loader.Ready
            readonly property var replyMascot: bodyLoader.item ? bodyLoader.item.replyMascot : null
            width: conversation.width - 16
            height: bodyReady ? bodyLoader.item.implicitHeight : Math.max(64, modelData._estimatedHeight || pane.messageModel.estimatedHeight(index))
            Loader {
                id: bodyLoader
                width: parent.width
                asynchronous: true
                active: !pane.released && !rowShell.modelData._loading
                onLoaded: {
                    pane.messageModel.recordHeight(rowShell.index, item.implicitHeight);
                    conversation.scheduleRange();
                }
                sourceComponent: Column {
                    id: messageRow
                    readonly property var replyMascot: closingMascot
                    property var modelData: rowShell.modelData
                    property int index: rowShell.index
                    readonly property bool compactionNotice: modelData.customType === "umeko-compaction"
                    readonly property point hoverPoint: chatSelection.mapToItem(messageRow, chatSelection.pointer.x, chatSelection.pointer.y)
                    readonly property bool hovered: chatSelection.hovering && hoverPoint.x >= 0 && hoverPoint.x <= width && hoverPoint.y >= 0 && hoverPoint.y <= height
                    width: conversation.width - 16
                    spacing: 10
                    onImplicitHeightChanged: if (bodyLoader.status === Loader.Ready)
                        pane.messageModel.recordHeight(index, implicitHeight)
                    Row {
                        visible: !modelData._loading && !messageRow.compactionNotice && !modelData.continuation && modelData.role !== "user"
                        spacing: 9
                        AssistantAvatar {
                            objectName: "assistantAvatar_" + messageRow.index
                            messageKey: pane.viewKey + "/" + messageRow.index
                        }
                        SelectableText {
                            selectionController: chatSelection
                            messageIndex: messageRow.index
                            blockIndex: -100000
                            text: "umeko"
                            anchors.verticalCenter: parent.verticalCenter
                            color: Theme.ink
                            font.pixelSize: Theme.font(11, visible)
                            font.weight: Font.DemiBold
                        }
                    }
                    Rectangle {
                        objectName: "messageBubble_" + messageRow.index
                        border.width: 1
                        border.color: window.searchHighlightRow === messageRow.index ? Theme.accent : "transparent"
                        Behavior on border.color {
                            ColorAnimation {
                                duration: 180
                            }
                        }
                        visible: !modelData._loading && !messageRow.compactionNotice
                        readonly property bool userMessage: modelData.role === "user"
                        width: userMessage ? (modelData.text.length > 512 ? messageRow.width * 0.82 : Math.min(messageRow.width * 0.82, Math.max(64, userBody.implicitWidth + 28))) : parent.width - 33
                        x: userMessage ? parent.width - width : 33
                        height: replyColumn.implicitHeight + (userMessage ? 22 : modelData.error ? 28 : 4)
                        radius: userMessage ? 13 : 8
                        color: userMessage ? Theme.userBubble : modelData.error ? Theme.accentBg : "transparent"
                        Column {
                            id: replyColumn
                            x: parent.userMessage || modelData.error ? 14 : 0
                            y: parent.userMessage ? 11 : modelData.error ? 14 : 0
                            width: parent.width - x * 2
                            spacing: 10
                            ActivityHistory {
                                width: parent.width
                                activity: modelData.activity || []
                                selectionController: chatSelection
                                messageIndex: messageRow.index
                            }
                            UserMessageBody {
                                id: userBody
                                width: parent.width
                                visible: modelData.role === "user"
                                text: modelData.role === "user" ? modelData.text : ""
                                attachments: modelData.attachments || []
                                selectionController: chatSelection
                                messageIndex: messageRow.index
                            }
                            MessageBody {
                                id: reply
                                width: parent.width
                                preparedBlocks: modelData._rendered || null
                                selectionController: chatSelection
                                messageIndex: messageRow.index
                                visible: modelData.role !== "user" && text.length > 0 && !(modelData.activity || []).length
                                text: modelData.role === "user" || (modelData.activity || []).length ? "" : modelData.text || (messageRow.index === conversation.count - 1 && pane.busy ? I18n.t(pane.toolStatus) + "…" : "")
                                markdown: modelData.role === "assistant" && !modelData.error
                                textColor: modelData.error ? Theme.danger : Theme.ink
                            }
                        }
                    }
                    ActionButton {
                        objectName: "requestDetails_" + messageRow.index
                        selectionController: chatSelection
                        visible: !modelData._loading && !messageRow.compactionNotice && !!modelData.error && (modelData.diagnosticId || "").length > 0
                        x: 33
                        text: I18n.t("查看请求与返回")
                        glyph: "code"
                        quiet: true
                        onClicked: requestInspector.show(modelData.diagnosticId)
                    }
                    Column {
                        id: compactionEvent
                        objectName: "compactionEvent_" + messageRow.index
                        x: 33
                        width: parent.width - 33
                        visible: !modelData._loading && messageRow.compactionNotice
                        readonly property var record: modelData.compaction || ({})
                        readonly property string eventState: record.state || "success"
                        readonly property string heading: eventState === "running" ? I18n.t("正在压缩上下文") : eventState === "failure" ? I18n.t("上下文压缩失败") : I18n.t("上下文已压缩")
                        property bool expanded: false
                        spacing: 6
                        onExpandedChanged: if (!expanded)
                            chatSelection.hideDetails(messageRow.index, 0, 1)
                        Item {
                            width: Math.min(parent.width, compactionHeading.implicitWidth)
                            height: Theme.control(24)
                            Row {
                                id: compactionHeading
                                height: parent.height
                                spacing: 7
                                ActivitySpinner {
                                    visible: compactionEvent.eventState === "running"
                                    width: Theme.icon(12)
                                    height: Theme.icon(12)
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text {
                                    font.family: Theme.fontFamily
                                    text: compactionEvent.heading
                                    color: compactionHover.interactionHovered ? Theme.ink : Theme.muted
                                    font.pixelSize: Theme.font(12, visible)
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Glyph {
                                    name: compactionEvent.expanded ? "chevron-down" : "chevron-right"
                                    width: Theme.icon(12)
                                    height: Theme.icon(12)
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                            }
                            ChatHitArea {
                                id: compactionHover
                                objectName: "compactionEventToggle_" + messageRow.index
                                anchors.fill: parent
                                selectionController: chatSelection
                                onClicked: compactionEvent.expanded = !compactionEvent.expanded
                            }
                            Accessible.role: Accessible.Button
                            Accessible.name: compactionEvent.heading
                            Accessible.description: compactionEvent.expanded ? I18n.t("已展开") : I18n.t("已折叠")
                        }
                        Item {
                            visible: compactionEvent.expanded
                            width: parent.width
                            height: compactionDetails.implicitHeight
                            Rectangle {
                                width: 1
                                height: parent.height
                                color: Theme.line
                                x: 6
                            }
                            SelectableText {
                                id: compactionDetails
                                objectName: "compactionEventDetails_" + messageRow.index
                                x: 23
                                width: parent.width - x
                                text: {
                                    const detail = compactionEvent.record, lines = [];
                                    if (typeof detail.before === "number")
                                        lines.push(I18n.t("压缩前：") + detail.before + " tokens");
                                    if (typeof detail.after === "number")
                                        lines.push(I18n.t("压缩后：") + detail.after + " tokens");
                                    if (detail.summary)
                                        lines.push("\n" + I18n.t("压缩摘要") + "\n" + detail.summary);
                                    if (detail.error)
                                        lines.push("\n" + I18n.t(detail.error));
                                    return lines.join("\n");
                                }
                                color: Theme.muted
                                font.pixelSize: Theme.font(13, visible)
                                wrapMode: TextEdit.Wrap
                                textFormat: TextEdit.PlainText
                                selectionController: chatSelection
                                messageIndex: messageRow.index
                                blockIndex: 0
                                conditionalSelection: true
                            }
                        }
                    }
                    OutputLimitNotice {
                        objectName: "outputLimitNotice_" + messageRow.index
                        x: 33
                        width: parent.width - 33
                        visible: !modelData._loading && !messageRow.compactionNotice && modelData.segmentLast !== false && modelData.role === "assistant" && modelData.stopReason === "length"
                        continuable: messageRow.index === conversation.count - 1 && !pane.busy
                        onContinued: backend.send(I18n.t("继续刚才未完成的回答，从中断处接着输出，不要重复已有内容。"))
                    }
                    Item {
                        objectName: "messageActions_" + messageRow.index
                        visible: !modelData._loading && !messageRow.compactionNotice && modelData.segmentLast !== false
                        width: parent.width
                        height: 18
                        opacity: messageRow.hovered || actionHover.hovered ? 1 : 0
                        HoverHandler {
                            id: actionHover
                        }
                        Row {
                            x: modelData.role === "user" ? parent.width - width : 33
                            height: parent.height
                            spacing: 7
                            Text {
                                font.family: Theme.fontFamily
                                objectName: "messageTime_" + messageRow.index
                                anchors.verticalCenter: parent.verticalCenter
                                color: Theme.muted
                                font.pixelSize: Theme.font(11, visible)
                                text: {
                                    if (!modelData.timestamp)
                                        return "";
                                    const date = new Date(modelData.timestamp);
                                    if (isNaN(date.getTime()))
                                        return "";
                                    return Qt.formatDateTime(date, date.toDateString() === new Date().toDateString() ? "hh:mm" : "MM-dd hh:mm");
                                }
                            }
                            ActionButton {
                                objectName: "copyMessage_" + messageRow.index
                                selectionController: chatSelection
                                glyph: "copy"
                                width: Theme.control(22)
                                height: Theme.control(18)
                                quiet: true
                                enabled: parent.parent.opacity > 0
                                hint: I18n.t("复制消息")
                                onClicked: backend.copyDisplayMessage(messageRow.index)
                            }
                        }
                    }
                    ReplyMascot {
                        id: closingMascot
                        objectName: "replyEndMascot_" + messageRow.index
                        selectionController: chatSelection
                        width: Character.id === "doubao" ? Theme.icon(72) : 56
                        visible: !modelData._loading && !messageRow.compactionNotice && messageRow.index === conversation.count - 1 && modelData.role === "assistant" && !modelData.error && (modelData.text || "").trim().length > 0 && !pane.running && (pane.turnStatus.state === "finished" || modelData.stopReason === "stop")
                        x: 33
                    }
                }
            }
            Item {
                anchors.fill: parent
                visible: bodyLoader.status !== Loader.Ready
                ActivitySpinner {
                    x: 33
                    y: 16
                    running: pane.current && parent.visible && !rowShell.modelData._loadError
                }
                ActionButton {
                    x: 33
                    y: 16
                    visible: !!rowShell.modelData._loadError
                    text: I18n.t("重新加载消息")
                    glyph: "refresh-cw"
                    onClicked: pane.messageModel.retryPage(rowShell.index)
                }
            }
        }
    }

    ChatSelection {
        id: chatSelection
        anchors.fill: conversation
        view: conversation
        enabled: pane.current && !pane.blocked
        retainedView: true
        sessionActive: pane.current
        workspace: pane.workspace
    }
}
