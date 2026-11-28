import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import QtCore
import "../../../app/qml" as Umeko

Rectangle {
    id: root
    objectName: "groupChat"
    required property var sdk
    required property var agents
    required property bool active
    required property bool collaborationEnabled
    readonly property bool pollingActive: active && visible && collaborationEnabled && !!root.Window.window
        && root.Window.window.visibility !== Window.Hidden && root.Window.window.visibility !== Window.Minimized
    property var sessionCandidates: null
    readonly property bool managesSessions: sessionCandidates !== null
    property var managedMember: null
    signal openAgent(string id)
    readonly property var c: sdk.colors
    readonly property real scale: sdk.scale
    readonly property var members: agents.map(agent => ({targetId: "agent:" + agent.id, name: "agent-" + agent.id}))
    property var messages: []
    property var files: []
    property var pending: ({})
    property var contextMember: null
    property var contextMessage: null
    property var contextFile: null
    property var quotedMessage: null
    property bool reading: false
    property bool refreshQueued: false
    property bool sending: false
    property bool clearing: false
    property bool hasOlder: false
    property int historyGeneration: 0
    property bool searchMode: false
    property bool searchReading: false
    property bool searchHasOlder: false
    property int searchGeneration: 0
    property var searchRows: []
    property string error: ""
    property string recipient: "all"
    property int mentionIndex: 0
    property string shownMentionQuery: ""
    ListModel { id: historyModel; dynamicRoles: true }
    ListModel { id: searchModel; dynamicRoles: true }
    readonly property string searchQuery: searchMode ? searchField.text.trim() : ""
    readonly property var shownMessages: searchQuery ? searchRows : messages
    readonly property var mentionChoices: [{id: "all", name: tr("所有人", "Everyone"), portrait: ""}].concat(
        members.map(member => {
            const agent = agentById(member.targetId)
            const name = agent.name || member.name
            const duplicate = members.some(other => other.targetId !== member.targetId && agentById(other.targetId).name === name)
            return {id: member.targetId, name: duplicate ? name + " (" + member.name + ")" : name, portrait: agent.portrait || ""}
        }))
    readonly property var selectedMention: mentionChoices.find(row => row.id === recipient) || null
    readonly property var mentionQuery: /@([^@\s]*)$/.exec(composer.text.slice(0, composer.cursorPosition))
    readonly property var suggestions: mentionQuery ? mentionChoices.filter(
        row => row.name.toLowerCase().includes(mentionQuery[1].toLowerCase())) : []
    onSuggestionsChanged: Qt.callLater(showSuggestions)
    onSearchQueryChanged: {
        searchGeneration++
        searchReading = false
        searchHasOlder = false
        searchRows = []
        searchModel.clear()
        searchDelay.restart()
        list.followLatest = true
        Qt.callLater(list.followEnd)
    }
    color: c.dark ? "#182129" : "#F3F6FA"
    radius: 14

    function tr(zh, en) { return sdk.language === "en" ? en : zh }
    readonly property var agentIndex: {
        const index = {}
        for (const agent of agents)
            index["agent:" + agent.id] = agent
        return index
    }
    function agentById(id) { return agentIndex[id] || ({}) }
    function displayName(id, fallback) {
        if (id === "user") return tr("我", "Me")
        if (id === "all") return tr("所有人", "Everyone")
        return agentById(id).name || members.find(row => row.targetId === id)?.name || fallback || tr("智能体", "Agent")
    }
    function messageText(message) {
        if (!message) return ""
        return message.text || message.files.map(file => file.name).join("\n")
    }
    function quoteLabel(message) {
        if (!message) return ""
        const author = message.authorName || displayName(message.author)
        return author + ": " + messageText(message).replace(/\s+/g, " ").trim()
    }
    function quoteMessage(message, fileIndex = -1) {
        quotedMessage = fileIndex < 0 ? message
            : Object.assign({}, message, {fileIndex, text: "", files: [message.files[fileIndex]]})
        if (message.author !== "user") {
            const member = mentionChoices.find(row => row.id === message.author)
            if (member) selectMention(member, true)
            else clearMention()
        } else composer.forceActiveFocus()
    }
    function fileAction(method, messageId, index, extra) {
        return request(method, Object.assign({messageId, index}, extra || {}))
    }
    function addFiles(items) {
        if (!items.length) return false
        const next = files.slice()
        for (const item of items) {
            if (next.some(file => file.id === item.id)) continue
            if (next.length >= 8) {
                error = tr("每条消息最多附加 8 个文件", "Attach up to 8 files per message.")
                break
            }
            next.push(item)
        }
        files = next
        composer.forceActiveFocus()
        return true
    }
    function acceptChatFiles(urls) {
        const accepted = addFiles(sdk.groupChatAttachments(urls))
        if (!accepted) error = tr("请选择本地文件", "Choose local files.")
        return accepted
    }
    function selectMention(choice, replaceQuery) {
        if (!choice) return
        if (replaceQuery && mentionQuery) {
            const end = composer.cursorPosition
            const start = end - mentionQuery[0].length
            composer.remove(start, end)
            composer.cursorPosition = start
        }
        recipient = choice.id
        mentionPopup.close()
        composer.forceActiveFocus()
    }
    function clearMention() {
        recipient = ""
        composer.forceActiveFocus()
    }
    function showSuggestions() {
        if (active && composer.activeFocus && !composer.inputMethodComposing && mentionQuery && suggestions.length) {
            const query = mentionQuery[1]
            if (!mentionPopup.opened || query !== shownMentionQuery) mentionIndex = 0
            else mentionIndex = Math.min(mentionIndex, suggestions.length - 1)
            shownMentionQuery = query
            if (!mentionPopup.opened) mentionPopup.open()
        } else {
            mentionPopup.close()
        }
    }
    function request(method, args) {
        if (!active || !collaborationEnabled) return false
        const id = sdk.call(method, args || {})
        if (!id) {
            error = tr("服务忙，请稍后重试", "The service is busy. Try again shortly.")
            return false
        }
        pending = Object.assign({}, pending, {
            [id]: {method, before: args?.before || 0, historyGeneration, searchGeneration,
                   addedSessionId: method === "groupChatAddMember" ? args.id : ""}
        })
        return true
    }
    function refresh(older) {
        if (!pollingActive || reading || clearing) return
        if (!older) refreshQueued = false
        const after = !older && messages.length ? messages[messages.length-1].id : 0
        const before = older && messages.length ? messages[0].id : 0
        reading = request("groupChatHistory", {after, before})
    }
    function refreshSoon() {
        if (!pollingActive) return
        if (reading || clearing) refreshQueued = true
        else refresh()
    }
    function refreshIfQueued() {
        if (refreshQueued) refresh()
    }
    function search(older) {
        if (!searchQuery || searchReading || clearing) return
        const before = older && searchRows.length ? searchRows[0].id : 0
        searchReading = request("groupChatSearch", {query: searchQuery, before})
    }
    function applyHistory(data, before, searching) {
        const rows = searching ? searchRows : messages
        if (before || !rows.length) {
            if (searching) searchHasOlder = data.hasOlder
            else hasOlder = data.hasOlder
        }
        const batch = data.messages
        if (!batch.length) return
        const model = searching ? searchModel : historyModel
        const oldY = list.contentY
        const oldHeight = list.contentHeight
        if (before && list.model === model) list.followLatest = false
        if (searching) searchRows = before ? batch.concat(rows) : rows.concat(batch)
        else messages = before ? batch.concat(rows) : rows.concat(batch)
        if (before) {
            for (let i = 0; i < batch.length; ++i) model.insert(i, {chatRow: batch[i]})
        } else {
            for (const row of batch) model.append({chatRow: row})
        }
        Qt.callLater(() => {
            if (list.model !== model) return
            if (before) {
                list.contentY = oldY + list.contentHeight - oldHeight
                list.followLatest = list.atYEnd
            } else list.followEnd()
        })
    }
    function send() {
        if (!sendButton.enabled) return
        sending = request("groupChatSend", {
            recipient, text: composer.text.trim(), files: files.map(file => file.url),
            quoteId: quotedMessage?.id ?? null, quoteFileIndex: quotedMessage?.fileIndex ?? null
        })
    }
    function timeLabel(index) {
        if (!shownMessages[index]) return ""
        const current = new Date(shownMessages[index].created)
        if (index > 0 && current - new Date(shownMessages[index-1].created) < 300000) return ""
        return Qt.formatDateTime(current, "MM-dd HH:mm")
    }
    onActiveChanged: {
        if (!active) {
            mentionPopup.close()
            avatarMenu.close()
            messageMenu.close()
            fileMenu.close()
            detailsPopup.close()
            clearDialog.close()
            memberPicker.close()
            memberActions.close()
            renameMember.close()
        }
    }
    onPollingActiveChanged: if (pollingActive) refreshSoon()
    Timer { interval: 900; repeat: true; running: root.pollingActive; onTriggered: root.refresh() }
    Timer { id: searchDelay; interval: 260; onTriggered: root.search() }
    Connections {
        target: root.sdk
        function onResponse(id, value) {
            const entry = root.pending[id]
            if (!entry) return
            const rest = Object.assign({}, root.pending)
            delete rest[id]
            root.pending = rest
            const method = entry.method
            if (method === "groupChatHistory") root.reading = false
            if (method === "groupChatClear") root.clearing = false
            if ((method === "groupChatHistory" || method === "groupChatClear") && root.refreshQueued)
                Qt.callLater(root.refreshIfQueued)
            if ((method === "groupChatHistory" || method === "groupChatSearch")
                    && entry.historyGeneration !== root.historyGeneration) return
            if (method === "groupChatSearch" && entry.searchGeneration !== root.searchGeneration) return
            if (method === "groupChatSearch") root.searchReading = false
            if (method === "groupChatSend") root.sending = false
            if (method === "groupChatAddMember") memberPicker.submitting = false
            if (!value.ok) {
                const message = value.error || root.tr("操作失败", "Operation failed")
                if (method === "groupChatAddMember" && memberPicker.visible) memberPicker.errorText = message
                else root.error = message
                return
            }
            const data = value.result
            if (method === "groupChatHistory" || method === "groupChatSearch") {
                root.applyHistory(data, entry.before, method === "groupChatSearch")
            } else if (method === "groupChatSend") {
                root.error = ""
                root.files = []
                root.recipient = "all"
                root.quotedMessage = null
                composer.clear()
                root.refreshSoon()
            } else if (method === "groupChatPoke") {
                root.error = ""
                root.refreshSoon()
            } else if (method === "groupChatAddMember") {
                root.error = ""
                if (root.active && memberPicker.opened) {
                    memberPicker.addedSessionId = entry.addedSessionId
                    memberPicker.close()
                }
            } else if (method === "groupChatRenameMember") {
                root.error = ""
                renameMember.close()
            } else if (method === "groupChatRemoveMember") {
                root.error = ""
                if (!root.selectedMention) root.recipient = "all"
            } else if (method === "groupChatClear") {
                root.error = ""
                root.historyGeneration++
                root.hasOlder = false
                root.messages = []
                historyModel.clear()
                root.contextMessage = null
                root.contextFile = null
                root.quotedMessage = null
                root.searchMode = false
                searchField.clear()
                root.refreshSoon()
            }
        }
    }

    component Caption: Text {
        textFormat: Text.PlainText
        font.family: Umeko.Theme.fontFamily
        color: root.c.ink
        font.pixelSize: 12 * root.scale
    }
    component QuoteSummary: RowLayout {
        id: quoteSummary
        property string summary: ""
        property bool trailingRule: false
        layoutDirection: trailingRule ? Qt.RightToLeft : Qt.LeftToRight
        spacing: 6 * root.scale
        Rectangle {
            Layout.preferredWidth: 2 * root.scale
            Layout.fillHeight: true
            radius: width / 2
            color: root.c.line
        }
        Caption {
            Layout.fillWidth: true
            text: quoteSummary.summary
            color: root.c.muted
            font.pixelSize: 11 * root.scale
            elide: Text.ElideRight
            horizontalAlignment: quoteSummary.trailingRule ? Text.AlignRight : Text.AlignLeft
        }
    }
    component Avatar: Rectangle {
        property string label: ""
        property url portrait
        implicitWidth: 33 * root.scale
        implicitHeight: implicitWidth
        radius: width / 3
        color: root.c.accentBg
        Image { anchors.fill: parent; source: parent.portrait; fillMode: Image.PreserveAspectFit; asynchronous: true }
        Caption { anchors.centerIn: parent; text: parent.label.slice(0, 1); color: root.c.accent; visible: !String(parent.portrait) }
    }
    component FileCard: ItemDelegate {
        id: card
        required property var attachment
        required property real widthLimit
        readonly property bool inlineImage: !!attachment.preview && thumbnail.status !== Image.Error
        readonly property real aspect: (attachment.pixelWidth || thumbnail.implicitWidth || 3)
            / (attachment.pixelHeight || thumbnail.implicitHeight || 2)
        signal menuRequested(point position)
        text: attachment.name
        width: Math.min(widthLimit, inlineImage ? Math.min(280, 210 * aspect) * root.scale : 250 * root.scale)
        height: inlineImage ? width / aspect : fileDetails.implicitHeight + 20 * root.scale
        hoverEnabled: true
        padding: 0
        function sizeLabel(bytes) {
            if (bytes === undefined) return ""
            if (bytes < 1024) return bytes + " B"
            if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB"
            if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + " MB"
            return (bytes / 1073741824).toFixed(1) + " GB"
        }
        background: Rectangle {
            radius: 11 * root.scale
            color: card.inlineImage ? "transparent" : card.hovered ? root.c.hover : root.c.surface
            border.color: card.inlineImage ? "transparent" : root.c.line
        }
        contentItem: Item {
            Image {
                id: thumbnail
                objectName: "groupChatSentImage"
                anchors.fill: parent
                visible: card.inlineImage
                source: card.attachment.preview || ""
                sourceSize: Qt.size(560, 420)
                asynchronous: true
                fillMode: Image.PreserveAspectFit
            }
            RowLayout {
                id: fileDetails
                anchors.fill: parent
                anchors.margins: 10 * root.scale
                visible: !card.inlineImage
                spacing: 10 * root.scale
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4 * root.scale
                    Caption {
                        Layout.fillWidth: true
                        text: card.attachment.name
                        wrapMode: Text.Wrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                        font.weight: Font.DemiBold
                    }
                    Caption {
                        text: card.sizeLabel(card.attachment.bytes)
                        visible: !!text
                        color: root.c.muted
                        font.pixelSize: 10 * root.scale
                    }
                }
                Rectangle {
                    Layout.preferredWidth: 31 * root.scale
                    Layout.preferredHeight: 36 * root.scale
                    radius: 6 * root.scale
                    color: root.c.accentBg
                    Umeko.Glyph {
                        anchors.centerIn: parent
                        width: 18 * root.scale
                        height: width
                        name: /\.(zip|7z|rar|tar|gz)$/i.test(card.attachment.name) ? "archive" : "file"
                        color: root.c.accent
                    }
                }
            }
        }
        HoverHandler { cursorShape: Qt.PointingHandCursor }
        TapHandler {
            acceptedButtons: Qt.RightButton
            onTapped: point => card.menuRequested(point.position)
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10 * root.scale
        spacing: 8 * root.scale
        RowLayout {
            id: groupHeader
            Layout.fillWidth: true
            visible: root.collaborationEnabled
            Item { Layout.fillWidth: true }
            Umeko.InputField {
                id: searchField
                objectName: "groupChatSearchField"
                Layout.preferredWidth: Math.min(Umeko.Theme.control(344), Math.max(0, groupHeader.width - detailsButton.width - 2 * groupHeader.spacing))
                Layout.preferredHeight: Umeko.Theme.control(36)
                visible: root.searchMode
                placeholderText: root.tr("查找聊天内容", "Search messages")
                Accessible.name: placeholderText
                maximumLength: 256
                leftPadding: Umeko.Theme.control(34)
                rightPadding: Umeko.Theme.control(34)
                onAccepted: { searchDelay.stop(); root.search() }
                Keys.onShortcutOverride: event => {
                    if (event.key === Qt.Key_Escape) event.accepted = true
                }
                Keys.onEscapePressed: root.searchMode = false
                Umeko.Glyph {
                    name: "search"
                    width: Umeko.Theme.icon(15); height: width
                    anchors.left: parent.left; anchors.leftMargin: Umeko.Theme.control(11)
                    anchors.verticalCenter: parent.verticalCenter
                }
                Umeko.ActionButton {
                    objectName: "groupChatCloseSearch"
                    width: Umeko.Theme.control(27); height: width
                    anchors.right: parent.right; anchors.rightMargin: Umeko.Theme.control(4)
                    anchors.verticalCenter: parent.verticalCenter
                    glyph: "x"; quiet: true
                    hint: root.tr("关闭搜索", "Close search")
                    Accessible.name: hint
                    onClicked: root.searchMode = false
                }
            }
            Umeko.ActionButton {
                id: detailsButton
                objectName: "groupChatDetailsButton"
                Layout.preferredWidth: 34 * root.scale
                Layout.preferredHeight: 31 * root.scale
                glyph: "more"
                quiet: true
                hint: root.tr("群聊详情", "Group details")
                Accessible.name: hint
                onClicked: detailsPopup.open()
            }
        }
        Caption {
            visible: !!root.error
            Layout.fillWidth: true
            text: root.error
            color: root.c.danger
            wrapMode: Text.Wrap
        }
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Caption {
                anchors.centerIn: parent
                width: parent.width - 12
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                color: root.c.muted
                visible: !root.collaborationEnabled || !root.shownMessages.length
                text: {
                    if (!root.collaborationEnabled)
                        return root.tr("请先在 Umeko Desktop 设置中开启团队协作。", "Enable Team collaboration in Umeko Desktop settings.")
                    if (!root.searchQuery) return root.tr("输入 @，开始群聊。", "Type @ to start the group chat.")
                    if (root.searchReading || searchDelay.running) return root.tr("正在查找…", "Searching…")
                    return root.tr("没有找到匹配的消息", "No matching messages")
                }
            }
            ListView {
                id: list
                objectName: "groupChatMessages"
                property bool followLatest: true
                function followEnd() {
                    if (visible && followLatest && !moving && !messageScroll.pressed) positionViewAtEnd()
                }
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: Math.min(parent.height, Math.max(96 * root.scale, contentHeight))
                clip: true
                visible: root.collaborationEnabled && root.shownMessages.length > 0
                model: root.searchQuery ? searchModel : historyModel
                spacing: 10 * root.scale
                onHeightChanged: Qt.callLater(followEnd)
                onContentHeightChanged: Qt.callLater(followEnd)
                onMovementStarted: followLatest = false
                onMovementEnded: followLatest = atYEnd
                ScrollBar.vertical: ScrollBar {
                    id: messageScroll
                    policy: ScrollBar.AsNeeded
                    onPressedChanged: if (!pressed) list.followLatest = list.atYEnd
                }
                header: Umeko.ActionButton {
                    visible: root.searchQuery ? root.searchHasOlder : root.hasOlder
                    height: visible ? implicitHeight : 0
                    anchors.horizontalCenter: parent?.horizontalCenter
                    text: root.tr("查看更早消息", "Earlier messages")
                    quiet: true
                    enabled: root.searchQuery ? !root.searchReading : !root.reading
                    onClicked: root.searchQuery ? root.search(true) : root.refresh(true)
                }
                delegate: Column {
                    id: entry
                    required property var chatRow
                    required property int index
                    readonly property var modelData: chatRow
                    readonly property bool mine: modelData.author === "user"
                    width: ListView.view.width
                    spacing: 5 * root.scale
                    Caption {
                        readonly property string label: root.timeLabel(entry.index)
                        width: parent.width
                        visible: label !== ""
                        text: label
                        color: root.c.muted
                        horizontalAlignment: Text.AlignHCenter
                        font.pixelSize: 10 * root.scale
                    }
                    Caption {
                        width: parent.width
                        visible: entry.modelData.poke
                        text: root.tr("我拍了拍 %1", "I poked %1").arg(root.displayName(entry.modelData.recipient))
                        color: root.c.muted
                        horizontalAlignment: Text.AlignHCenter
                    }
                    Row {
                        visible: !entry.modelData.poke
                        anchors.right: entry.mine ? parent.right : undefined
                        layoutDirection: entry.mine ? Qt.RightToLeft : Qt.LeftToRight
                        spacing: 8 * root.scale
                        Avatar {
                            objectName: "groupChatAvatar_" + entry.modelData.author
                            label: root.displayName(entry.modelData.author, entry.modelData.authorName)
                            portrait: root.agentById(entry.modelData.author).portrait || ""
                            MouseArea {
                                id: avatarMouse
                                anchors.fill: parent
                                enabled: !entry.mine && !!root.agentById(entry.modelData.author).id
                                acceptedButtons: Qt.LeftButton | Qt.RightButton
                                cursorShape: Qt.PointingHandCursor
                                onClicked: mouse => {
                                    const id = entry.modelData.author
                                    if (mouse.button === Qt.LeftButton) root.openAgent(id.slice(6))
                                    else {
                                        root.contextMember = root.mentionChoices.find(row => row.id === id)
                                        if (root.contextMember)
                                            avatarMenu.openAt(avatarMouse.mapToItem(avatarMenu.parent, mouse.x, mouse.y))
                                    }
                                }
                            }
                        }
                        Column {
                            spacing: 4 * root.scale
                            Caption {
                                width: Math.min(entry.width * 0.78, implicitWidth)
                                visible: !entry.mine
                                text: root.displayName(entry.modelData.author, entry.modelData.authorName)
                                elide: Text.ElideRight
                                color: root.c.muted
                            }
                            Caption {
                                anchors.right: entry.mine ? parent.right : undefined
                                visible: !entry.modelData.text && entry.modelData.files.length > 0
                                text: "@" + root.displayName(entry.modelData.recipient)
                                color: root.c.accent
                            }
                            Rectangle {
                                id: bubbleFrame
                                objectName: "groupChatBubble_" + entry.modelData.id
                                visible: !!entry.modelData.text
                                anchors.right: entry.mine ? parent.right : undefined
                                width: Math.min(entry.width * 0.78, Math.max(78 * root.scale, bubble.implicitWidth + 20 * root.scale))
                                height: bubble.implicitHeight + 16 * root.scale
                                radius: 11 * root.scale
                                color: entry.mine ? (root.c.dark ? "#245B4D" : "#C7EEDC") : root.c.surface
                                border.color: "transparent"
                                ColumnLayout {
                                    id: bubble
                                    x: 10 * root.scale
                                    y: 8 * root.scale
                                    width: parent.width - 20 * root.scale
                                    spacing: 4 * root.scale
                                    Caption {
                                        Layout.fillWidth: true
                                        text: "@" + root.displayName(entry.modelData.recipient)
                                        color: entry.mine ? (root.c.dark ? "#C5F5DD" : "#1A654F") : root.c.accent
                                        wrapMode: Text.Wrap
                                        font.weight: Font.DemiBold
                                    }
                                    Caption {
                                        Layout.fillWidth: true
                                        visible: !!entry.modelData.text
                                        text: entry.modelData.text
                                        wrapMode: Text.Wrap
                                    }
                                }
                                MouseArea {
                                    id: bubbleMouse
                                    anchors.fill: parent
                                    acceptedButtons: Qt.RightButton
                                    onClicked: mouse => {
                                        root.contextMessage = entry.modelData
                                        messageMenu.openAt(bubbleMouse.mapToItem(messageMenu.parent, mouse.x, mouse.y))
                                    }
                                }
                            }
                            Repeater {
                                model: entry.modelData.files
                                delegate: FileCard {
                                    id: card
                                    required property var modelData
                                    required property int index
                                    objectName: "groupChatFile_" + entry.modelData.id + "_" + index
                                    widthLimit: entry.width * 0.78
                                    attachment: modelData
                                    anchors.right: entry.mine ? parent.right : undefined
                                    onClicked: root.fileAction("groupChatOpenFile", entry.modelData.id, index)
                                    onMenuRequested: position => {
                                        root.contextFile = {message: entry.modelData, index}
                                        fileMenu.openAt(card.mapToItem(fileMenu.parent, position.x, position.y))
                                    }
                                }
                            }
                            QuoteSummary {
                                objectName: "groupChatQuote_" + entry.modelData.id
                                visible: !!entry.modelData.quote
                                anchors.right: entry.mine ? parent.right : undefined
                                width: Math.min(entry.width * 0.78, Math.max(bubbleFrame.width, implicitWidth))
                                summary: root.quoteLabel(entry.modelData.quote)
                                trailingRule: entry.mine
                            }
                        }
                    }
                }
            }
        }
        Rectangle {
            id: composerFrame
            Layout.fillWidth: true
            implicitHeight: controls.implicitHeight + 16 * root.scale
            visible: root.collaborationEnabled
            radius: 12 * root.scale
            color: root.c.surface
            border.color: composer.activeFocus ? root.c.accent : root.c.line
            ColumnLayout {
                id: controls
                anchors.fill: parent
                anchors.margins: 8 * root.scale
                spacing: 5 * root.scale
                Rectangle {
                    objectName: "groupChatMentionChip"
                    visible: !!root.selectedMention
                    Layout.maximumWidth: controls.width
                    implicitWidth: mentionChip.implicitWidth + 8 * root.scale
                    implicitHeight: mentionChip.implicitHeight
                    radius: 6 * root.scale
                    color: root.c.accentBg
                    RowLayout {
                        id: mentionChip
                        anchors.fill: parent
                        anchors.leftMargin: 8 * root.scale
                        spacing: 2 * root.scale
                        Caption {
                            Layout.fillWidth: true
                            text: root.selectedMention ? "@" + root.selectedMention.name : ""
                            color: root.c.accent
                            elide: Text.ElideRight
                        }
                        ToolButton {
                            objectName: "groupChatClearMention"
                            Layout.preferredWidth: 23 * root.scale
                            Layout.preferredHeight: 23 * root.scale
                            Accessible.name: root.tr("移除点名", "Remove mention")
                            contentItem: Umeko.Glyph { name: "x"; color: root.c.accent }
                            background: Rectangle { radius: 6 * root.scale; color: parent.hovered ? root.c.hover : "transparent" }
                            onClicked: root.clearMention()
                        }
                    }
                }
                Umeko.ComposerAttachments {
                    objectName: "groupChatAttachments"
                    Layout.fillWidth: true
                    visible: items.length > 0
                    items: root.files
                    onRemoveRequested: id => root.files = root.files.filter(file => file.id !== id)
                }
                ScrollView {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 64 * root.scale
                    contentWidth: availableWidth
                    Umeko.ChatInput {
                        id: composer
                        objectName: "groupChatComposer"
                        placeholderText: root.selectedMention ? root.tr("输入消息…", "Write a message…")
                            : root.tr("输入 @ 点名群聊成员", "Type @ to mention a member")
                        placeholderTextColor: root.c.muted
                        wrapMode: TextEdit.Wrap
                        color: root.c.ink
                        background: null
                        selectByMouse: true
                        font.family: Umeko.Theme.fontFamily
                        font.pixelSize: 13 * root.scale
                        onActiveFocusChanged: Qt.callLater(root.showSuggestions)
                        onInputMethodComposingChanged: Qt.callLater(root.showSuggestions)
                        Keys.onShortcutOverride: event => {
                            if (mentionPopup.opened && !composer.inputMethodComposing
                                    && [Qt.Key_Up, Qt.Key_Down, Qt.Key_Escape].includes(event.key))
                                event.accepted = true
                        }
                        onSubmitted: {
                            if (mentionPopup.opened && root.suggestions.length)
                                root.selectMention(root.suggestions[root.mentionIndex], true)
                            else root.send()
                        }
                        Keys.onPressed: event => {
                            if (composer.inputMethodComposing) return
                            if (event.matches(StandardKey.Paste) && root.addFiles(root.sdk.groupChatAttachments())) {
                                event.accepted = true
                            } else if (event.key === Qt.Key_Backspace && !event.modifiers && composer.cursorPosition === 0
                                    && composer.selectionStart === composer.selectionEnd && root.selectedMention) {
                                root.clearMention()
                                event.accepted = true
                            } else if (mentionPopup.opened && root.suggestions.length) {
                                if (event.key === Qt.Key_Escape) { mentionPopup.close(); event.accepted = true }
                                else if (event.key === Qt.Key_Down || event.key === Qt.Key_Up) {
                                    const count = root.suggestions.length
                                    root.mentionIndex = (root.mentionIndex + count + (event.key === Qt.Key_Down ? 1 : -1)) % count
                                    mentionList.positionViewAtIndex(root.mentionIndex, ListView.Contain)
                                    event.accepted = true
                                }
                            }
                        }
                    }
                }
                RowLayout {
                    objectName: "groupChatDraftQuote"
                    visible: !!root.quotedMessage
                    Layout.fillWidth: true
                    spacing: 5 * root.scale
                    QuoteSummary {
                        Layout.fillWidth: true
                        summary: root.quoteLabel(root.quotedMessage)
                    }
                    ToolButton {
                        objectName: "groupChatClearQuote"
                        Layout.preferredWidth: 23 * root.scale
                        Layout.preferredHeight: 23 * root.scale
                        Accessible.name: root.tr("移除引用", "Remove quote")
                        contentItem: Umeko.Glyph { name: "x"; color: root.c.muted }
                        background: Rectangle { radius: 6 * root.scale; color: parent.hovered ? root.c.hover : "transparent" }
                        onClicked: {
                            root.quotedMessage = null
                            composer.forceActiveFocus()
                        }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Umeko.ActionButton {
                        glyph: "smile"
                        quiet: true
                        hint: root.tr("表情", "Emoji")
                        Accessible.name: root.tr("表情", "Emoji")
                        onClicked: emojiPopup.open()
                    }
                    Umeko.ActionButton {
                        glyph: "folder"
                        quiet: true
                        hint: root.tr("发送文件", "Send file")
                        Accessible.name: root.tr("发送文件", "Send file")
                        onClicked: filePicker.open()
                    }
                    Item { Layout.fillWidth: true }
                    Umeko.ActionButton {
                        id: sendButton
                        objectName: "groupChatSend"
                        text: root.tr("发送", "Send")
                        primary: true
                        enabled: root.members.length > 0 && !!root.selectedMention && !root.sending && !root.clearing
                            && (!!composer.text.trim() || root.files.length > 0)
                        textColor: enabled ? Umeko.Theme.buttonText : root.c.muted
                        background: Rectangle {
                            radius: 8
                            color: sendButton.enabled ? root.c.accent : root.c.line
                        }
                        onClicked: root.send()
                    }
                }
            }
        }
    }

    Umeko.ChatFileDrop {
        objectName: "groupChatDropArea"
        anchors.fill: parent
        z: 5
        enabled: root.active && root.collaborationEnabled
        chatWindow: root
        overlayName: "groupChatDropOverlay"
        mascotName: "groupChatDropMascot"
        promptText: root.tr("松开发送到群聊", "Drop to attach to the group chat")
    }

    Popup {
        id: detailsPopup
        objectName: "groupChatDetails"
        parent: detailsButton
        x: parent.width - width
        y: parent.height + 5 * root.scale
        width: Math.min(282 * root.scale, root.width - 16 * root.scale)
        padding: 10 * root.scale
        margins: 8
        focus: true
        property string highlightedMember: ""

        function revealAddedMember() {
            if (!opened || !highlightedMember) return
            const index = memberRepeater.model.findIndex(member => member.id === highlightedMember)
            const item = memberRepeater.itemAt(index)
            if (!item) return
            const view = memberScroll.contentItem
            const top = item.mapToItem(view.contentItem, 0, 0).y
            if (top < view.contentY) view.contentY = top
            else if (top + item.height > view.contentY + view.height)
                view.contentY = top + item.height - view.height
        }
        onOpened: if (highlightedMember) {
            Qt.callLater(revealAddedMember)
            memberHighlight.restart()
        }
        onClosed: {
            memberHighlight.stop()
            highlightedMember = ""
        }
        Timer {
            id: memberHighlight
            interval: 2200
            onTriggered: detailsPopup.highlightedMember = ""
        }
        background: Rectangle { radius: 10; color: root.c.surface; border.color: root.c.line }
        contentItem: ColumnLayout {
            spacing: 8 * root.scale
            Caption {
                text: root.tr("群聊成员", "Group members")
                color: root.c.muted
            }
            ScrollView {
                id: memberScroll
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(memberGrid.implicitHeight, 184 * root.scale)
                contentWidth: availableWidth
                clip: true
                Flow {
                    id: memberGrid
                    width: parent.width
                    spacing: 3 * root.scale
                    Repeater {
                        id: memberRepeater
                        model: [{id: "user", name: root.displayName("user"), portrait: ""}].concat(root.mentionChoices.slice(1))
                        delegate: ItemDelegate {
                            id: memberButton
                            required property var modelData
                            objectName: "groupChatMember_" + modelData.id
                            width: 59 * root.scale
                            height: 59 * root.scale
                            padding: 3 * root.scale
                            Accessible.name: modelData.name
                            background: Rectangle {
                                radius: 6
                                color: detailsPopup.highlightedMember === memberButton.modelData.id ? root.c.accentBg
                                    : memberButton.hovered && memberButton.modelData.id !== "user" ? root.c.hover : "transparent"
                                Behavior on color { ColorAnimation { duration: 160 } }
                            }
                            contentItem: ColumnLayout {
                                spacing: 3 * root.scale
                                Avatar {
                                    Layout.alignment: Qt.AlignHCenter
                                    label: memberButton.modelData.name
                                    portrait: memberButton.modelData.portrait
                                }
                                Caption {
                                    Layout.fillWidth: true
                                    horizontalAlignment: Text.AlignHCenter
                                    text: memberButton.modelData.name
                                    font.pixelSize: 10 * root.scale
                                    color: root.c.muted
                                    elide: Text.ElideRight
                                }
                            }
                            onClicked: {
                                if (modelData.id === "user") return
                                detailsPopup.close()
                                root.openAgent(modelData.id.slice(6))
                            }
                            MouseArea {
                                id: memberContextClick
                                anchors.fill: parent
                                enabled: root.managesSessions && memberButton.modelData.id !== "user"
                                acceptedButtons: Qt.RightButton
                                onClicked: mouse => {
                                    root.managedMember = memberButton.modelData
                                    memberActions.openAt(mapToItem(memberActions.parent, mouse.x, mouse.y))
                                }
                            }
                        }
                    }
                    ItemDelegate {
                        id: addSessionMember
                        objectName: "groupChatAddMember"
                        visible: root.managesSessions
                        width: 59 * root.scale
                        height: 59 * root.scale
                        padding: 3 * root.scale
                        Accessible.name: root.tr("添加群成员", "Add group member")
                        background: Rectangle {
                            radius: 6
                            color: addSessionMember.hovered ? root.c.hover : "transparent"
                        }
                        contentItem: ColumnLayout {
                            spacing: 3 * root.scale
                            Rectangle {
                                Layout.alignment: Qt.AlignHCenter
                                implicitWidth: 32 * root.scale; implicitHeight: width
                                radius: 7; color: "transparent"; border.color: root.c.line
                                Umeko.Glyph { name: "plus"; width: 17 * root.scale; height: width; anchors.centerIn: parent }
                            }
                            Caption {
                                Layout.fillWidth: true
                                horizontalAlignment: Text.AlignHCenter
                                text: root.tr("添加", "Add")
                                font.pixelSize: 10 * root.scale
                                color: root.c.muted
                            }
                        }
                        onClicked: {
                            detailsPopup.close()
                            memberPicker.begin()
                        }
                    }
                }
            }
            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: root.c.line }
            Umeko.ActionButton {
                objectName: "groupChatStartSearch"
                Layout.fillWidth: true
                glyph: "search"
                text: root.tr("查找聊天内容", "Search messages")
                quiet: true
                onClicked: {
                    detailsPopup.close()
                    root.searchMode = true
                    Qt.callLater(() => searchField.forceActiveFocus())
                }
            }
            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: root.c.line }
            Umeko.ActionButton {
                objectName: "groupChatClearHistory"
                Layout.fillWidth: true
                glyph: "trash"
                text: root.tr("清空聊天记录", "Clear chat history")
                destructive: true
                quiet: true
                enabled: root.messages.length > 0 && !root.clearing && !root.sending
                onClicked: {
                    detailsPopup.close()
                    clearDialog.open()
                }
            }
        }
    }
    Umeko.FloatingMenu {
        id: memberActions
        objectName: "groupChatMemberActions"
        parent: root
        Umeko.ContextAction {
            objectName: "groupChatRenameMember"
            glyph: "edit"
            text: root.tr("设置群备注", "Set group nickname")
            onTriggered: {
                const id = root.managedMember?.id || ""
                renameInput.text = root.agentById(id).alias || ""
                detailsPopup.close()
                renameMember.open()
            }
        }
        Umeko.ContextAction {
            objectName: "groupChatRemoveMember"
            glyph: "trash"
            text: root.tr("移出群聊", "Remove from group")
            destructive: true
            onTriggered: if (root.managedMember) {
                root.request("groupChatRemoveMember", {id: root.managedMember.id.slice(6)})
                memberActions.close()
            }
        }
    }
    GroupMemberPicker {
        id: memberPicker
        property string addedSessionId: ""
        candidates: root.sessionCandidates || []
        english: root.sdk.language === "en"
        onMemberSelected: sessionId => {
            memberPicker.errorText = ""
            memberPicker.submitting = root.request("groupChatAddMember", {id: sessionId})
            if (!memberPicker.submitting) memberPicker.errorText = root.error
        }
        onClosed: {
            const sessionId = addedSessionId
            addedSessionId = ""
            if (sessionId && root.active && root.collaborationEnabled) {
                detailsPopup.highlightedMember = "agent:" + sessionId
                detailsPopup.open()
            }
        }
    }
    Popup {
        id: renameMember
        objectName: "groupChatRenameDialog"
        parent: root
        anchors.centerIn: parent
        width: Math.min(365 * root.scale, root.width - 20)
        focus: true; modal: true; padding: 16
        background: Rectangle { radius: 12; color: root.c.surface; border.color: root.c.line }
        onOpened: { renameInput.forceActiveFocus(); renameInput.selectAll() }
        function save() {
            if (root.managedMember) root.request("groupChatRenameMember", {
                id: root.managedMember.id.slice(6), alias: renameInput.text.trim()
            })
        }
        contentItem: ColumnLayout {
            spacing: 10 * root.scale
            Caption { text: root.tr("设置群备注", "Set group nickname"); font.weight: Font.DemiBold }
            TextField {
                id: renameInput
                objectName: "groupChatRenameInput"
                Layout.fillWidth: true
                placeholderText: root.tr("留空使用会话名称", "Leave blank to use the conversation name")
                maximumLength: 80
                onAccepted: renameMember.save()
            }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                Umeko.ActionButton { text: root.tr("取消", "Cancel"); quiet: true; onClicked: renameMember.close() }
                Umeko.ActionButton { objectName: "groupChatSaveNickname"; text: root.tr("保存", "Save"); primary: true; onClicked: renameMember.save() }
            }
        }
    }
    Popup {
        id: clearDialog
        objectName: "groupChatClearConfirmation"
        parent: root
        anchors.centerIn: parent
        width: Math.min(325 * root.scale, root.width - 16 * root.scale)
        padding: 15 * root.scale
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape
        background: Rectangle { radius: 10; color: root.c.surface; border.color: root.c.line }
        contentItem: ColumnLayout {
            spacing: 10 * root.scale
            Caption {
                text: root.tr("清空聊天记录？", "Clear chat history?")
                font.weight: Font.DemiBold
                font.pixelSize: 15 * root.scale
            }
            Caption {
                Layout.fillWidth: true
                text: root.tr("群聊里的消息将被永久删除。", "The messages in this group chat will be permanently deleted.")
                color: root.c.muted
                wrapMode: Text.Wrap
            }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                Umeko.ActionButton {
                    objectName: "groupChatCancelClear"
                    text: root.tr("取消", "Cancel")
                    quiet: true
                    onClicked: clearDialog.close()
                }
                Umeko.ActionButton {
                    objectName: "groupChatConfirmClear"
                    text: root.tr("清空", "Clear")
                    destructive: true
                    onClicked: {
                        root.clearing = root.request("groupChatClear", {confirmed: true})
                        clearDialog.close()
                    }
                }
            }
        }
    }
    Umeko.FloatingMenu {
        id: fileMenu
        objectName: "groupChatFileMenu"
        parent: root
        Umeko.ContextAction {
            objectName: "groupChatQuoteFile"
            text: root.tr("引用", "Quote")
            glyph: "quote"
            onTriggered: root.quoteMessage(root.contextFile.message, root.contextFile.index)
        }
        Umeko.ContextAction {
            objectName: "groupChatCopyFile"
            text: root.tr("复制", "Copy")
            glyph: "copy"
            onTriggered: root.fileAction("groupChatCopyFile", root.contextFile.message.id, root.contextFile.index)
        }
        Umeko.ContextAction {
            objectName: "groupChatRevealFile"
            text: root.tr("在文件管理器中显示", "Show in file manager")
            glyph: "folder"
            onTriggered: root.fileAction("groupChatRevealFile", root.contextFile.message.id, root.contextFile.index)
        }
        Umeko.ContextAction {
            objectName: "groupChatSaveFile"
            text: root.tr("另存为…", "Save as…")
            glyph: "download"
            onTriggered: {
                const target = root.contextFile
                savePicker.attachment = target
                const filename = target.message.files[target.index].name
                savePicker.selectedFile = String(savePicker.currentFolder).replace(/\/$/, "") + "/" + encodeURIComponent(filename)
                savePicker.open()
            }
        }
    }
    Umeko.FloatingMenu {
        id: messageMenu
        objectName: "groupChatMessageMenu"
        parent: root
        Umeko.ContextAction {
            objectName: "groupChatCopyMessage"
            text: root.tr("复制", "Copy")
            glyph: "copy"
            onTriggered: root.sdk.copyText(root.messageText(root.contextMessage))
        }
        Umeko.ContextAction {
            objectName: "groupChatQuoteMessage"
            text: root.tr("引用", "Quote")
            glyph: "quote"
            onTriggered: root.quoteMessage(root.contextMessage)
        }
    }
    Umeko.FloatingMenu {
        id: avatarMenu
        objectName: "groupChatAvatarMenu"
        parent: root
        Umeko.ContextAction {
            objectName: "groupChatMentionAgent"
            text: "@" + (root.contextMember?.name || "")
            onTriggered: root.selectMention(root.contextMember, false)
        }
        Umeko.ContextAction {
            objectName: "groupChatPokeAgent"
            text: root.tr("拍一拍", "Poke")
            onTriggered: if (root.contextMember) root.request("groupChatPoke", {recipient: root.contextMember.id})
        }
    }
    Popup {
        id: mentionPopup
        objectName: "groupChatMentionPopup"
        parent: composerFrame
        y: -height - 5
        width: Math.min(230 * root.scale, composerFrame.width)
        padding: 5
        implicitHeight: Math.min(6, root.suggestions.length) * 35 * root.scale + 10
        background: Rectangle { radius: 10; color: root.c.surface; border.color: root.c.line }
        contentItem: ListView {
            id: mentionList
            clip: true
            model: root.suggestions
            currentIndex: root.mentionIndex
            delegate: ItemDelegate {
                id: suggestion
                required property var modelData
                required property int index
                width: ListView.view.width
                height: 35 * root.scale
                highlighted: index === root.mentionIndex
                background: Rectangle { radius: 7; color: suggestion.highlighted || suggestion.hovered ? root.c.hover : "transparent" }
                contentItem: RowLayout {
                    Avatar { label: modelData.name; portrait: modelData.portrait; implicitWidth: 22 * root.scale }
                    Caption { text: modelData.name; Layout.fillWidth: true; elide: Text.ElideRight }
                }
                onClicked: root.selectMention(modelData, true)
            }
        }
    }
    Popup {
        id: emojiPopup
        parent: composerFrame
        y: -height - 5
        padding: 5
        background: Rectangle { radius: 10; color: root.c.surface; border.color: root.c.line }
        contentItem: GridLayout {
            columns: 5
            Repeater {
                model: ["😀", "😂", "🙂", "👍", "🎉", "🤔", "❤️", "👀", "🙏", "✅"]
                delegate: Umeko.ActionButton {
                    required property string modelData
                    text: modelData
                    quiet: true
                    onClicked: { composer.insert(composer.cursorPosition, modelData); emojiPopup.close(); composer.forceActiveFocus() }
                }
            }
        }
    }
    FileDialog {
        id: filePicker
        fileMode: FileDialog.OpenFiles
        onAccepted: root.acceptChatFiles(selectedFiles.map(file => String(file)))
    }
    FileDialog {
        id: savePicker
        objectName: "groupChatSaveDialog"
        property var attachment: null
        title: root.tr("另存为", "Save as")
        fileMode: FileDialog.SaveFile
        currentFolder: StandardPaths.writableLocation(StandardPaths.DownloadLocation)
        onAccepted: root.fileAction("groupChatSaveFile", attachment.message.id, attachment.index,
                                    {destination: String(selectedFile)})
    }
}
