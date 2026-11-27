import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    objectName: "channelPage"
    readonly property var adapter: backend.channels
    readonly property var board: adapter.channel
    readonly property var execution: adapter.execution
    readonly property bool split: !!execution.id
    readonly property string channelId: board.id || ""
    readonly property string childId: execution.id || ""
    readonly property string savedChildDraft: execution.draft || ""
    onChildIdChanged: if (childEditor) childEditor.text = savedChildDraft
    onSavedChildDraftChanged: if (childEditor && childEditor.text !== savedChildDraft)
        childEditor.text = savedChildDraft
    property real restoreY: 0
    property string acceptId: ""

    function tr(zh, en) { return backend.language === "en" ? en : zh }
    function state(code) {
        switch (code) {
        case "closed": return tr("已验收 · 只读", "Accepted · Read-only")
        case "review": return tr("待验收", "Ready for review")
        case "completed": return tr("已完成", "Completed")
        case "accepted": return tr("已接单", "Accepted")
        case "interrupted": case "stopped": case "aborted": return tr("已中断", "Interrupted")
        case "failed": case "error": return tr("失败", "Failed")
        case "cancelled": return tr("已取消", "Cancelled")
        case "running": return tr("进行中", "In progress")
        case "sending": return tr("发送中", "Sending")
        case "queued": return tr("已排队", "Queued")
        default: return tr("待处理", "Pending")
        }
    }
    function role(code) {
        switch (code) {
        case "general-purpose": return tr("通用执行者", "General-purpose worker")
        case "Explore": return tr("调研执行者", "Exploration worker")
        case "Plan": return tr("规划执行者", "Planning worker")
        default: return code || tr("子智能体", "Worker")
        }
    }
    function inspect(id) {
        if (!split) restoreY = feed.contentY
        adapter.openExecution(id)
    }
    onChannelIdChanged: {
        if (editor) editor.text = board.draft || ""
        if (feed) feed.contentY = 0
        restoreY = 0
    }
    onSplitChanged: if (!split) Qt.callLater(() => {
        if (root.split) return
        feed.forceLayout()
        // ListView includes its explicit top margin above originY. Its top is
        // negative in a fresh/archived viewport, not necessarily zero.
        const first = feed.originY - feed.topMargin
        const last = Math.max(first, feed.originY + feed.contentHeight + feed.bottomMargin - feed.height)
        feed.contentY = Math.max(first, Math.min(root.restoreY, last))
    })
    Component.onCompleted: editor.text = board.draft || ""

    component Label: Text {
        color: Theme.ink
        font.family: Theme.fontFamily
        font.pixelSize: Theme.font(13, visible)
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
    }
    component Pill: Rectangle {
        id: pill
        property string code: ""
        readonly property color ink: code === "failed" || code === "error" || code === "interrupted" ? Theme.danger
            : ["completed", "closed", "review"].includes(code) ? (Theme.dark ? "#82dcb0" : "#24714d") : Theme.accent
        implicitWidth: stateLabel.implicitWidth + 20; implicitHeight: stateLabel.implicitHeight + 10
        radius: height / 2; color: Qt.alpha(ink, 0.13)
        Label { id: stateLabel; anchors.centerIn: parent; text: root.state(pill.code); color: pill.ink
            font.pixelSize: Theme.font(10, visible); font.weight: Font.DemiBold }
    }

    RowLayout {
        anchors.fill: parent; anchors.leftMargin: 14; anchors.rightMargin: 14; anchors.bottomMargin: 14
        spacing: root.split ? 12 : 0
        Rectangle {
            objectName: "channelExecutionPane"
            visible: root.split
            Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumWidth: root.split ? 296 : 0
            radius: 13; border.color: Theme.line; color: Theme.surface
            ColumnLayout {
                anchors.fill: parent; spacing: 0
                RowLayout {
                    Layout.fillWidth: true; Layout.margins: 15; spacing: 12
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 4
                        Label { text: root.board.status === "closed"
                                      ? root.tr("子任务执行 · 只读", "Subtask run · Read-only")
                                      : root.tr("子任务执行 · 单独对话", "Subtask run · Direct chat")
                            color: Theme.accent
                            font.weight: Font.DemiBold; font.pixelSize: Theme.font(10, visible) }
                        Label { Layout.fillWidth: true; text: root.execution.title || ""; font.weight: Font.DemiBold
                            font.pixelSize: Theme.font(18, visible); maximumLineCount: 2; elide: Text.ElideRight }
                    }
                }
                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.line }
                ListView {
                    id: executionFeed; objectName: "channelExecutionConversation"
                    Layout.fillWidth: true; Layout.fillHeight: true
                    clip: true; spacing: 12; topMargin: 14; bottomMargin: 14
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar {}
                    model: root.adapter.transcript
                    onCountChanged: if (count > 0) Qt.callLater(() => executionFeed.positionViewAtEnd())
                    delegate: Item {
                        id: runMessage
                        required property var modelData
                        readonly property bool user: modelData.role === "user"
                        width: executionFeed.width
                        height: runBubble.height
                        Rectangle {
                            id: runBubble
                            x: runMessage.user ? parent.width - width - 14 : 14
                            width: Math.min(parent.width - 29, Math.max(135, runText.implicitWidth + 22)); height: runBody.implicitHeight + 22
                            radius: 9; color: runMessage.user ? Theme.accentBg : Theme.bg; border.color: Theme.line
                            ColumnLayout {
                                id: runBody
                                x: 11; y: 11; width: parent.width - 22; spacing: 5
                                RowLayout {
                                    Layout.fillWidth: true; spacing: 8
                                    Label {
                                        color: Theme.accent; font.weight: Font.DemiBold
                                        font.pixelSize: Theme.font(10, visible)
                                        text: runMessage.user ? root.tr("我", "Me") : root.role(root.execution.role)
                                    }
                                    Label {
                                        objectName: "channelChildMessageTime"
                                        visible: !!runMessage.modelData.time
                                        text: visible ? Qt.formatDateTime(new Date(runMessage.modelData.time), "HH:mm") : ""
                                        font.pixelSize: Theme.font(10, visible); color: Theme.muted
                                    }
                                }
                                Label { id: runText; Layout.fillWidth: true; text: runMessage.modelData.text || "" }
                            }
                        }
                    }
                    Label {
                        parent: executionFeed; anchors.centerIn: parent; width: parent.width - 30
                        horizontalAlignment: Text.AlignHCenter; visible: executionFeed.count === 0
                        text: root.adapter.executionError || (root.adapter.executionLoading
                            ? root.tr("正在读取执行记录…", "Reading run…") : root.tr("暂无执行消息", "No run messages"))
                        color: root.adapter.executionError ? Theme.danger : Theme.muted
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true; Layout.leftMargin: 14; Layout.rightMargin: 14
                    Layout.bottomMargin: 12; spacing: 5
                    visible: root.split && root.board.status !== "closed"
                    Label {
                        Layout.fillWidth: true
                        text: root.adapter.executionError || (root.execution.pending
                            ? root.tr("子智能体处理中。", "The worker is responding.")
                            : !root.execution.canSend ? root.tr("原会话或授权暂不可用，可保留草稿。", "The original session or permissions are unavailable. You can keep a draft.") : "")
                        visible: !!text
                        color: root.adapter.executionError ? Theme.danger : Theme.muted
                        font.pixelSize: Theme.font(10, visible)
                    }
                    Label {
                        Layout.fillWidth: true; color: Theme.muted
                        font.pixelSize: Theme.font(10, visible)
                        text: root.tr("普通问答留在这里；只有明确的追加任务才会同步接单摘要。",
                                      "Questions stay private. Only clearly assigned tasks share an acceptance summary.")
                    }
                    Rectangle {
                        Layout.fillWidth: true; Layout.preferredHeight: childInputRow.implicitHeight + 14
                        color: Theme.surface; radius: 10
                        border.color: childEditor.activeFocus ? Theme.accent : Theme.line
                        RowLayout {
                            id: childInputRow
                            x: 7; y: 7; width: parent.width - 14; spacing: 7
                            Label {
                                color: Theme.accent; font.weight: Font.DemiBold
                                font.pixelSize: Theme.font(11, visible)
                                wrapMode: Text.NoWrap
                                text: "@" + root.role(root.execution.role)
                            }
                            TextArea {
                                id: childEditor; objectName: "channelChildDraft"
                                Layout.fillWidth: true; Layout.preferredHeight: 36
                                clip: true; color: Theme.ink; font.family: Theme.fontFamily
                                background: null; padding: 5; wrapMode: TextEdit.Wrap
                                Accessible.name: root.tr("只发给此子智能体", "Send only to this worker")
                                placeholderText: root.tr("给此子智能体发消息…", "Message this worker…")
                                Keys.onReturnPressed: event => {
                                    if (event.modifiers & (Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier)) {
                                        event.accepted = false
                                        return
                                    }
                                    if (!childEditor.inputMethodComposing && childSend.enabled) {
                                        childSend.clicked()
                                        event.accepted = true
                                    }
                                }
                                onTextChanged: if (root.childId) root.adapter.setChildDraft(root.channelId, root.childId, text)
                            }
                            ActionButton {
                                id: childSend; objectName: "channelChildSend"; glyph: "send"; primary: true
                                Layout.preferredWidth: 35; Layout.preferredHeight: 32
                                enabled: !!root.execution.canSend && childEditor.text.trim().length > 0
                                hint: root.tr("发送给此子智能体", "Send to this worker"); Accessible.name: hint
                                onClicked: root.adapter.sendToChild(root.channelId, root.childId, childEditor.text)
                            }
                        }
                    }
                }
            }
        }

        Rectangle {
            id: panel; objectName: "channelBoard"
            Layout.fillHeight: true; Layout.fillWidth: !root.split
            Layout.preferredWidth: root.split ? Math.min(460, Math.floor(root.width * 0.44)) : -1
            radius: 13; color: Theme.surface; border.color: Theme.line
            ColumnLayout {
                anchors.fill: parent; spacing: 0
                RowLayout {
                    Layout.fillWidth: true; Layout.leftMargin: 15; Layout.rightMargin: 15; Layout.topMargin: 10
                    Layout.bottomMargin: 9; spacing: 10
                    Rectangle {
                        Layout.preferredWidth: 34; Layout.preferredHeight: 34
                        radius: 9; color: Theme.accentBg
                        Glyph { anchors.centerIn: parent; name: "chat"; color: Theme.accent; width: 18; height: 18 }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 2
                        Label {
                            Layout.fillWidth: true; objectName: "channelTitle"
                            text: root.board.title || root.tr("任务 Channel", "Task Channels")
                            font.pixelSize: Theme.font(15, visible); font.weight: Font.DemiBold
                            wrapMode: Text.NoWrap; elide: Text.ElideRight
                        }
                        Label {
                            Layout.fillWidth: true; color: Theme.muted; font.pixelSize: Theme.font(10, visible)
                            wrapMode: Text.NoWrap; elide: Text.ElideRight
                            text: root.channelId
                                  ? root.board.coordinator + " · " + root.tr("协调者 · ", "Coordinator · ")
                                    + Math.max(0, (root.board.participants || 1) - 1) + root.tr(" 位子智能体", " workers")
                                  : root.tr("首次成功派单后自动创建", "Created on the first successful delegation")
                        }
                    }
                    Pill { code: root.board.status || ""; visible: !!root.channelId }
                    ActionButton {
                        objectName: "channelCloseExecution"; visible: root.split
                        glyph: "arrow-left"; text: root.tr("回到群聊", "Back to chat")
                        onClicked: root.adapter.closeExecution()
                    }
                    ActionButton {
                        objectName: "channelAcceptButton"; visible: !root.split && root.board.status === "review"
                        text: root.tr("验收", "Accept"); glyph: "check"
                        onClicked: { root.acceptId = root.channelId; acceptDialog.open() }
                    }
                }
                Flickable {
                    visible: !root.split && root.adapter.channelRows.length > 1
                    Layout.fillWidth: true; Layout.leftMargin: 15; Layout.rightMargin: 15; Layout.bottomMargin: 8
                    Layout.preferredHeight: tabRow.implicitHeight
                    clip: true; contentWidth: tabRow.implicitWidth; contentHeight: tabRow.implicitHeight
                    boundsBehavior: Flickable.StopAtBounds
                    Row {
                        id: tabRow; spacing: 6
                        Repeater {
                            model: root.adapter.channelRows
                            delegate: ItemDelegate {
                                id: tab
                                required property var modelData
                                objectName: "channelSelect_" + modelData.id
                                highlighted: modelData.id === root.channelId
                                implicitWidth: Math.min(153, tabLabel.implicitWidth + 18)
                                implicitHeight: Theme.control(25)
                                padding: 3; leftPadding: 9; rightPadding: 9
                                Accessible.name: modelData.title
                                contentItem: Label {
                                    id: tabLabel; text: tab.modelData.title; elide: Text.ElideRight
                                    wrapMode: Text.NoWrap; color: tab.highlighted ? Theme.accent : Theme.muted
                                    font.pixelSize: Theme.font(9, visible)
                                }
                                background: Rectangle { radius: 6; border.color: Theme.line
                                    color: tab.highlighted ? Theme.accentBg : tab.hovered ? Theme.hover : Theme.surface }
                                onClicked: root.adapter.select(modelData.id)
                            }
                        }
                    }
                }
                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.line }
                ListView {
                    id: feed; objectName: "channelBoardScroll"
                    Layout.fillHeight: true; Layout.fillWidth: true
                    topMargin: 16; bottomMargin: 15
                    spacing: 7; clip: true; boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar {}
                    model: root.board.messages || []
                    header: Item {
                        width: feed.width; height: root.channelId ? 24 : 0
                        RowLayout {
                            anchors.centerIn: parent
                            width: Math.min(856, parent.width - 32); spacing: 9
                            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.line }
                            Label {
                                readonly property real stamp: Number((root.board.messages || [])[0]?.time || 0)
                                text: stamp > 0 ? Qt.formatDateTime(new Date(stamp), "yyyy-MM-dd")
                                                : root.tr("任务开始", "Task started")
                                color: Theme.muted; font.pixelSize: Theme.font(10, visible)
                            }
                            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.line }
                        }
                    }
                    delegate: Item {
                        id: eventRow
                        required property var modelData
                        required property int index
                        readonly property bool progress: modelData.kind === "progress"
                        readonly property bool mine: modelData.role === "user"
                        readonly property bool worker: modelData.role === "worker"
                        readonly property var previous: index ? (root.board.messages || [])[index - 1] : null
                        readonly property bool grouped: !progress && !!previous && previous.kind !== "progress"
                            && previous.actor === modelData.actor && (!modelData.time || !previous.time
                                || modelData.time - previous.time < 300000)
                        readonly property color workerInk: modelData.ordinal % 2
                            ? (Theme.dark ? "#d2baff" : "#6945a0") : (Theme.dark ? "#9cdeff" : "#276889")
                        readonly property color actorInk: mine ? Theme.muted : worker ? workerInk
                            : Theme.dark ? "#8cdbba" : "#277b5d"
                        readonly property string actorName: mine ? root.tr("我", "Me") : worker
                            ? root.role(modelData.workerRole) + " " + modelData.ordinal : root.board.coordinator || ""
                        objectName: progress ? "" : modelData.taskId ? "channelTask_" + modelData.taskId
                            : mine && index === 0 ? "channelKickoffMessage" : !mine ? "channelCoordinatorMessage" : "channelUserMessage"
                        width: feed.width
                        height: progress ? progressRow.implicitHeight + 3 : bubbleArea.implicitHeight + (grouped ? 0 : 6)
                        Item {
                            id: lane
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: Math.min(856, parent.width - 32)
                            height: parent.height
                            RowLayout {
                                id: progressRow
                                anchors.horizontalCenter: parent.horizontalCenter
                                width: Math.min(lane.width, implicitWidth)
                                visible: eventRow.progress; spacing: 5
                                Label {
                                    Layout.fillWidth: true
                                    text: (eventRow.modelData.rework ? root.tr("返工已同步", "Rework synced") : root.tr("委派", "Delegation"))
                                          + " · " + root.state(eventRow.modelData.status)
                                          + (eventRow.modelData.text ? " · " + eventRow.modelData.text : "")
                                          + (eventRow.modelData.artifactNames?.length ? " · " + eventRow.modelData.artifactNames.join("、") : "")
                                    wrapMode: Text.NoWrap; elide: Text.ElideRight
                                    color: Theme.muted; font.pixelSize: Theme.font(10, visible)
                                }
                            }
                            Rectangle {
                                visible: !eventRow.progress && !eventRow.grouped
                                x: eventRow.mine ? lane.width - width : 0
                                y: 1; width: 29; height: 29; radius: 8
                                color: Qt.alpha(eventRow.actorInk, Theme.dark ? 0.26 : 0.13)
                                Label {
                                    anchors.centerIn: parent
                                    text: eventRow.mine ? root.tr("我", "Me")
                                         : eventRow.worker ? String(eventRow.modelData.ordinal)
                                         : eventRow.actorName.slice(0, 1)
                                    font.pixelSize: Theme.font(11, visible)
                                    font.weight: Font.DemiBold; color: eventRow.actorInk
                                }
                            }
                            ColumnLayout {
                                id: bubbleArea
                                visible: !eventRow.progress
                                width: Math.max(100, Math.min(lane.width - 42, Math.floor(lane.width * 0.80)))
                                x: eventRow.mine ? lane.width - width - 38 : 38
                                spacing: 3
                                Label {
                                    Layout.alignment: eventRow.mine ? Qt.AlignRight : Qt.AlignLeft
                                    Layout.maximumWidth: bubbleArea.width; visible: !eventRow.grouped
                                    text: eventRow.actorName + (eventRow.modelData.time
                                         ? "  " + Qt.formatDateTime(new Date(eventRow.modelData.time), "HH:mm") : "")
                                    color: eventRow.actorInk; wrapMode: Text.NoWrap; elide: Text.ElideRight
                                    font.pixelSize: Theme.font(10, visible); font.weight: Font.DemiBold
                                }
                                Rectangle {
                                    id: chatBubble
                                    Layout.alignment: eventRow.mine ? Qt.AlignRight : Qt.AlignLeft
                                    Layout.preferredWidth: Math.min(bubbleArea.width, Math.max(28, bubbleText.implicitWidth + 22))
                                    Layout.preferredHeight: bubbleText.implicitHeight + 15
                                    radius: 10
                                    color: eventRow.mine ? Theme.accentBg : Theme.dark ? Qt.alpha("#d5e1ff", 0.12) : "#eef2f8"
                                    Label {
                                        id: bubbleText; objectName: "channelMessageText"
                                        x: 11; y: 7; width: parent.width - 22
                                        text: (eventRow.modelData.mentionId ? "@" + eventRow.modelData.mentionName + " "
                                            + root.tr("用户给我派了追加任务：", "The user assigned me an additional task: ") : "")
                                            + (eventRow.modelData.text || "")
                                            + (eventRow.modelData.mentionId ? "\n" + root.state(eventRow.modelData.status) : "")
                                            + (eventRow.modelData.mentionId && eventRow.modelData.artifactCount
                                                ? "\n" + root.tr("已核验产物：", "Verified outputs: ")
                                                    + eventRow.modelData.artifactCount : "")
                                        wrapMode: Text.Wrap
                                        color: Theme.ink
                                    }
                                }
                                Flow {
                                    Layout.fillWidth: true; Layout.preferredHeight: implicitHeight
                                    visible: eventRow.worker
                                    spacing: 5
                                    Repeater {
                                        model: eventRow.modelData.artifacts || []
                                        delegate: ItemDelegate {
                                            id: fileChip
                                            required property var modelData
                                            objectName: "channelArtifact_" + modelData.id
                                            width: Math.min(bubbleArea.width, fileLabel.implicitWidth + 37)
                                            height: 28; padding: 5
                                            enabled: !root.split
                                            background: Rectangle { radius: 6; border.color: Theme.line
                                                color: fileChip.hovered ? Theme.hover : Theme.surface }
                                            contentItem: RowLayout {
                                                spacing: 5
                                                Glyph { name: "file"; Layout.preferredWidth: 14; Layout.preferredHeight: 14
                                                    color: Theme.accent }
                                                Label {
                                                    id: fileLabel; Layout.fillWidth: true
                                                    text: fileChip.modelData.name; color: Theme.muted
                                                    font.pixelSize: Theme.font(10, visible)
                                                    wrapMode: Text.NoWrap; elide: Text.ElideRight
                                                }
                                            }
                                            onClicked: root.adapter.openArtifact(eventRow.modelData.taskId, modelData.id)
                                        }
                                    }
                                    ItemDelegate {
                                        id: runLink
                                        objectName: eventRow.modelData.taskId ? "channelExecution_" + eventRow.modelData.taskId : ""
                                        width: runLinkLabel.implicitWidth + 27; height: 28
                                        visible: !root.split
                                        enabled: !!eventRow.modelData.ready
                                        Accessible.name: runLinkLabel.text
                                        background: Rectangle { radius: 6; color: runLink.hovered ? Theme.accentBg : "transparent" }
                                        contentItem: Label {
                                            id: runLinkLabel; text: root.tr("查看执行 ↗", "View run ↗"); color: Theme.accent
                                            verticalAlignment: Text.AlignVCenter
                                            font.pixelSize: Theme.font(10, visible)
                                        }
                                        onClicked: root.inspect(eventRow.modelData.taskId)
                                    }
                                }
                            }
                        }
                    }
                    Label {
                        parent: feed; anchors.centerIn: parent
                        visible: !root.channelId; text: root.tr("还没有任务消息", "No task messages yet")
                        color: Theme.muted; horizontalAlignment: Text.AlignHCenter
                    }
                }
                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: composer.implicitHeight + 19
                    visible: !root.split && !!root.channelId && root.board.status !== "closed"
                    ColumnLayout {
                        id: composer; anchors.horizontalCenter: parent.horizontalCenter; y: 5
                        width: Math.min(856, parent.width - 32); spacing: 4
                        Label { Layout.fillWidth: true; color: Theme.danger
                            text: root.adapter.error || ""; visible: !!text; font.pixelSize: Theme.font(10, visible) }
                        Rectangle {
                            Layout.fillWidth: true; Layout.preferredHeight: chatComposer.implicitHeight + 14
                            radius: 10; color: Theme.surface
                            border.color: editor.activeFocus ? Theme.accent : Theme.line
                            RowLayout {
                                id: chatComposer
                                x: 7; y: 7; width: parent.width - 14; spacing: 7
                                Rectangle {
                                    Layout.preferredWidth: Math.min(composer.width * 0.35, recipient.implicitWidth + 14)
                                    Layout.preferredHeight: 27; Layout.alignment: Qt.AlignTop
                                    radius: 6; color: Theme.accentBg
                                    Label {
                                        id: recipient; anchors.fill: parent; anchors.leftMargin: 7; anchors.rightMargin: 7
                                        text: "@" + (root.board.coordinator || "")
                                        color: Theme.accent; font.weight: Font.DemiBold; font.pixelSize: Theme.font(10, visible)
                                        wrapMode: Text.NoWrap; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter
                                    }
                                }
                                TextArea {
                                    id: editor; objectName: "channelMessageDraft"
                                    Layout.fillWidth: true; Layout.preferredHeight: Math.min(93, Math.max(34, contentHeight + 10))
                                    placeholderText: root.board.canSend ? root.tr("在任务群聊里继续交代…", "Continue this task…")
                                        : root.tr("协调者暂不可用，仍可保留草稿…", "Coordinator unavailable; you can keep a draft…")
                                    Accessible.name: root.tr("发送给协调者：", "Send to coordinator: ") + (root.board.coordinator || "")
                                    wrapMode: TextEdit.Wrap; padding: 5
                                    color: Theme.ink; font.family: Theme.fontFamily; font.pixelSize: Theme.font(13, visible)
                                    background: null
                                    onTextChanged: if (root.channelId) root.adapter.setDraft(root.channelId, text)
                                }
                                ActionButton {
                                    objectName: "channelSendButton"; glyph: "send"; primary: true
                                    Layout.alignment: Qt.AlignBottom; Layout.preferredWidth: 35; Layout.preferredHeight: 32
                                    hint: root.tr("发给协调者", "Send to coordinator"); Accessible.name: hint
                                    enabled: !!root.board.canSend && editor.text.trim().length > 0
                                    onClicked: if (root.adapter.sendToCoordinator(root.channelId, editor.text)) editor.clear()
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    Dialog {
        id: acceptDialog
        objectName: "channelAcceptDialog"
        modal: true
        width: Math.min(420, root.width - 36)
        implicitWidth: width
        title: root.tr("确认验收此任务？", "Accept this task?")
        anchors.centerIn: parent
        contentItem: ColumnLayout {
            spacing: 10
            Label {
                Layout.fillWidth: true
                text: root.tr("确认后关闭任务，可以只读回看，不再接收追问。", "This closes the task for follow-ups. Its records remain readable.")
            }
            RowLayout {
                Layout.alignment: Qt.AlignRight; spacing: 8
                ActionButton { text: root.tr("取消", "Cancel"); onClicked: acceptDialog.close() }
                ActionButton {
                    objectName: "channelConfirmAccept"; text: root.tr("确认验收并关闭", "Accept and close"); primary: true
                    enabled: root.channelId === root.acceptId && root.board.status === "review"
                    onClicked: if (root.adapter.accept(root.acceptId)) acceptDialog.close()
                }
            }
        }
    }
}
