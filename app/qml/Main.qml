import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import QtQuick.Window

ApplicationWindow {
    id: window
    objectName: "mainWindow"
    readonly property var appWindow: window
    readonly property var sharedRequestInspector: requestInspector
    readonly property var conversation: conversationHost.currentPane ? conversationHost.currentPane.view : emptyConversation
    readonly property bool chatWheelScrolling: !!conversationHost.currentPane && conversation.scrollDirection !== 0
    onChatWheelScrollingChanged: backend.sessionPreview.setWheelScrolling(chatWheelScrolling)
    readonly property var chatSelection: conversationHost.currentPane ? conversationHost.currentPane.selection : emptySelection
    ListView { id: emptyConversation; visible: false; property bool followTail: true; property bool restoring: false }
    ChatSelection { id: emptySelection; visible: false; view: emptyConversation }
    width: 1320; height: 860
    minimumWidth: 1060; minimumHeight: 700
    visible: !backend.loginStartup.background
    title: "Umeko"
    font.family: Theme.fontFamily
    color: Theme.bg
    flags: Qt.Window | Qt.FramelessWindowHint
    property string page: "chat"
    readonly property var settingsPage: settingsLoader.item
    property bool settingsPreload: false
    Timer { id: settingsPreloadTimer; interval: 800; onTriggered: window.settingsPreload = true }
    onFrameSwapped: if (!settingsPreload && !settingsPreloadTimer.running) settingsPreloadTimer.start()
    property bool searchVisible: false
    property bool searchFocusPending: false
    property int searchHighlightRow: -1
    function openConversationSearch() {
        cancelSidebarSelection(); page = "chat"; searchVisible = true; searchFocusPending = true
    }
    function closeConversationSearch(clear) {
        if (clear) searchPane.reset()
        searchVisible = false
        searchFocusPending = false
        composer.focusInput()
    }
    onActiveChanged: if (!active && searchVisible) closeConversationSearch(false)
    Timer { id: searchHighlightTimer; interval: 2000; onTriggered: window.searchHighlightRow = -1 }
    Timer { interval: 16; repeat: true; running: window.searchVisible && window.searchFocusPending
        onTriggered: if (!sidebarWidthMotion.moving) { searchPane.focusSearch(); window.searchFocusPending = false } }
    Connections { target: backend.chatSearch
        id: searchJumps
        property var pendingJump: null
        // A newly selected host attaches its ListView on a frame boundary.
        // Wait for that attachment and initial layout before navigating away
        // from the bottom; a callLater can still run while its count is zero.
        property var jumpWaiter: FrameAnimation {
            running: searchJumps.pendingJump !== null
            onTriggered: searchJumps.finishJump()
        }
        function finishJump() {
            const pending = pendingJump
            if (!pending) return
            if (backend.conversationToken !== pending.key
                    || backend.messageModel.openGeneration !== pending.generation) {
                pendingJump = null
                return
            }
            const pane = conversationHost.currentPane
            if (!pane || pane.viewKey !== pending.key || !pane.renderReady
                    || pane.concealed || pane.view.restoring
                    || conversationHost.pendingGeneration >= 0)
                return
            pendingJump = null
            pane.view.jumpToMessage(pending.row)
            window.searchHighlightRow = pending.row
            searchHighlightTimer.restart()
        }
        function onJumpReady(row, entryId) {
            window.page = "chat"; window.searchVisible = false
            chatCover.cancel()
            pendingJump = row >= 0 ? {row: row, key: backend.conversationToken,
                                      generation: backend.messageModel.openGeneration} : null
        }
    }
    Loader {
        id:petWindowLoader;objectName:"desktopPetWindowLoader"
        active:backend.desktopPlugins.pet.visible
        sourceComponent:Component { DesktopPetWindow { pet:backend.desktopPlugins.pet } }
    }
    Loader {
        id:petReminderWindowLoader;objectName:"desktopPetReminderWindowLoader"
        active:false
        sourceComponent:Component { DesktopPetReminderWindow { pet:backend.desktopPlugins.pet } }
    }
    Connections {
        target:backend.desktopPlugins.pet
        function onRemindersRequested() {
            if(petReminderWindowLoader.item)petReminderWindowLoader.item.present()
            else petReminderWindowLoader.active=true
        }
        function onRestoreRequested() { window.showNormal();window.raise();window.requestActivate() }
        function onSettingsRequested() {
            window.showNormal();window.raise();window.requestActivate()
            window.settingsTab=3;window.page="settings"
            settingsPage.openPluginManagement("desktop-pet")
        }
    }
    readonly property bool mediaOverlayActive: imageViewer.visible || chatDrop.containsDrag
    property int settingsTab: 0
    property string notification: ""
    property string avatarChatKey: String(Math.random())
    property string pendingSidebarId: ""
    property string pendingSidebarKind: ""
    property string pendingSidebarTitle: ""
    property int sidebarToken: 0
    property bool sidebarPrepared: false
    readonly property bool sidebarSwitching: pendingSidebarId.length > 0
    function cancelSidebarSelection() {
        sidebarToken++; pendingSidebarId = ""
        backend.sessionPreview.cancel(); chatCover.cancel()
    }
    function selectSidebar(row) {
        if (row.kind === "coworkType") {
            backend.cowork.toggleType(row.typeId)
            return
        }
        if (row.kind === "coworkDraft") {
            cancelSidebarSelection()
            page = "chat"
            backend.cowork.openDraft(row.instanceId)
            return
        }
        if (row.selected && !sidebarSwitching && (row.kind === "session" || !backend.activeSession)) { window.page = "chat"; return }
        backend.sessionPreview.cancel(); sidebarToken++
        pendingSidebarKind = row.kind; pendingSidebarTitle = row.title; pendingSidebarId = row.id
        sidebarPrepared = false
        window.page = "chat"
        // Warm panes already contain their controls and text layouts.
        const cached = backend.cachedConversationToken(row.id)
        if (cached && conversationHost.panes[cached]) chatCover.cancel()
        else chatCover.begin()
        if (pendingSidebarKind === "project") {
            sidebarPrepared = true
            Qt.callLater(window.commitSidebarSelection)
        } else {
            // Start the background read on selection. Committing the view
            // stays queued so later selections can supersede this one.
            backend.sessionPreview.prepare(pendingSidebarId, sidebarToken)
        }
    }
    function commitSidebarSelection() {
        if (!sidebarSwitching || !sidebarPrepared) return
        const token = sidebarToken
        let ok = true
        if (pendingSidebarKind === "project") backend.openProject(pendingSidebarId)
        else ok = backend.sessionPreview.activate(token)
        if (token !== sidebarToken) return
        pendingSidebarId = ""
        if (!ok) { window.notification = I18n.t("暂时无法打开所选聊天，请重试"); toastTimer.restart() }
        // A retained conversation was never covered; it appears directly.
        if (chatCover.loading) chatCover.contentReady()
    }
    Connections {
        target: backend.sessionPreview
        function onReady(token, ok) {
            if (token !== window.sidebarToken || !window.sidebarSwitching) return
            if (ok) {
                window.sidebarPrepared = true
                // Let the prepared result finish notifying its listeners
                // before activation changes the current conversation.
                Qt.callLater(window.commitSidebarSelection)
            }
            else { window.pendingSidebarId = ""; chatCover.contentReady() }
        }
    }
    Timer {
        id: recentTranscriptPrefetch
        interval: 900
        onTriggered: backend.sessionPreview.prefetchRecent()
    }
    Connections {
        target: backend
        function onJobDone(name, result) {
            if (name === "index" && result.ok)
                recentTranscriptPrefetch.restart()
        }
    }
    property real webPreferredWidth: 0
    readonly property real webMinimumWidth: 320
    readonly property real chatMinimumWidth: 640
    readonly property bool previewSidebarCollapsed: webPane.opened && page === "chat" && width - Math.min(sidebarPreferredWidth, sidebarMaximumWidth) < chatMinimumWidth + webMinimumWidth
    readonly property bool sidebarLayoutCollapsed: !searchVisible && (sidebarCollapsed || previewSidebarCollapsed)
    readonly property real webMaximumWidth: Math.max(webMinimumWidth, mainArea.width - chatMinimumWidth)
    function showChatWidthLimitHint() {
        const text = Character.scene("layout.tooNarrow", "")
        if (welcome.visible) { welcomeMascot.say(text); return }
        const row = conversation.itemAtIndex(conversation.count-1)
        const mascot = row ? row.replyMascot : null
        if (mascot && mascot.visible) {
            const point = mascot.mapToItem(conversation,0,0)
            if (point.y >= 0 && point.y+mascot.height <= conversation.height) { mascot.say(text); return }
        }
        widthLimitMascot.say(text)
    }
    property real sidebarPreferredWidth: backend.sidebarWidth
    property bool sidebarCollapsed: backend.sidebarCollapsed
    readonly property real sidebarMinimumWidth: 200
    readonly property real sidebarCollapseThreshold: 140
    readonly property real sidebarMaximumWidth: Math.min(480, width - 760)
    property bool sidebarCollapseHintPending: false
    function showSidebarCollapseHint() {
        if (!sidebarCollapseHintPending || !sidebarCollapsed || sidebarWidthMotion.moving) return
        sidebarCollapseHintPending = false
        sidebarToggle.flashCollapseHint()
    }
    function saveSidebarLayout() {
        backend.saveSidebarLayout(Math.round(sidebarPreferredWidth), sidebarCollapsed)
        sidebarPreferredWidth = backend.sidebarWidth
        sidebarCollapsed = backend.sidebarCollapsed
    }
    function toggleSidebar() {
        sidebarCollapseHintPending = false; sidebarToggle.stopCollapseHint()
        sidebarCollapsed = !sidebarCollapsed; saveSidebarLayout()
    }
    function settings(tab) {
        settingsTab = tab === 2 ? 1 : tab === 4 || tab === 7 ? 3 : tab
        page = "settings"
        if (tab === 7) Qt.callLater(() => settingsPage.openPluginManagement())
    }
    function openCowork() {
        closeConversationSearch(false)
        cancelSidebarSelection()
        modelPopup.close()
        subagentMatrix.close()
        page = "chat"
        backend.cowork.toggle()
    }
    function editCoworkType(id, folder) {
        coworkEditorLoader.pendingFolder = folder || ""
        coworkEditorLoader.active = true
        coworkEditorLoader.item.begin(id)
    }
    function createCoworker(source, folder) {
        coworkSessionLoader.active = true
        coworkSessionLoader.item.beginInstance(source || "", folder || "", "", "create")
    }
    function manageCoworker(id, action) {
        coworkSessionLoader.active = true
        coworkSessionLoader.item.beginInstance("", "", id, action)
    }
    readonly property bool coworkEmpty: backend.cowork.active && !backend.cowork.activeRole
    function startChat() {
        cancelSidebarSelection()
        if (backend.cowork.active) {
            searchVisible = false
            page = "chat"
            createCoworker("", "")
        } else {
            workspacePicker.openForConversation()
        }
    }
    function startProjectChat(row) { cancelSidebarSelection(); backend.openProject(row.id); backend.newSession(); if (row.collapsed) backend.toggleProject(row.id); page = "chat"; composer.focusInput() }
    function focusChatInput() {
        if (window.visibility === Window.Minimized) window.showNormal()
        window.raise(); window.requestActivate(); composer.focusInput(); dropFocusTimer.restart()
    }
    function acceptChatFiles(urls) { const accepted = backend.addAttachments(JSON.stringify(urls)); if (accepted) { modelPopup.close(); focusChatInput() }; return accepted }
    function attachChatFile(path) { backend.attachChatboxFile(path); imageViewer.close(); focusChatInput() }
    function attachChatUrl(url) { backend.attachChatboxUrl(url); focusChatInput() }
    function previewChatWeb(item) {
        const url = backend.normalizeWebUrl(item.url || item.path || "")
        if (!url) return
        backend.openWebPreview(url, item.title || item.name || "")
    }
    function previewChatDocument(item, sourceWidget) { if (backend.openExternalHtml(item.path)) return; window.page = "chat"; webPane.showDocument(item, sourceWidget || "") }
    function showSubagentGroup(agents, anchor) {
        if (subagentMatrix.desiredOpen && subagentMatrix.parent === anchor) { subagentMatrix.close(); return }
        subagentMatrix.agents = agents; subagentMatrix.parent = anchor; subagentMatrix.open()
    }
    function previewChatImage(item, siblings) {
        if (item.kind === "web") { previewChatWeb(item); return }
        const info = item.url && item.preview !== undefined ? item : backend.chatboxFileInfo(item.path)
        if (["markdown", "code", "text"].includes(info.kind)) { previewChatDocument(info); return }
        if (info.kind === "image" && info.preview) imageViewer.show(info, siblings || [info])
        else backend.openChatboxPath(item.path, false)
    }
    Timer { id: dropFocusTimer; interval: 80; onTriggered: { backend.activateChatWindow(); composer.focusInput() } }
    readonly property bool conversationVisible: page === "chat" && visible && visibility !== Window.Minimized && active
    onPageChanged: if (page !== "chat") {
        cancelSidebarSelection()
        webPane.dismiss()
    }
    onConversationVisibleChanged: backend.setConversationVisible(conversationVisible)
    Component.onCompleted: backend.setConversationVisible(conversationVisible)
    Shortcut { sequence: "Ctrl+N"; onActivated: window.startChat() }
    Shortcut { sequence: "Ctrl+K"; onActivated: window.openConversationSearch() }
    Shortcut { sequence: "Ctrl+S"; enabled: window.page === "chat" && !window.coworkEmpty && !chatCover.visible && !webPane.subagentInputFocused && !webPane.pluginInputFocused; onActivated: composer.sendMessage(true) }
    Shortcut { sequence: "Ctrl+,"; onActivated: window.settings(0) }
    Shortcut { sequence: "Ctrl+B"; onActivated: window.toggleSidebar() }
    Shortcut { sequences: [StandardKey.Copy]; enabled: chatSelection.activeFocus && chatSelection.hasSelection; onActivated: Qt.callLater(chatSelection.copy) }
    Shortcut { sequences: [StandardKey.SelectAll]; enabled: chatSelection.activeFocus; onActivated: chatSelection.selectAll() }
    Shortcut { sequence: "Escape"; enabled: !composer.slashVisible && !workspacePicker.visible && backend.pendingApproval.id === undefined && backend.desktopPlugins.hostServices.pendingApproval.id === undefined && !imageViewer.visible; onActivated: { if (window.searchVisible) window.closeConversationSearch(false); else if (window.page === "settings") window.page = "chat"; else modelPopup.close() } }
    Connections { target: backend; function onToast(message) { window.notification = message; toastTimer.restart() }
        function onViewChanged() { window.avatarChatKey = String(Math.random()); if (backend.desktopPlugins.page.id !== "global-agents") webPane.dismiss() }
        function onWebRequested(url, title) { if (backend.desktopSettings.webDisplay === "external") backend.openWebPreview(url,title); else {window.page = "chat"; webPane.submit(url, title)} }
        function onDesktopSettingsChanged() { if (backend.desktopSettings.webDisplay === "external" && (webPane.mode === "web" || webPane.mode === "document" && backend.documentPreview.state.fileType === "html")) webPane.dismiss() }
        function onDocumentRequested(path, title, kind) { window.previewChatDocument({path:path, title:title, kind:kind}) }
        function onWidgetDocumentRequested(path, title, kind, widget) { window.previewChatDocument({path:path, title:title, kind:kind}, widget) } }
    Connections { target: backend; function onLayoutChanged() { window.sidebarPreferredWidth = backend.sidebarWidth; window.sidebarCollapsed = backend.sidebarCollapsed } }
    Timer { id: toastTimer; interval: 4200; onTriggered: window.notification = "" }
    RequestDetails { id: requestInspector }
    Connections { target: backend; function onRequestDetailsRequested(identifier) { requestInspector.show(identifier) } }
    Loader {
        id: coworkSessionLoader
        active: false
        sourceComponent: CoworkSessionDialog {
            parent: Overlay.overlay
            service: backend.cowork
            onNewTypeRequested: folder => window.editCoworkType("", folder)
            onConfigured: {
                window.page = "chat"
                Qt.callLater(composer.focusInput)
            }
            onClosed: Qt.callLater(() => { if (coworkSessionLoader.item && !coworkSessionLoader.item.visible) coworkSessionLoader.active = false })
        }
    }
    Loader {
        id: coworkEditorLoader
        property string pendingFolder: ""
        active: false
        sourceComponent: CoworkEditor {
            parent: Overlay.overlay
            service: backend.cowork
            onSaved: (identifier, created) => {
                if (created) window.createCoworker(identifier, coworkEditorLoader.pendingFolder)
            }
            onClosed: Qt.callLater(() => { if (coworkEditorLoader.item && !coworkEditorLoader.item.visible) coworkEditorLoader.active = false })
        }
    }
    Connections {
        target: backend.cowork
        function onCreateRequested(template, folder) { window.createCoworker(template, folder) }
        function onTaskRequested(identifier) {
            window.cancelSidebarSelection()
            coworkSessionLoader.active = true
            coworkSessionLoader.item.begin(identifier)
        }
    }
    FolderDialog { id: folderDialog; title: I18n.t("选择工作目录"); onAccepted: workspacePicker.chooseLocalUrl(selectedFolder.toString()) }
    WorkspacePicker {
        id: workspacePicker
        allowRemote: backend.desktopSettings.remoteWorkspaceEnabled === true
        onBrowseLocalRequested: folderDialog.open()
        onWorkspaceSelected: {
            window.searchVisible = false
            window.page = "chat"
            Qt.callLater(composer.focusInput)
        }
    }
    FileDialog { id: attachmentDialog; title: I18n.t("添加文件"); fileMode: FileDialog.OpenFiles; onAccepted: window.acceptChatFiles(selectedFiles.map(url => url.toString())) }
    ImagePreview { id: imageViewer }

    Rectangle { anchors.fill: parent; color: "transparent"; border.color: Theme.line; z: 30 }
    WindowResizeHandles { anchors.fill: parent; z: 100; targetWindow: window }

    PidMotion {
        id: sidebarWidthMotion; objectName: "sidebarWidthMotion"
        targetRect: Qt.rect(0, 0, (sidebarResizeHandle.resizing ? sidebarResizeHandle.dragWidth : window.sidebarLayoutCollapsed ? 0 : Math.min(window.sidebarPreferredWidth, window.sidebarMaximumWidth)) + 1, 1)
        onMovingChanged: if (!moving) window.showSidebarCollapseHint()
    }
    Connections {
        target: backend.desktopPlugins
        function onRequested() { window.page = "chat"; webPane.showPlugin() }
        function onInputRequested() { window.focusChatInput() }
        function onImportRequested() { window.settingsTab=3;window.page="settings";Qt.callLater(()=>settingsPage.openPluginImport()) }
    }
    Connections { target: backend.subagents; function onRequested() { window.page = "chat"; webPane.showSubagent() } }
    Rectangle {
        id: sidebar; objectName: "sidebar"
        width: sidebarResizeHandle.resizing ? sidebarResizeHandle.dragWidth : Math.max(0, sidebarWidthMotion.value.width - 1)
        visible: width > 0.5; clip: true
        anchors.top: parent.top; anchors.bottom: parent.bottom
        color: Theme.sidebar
        Rectangle { width: 1; anchors.right: parent.right; height: parent.height; color: Theme.line }
        Item {
            // Keep content at its expanded width while the outer panel reveals or clips it.
            width: Math.max(window.sidebarMinimumWidth, sidebarResizeHandle.resizing ? sidebarResizeHandle.dragWidth : Math.min(window.sidebarPreferredWidth, window.sidebarMaximumWidth))
            anchors.top: parent.top; anchors.bottom: parent.bottom
            enabled: (!window.sidebarCollapsed || window.searchVisible) && !sidebarWidthMotion.moving
            TitleBarDrag { objectName: "sidebarTitleDrag"; width: parent.width; height: 20; enabled: !chatSelection.dragging; targetWindow: window }
            Item { anchors.fill: parent; visible: !window.searchVisible
            Row {
                id: sidebarActions
                x: 16; y: 24; width: parent.width - 32; height: Theme.control(42); spacing: 8
                ActionButton {
                    id: newChatAction
                    objectName: "newChatButton"
                    width: parent.width - parent.height - parent.spacing; height: parent.height
                    text: backend.cowork.active ? (backend.language === "en" ? "New coworker" : "新建 Coworker") : I18n.t("新建会话"); glyph: "plus"; hint: text
                    onClicked: window.startChat()
                    contentItem: Item {
                        Row {
                            x: 13; width: parent.width - 26; spacing: 9; anchors.verticalCenter: parent.verticalCenter
                            Glyph { name: "plus"; width: Theme.icon(18); height: Theme.icon(18); anchors.verticalCenter: parent.verticalCenter }
                            Text { font.family: Theme.fontFamily; width: Math.max(0, parent.width - Theme.icon(18) - 9); elide: Text.ElideRight; text: newChatAction.text; font.pixelSize: Theme.font(12, visible); color: Theme.ink; anchors.verticalCenter: parent.verticalCenter }
                        }
                    }
                }
                ActionButton {
                    objectName: "searchChatsButton"
                    width: height; height: parent.height
                    glyph: "search"; hint: I18n.t("搜索") + " Ctrl+K"
                    Accessible.name: I18n.t("搜索会话")
                    onClicked: window.openConversationSearch()
                }
            }
            Text { font.family: Theme.fontFamily; id: recentLabel; x: 29; y: 52 + Theme.control(42); text: backend.showArchived ? I18n.t("已归档") : backend.cowork.active ? "Coworkers" : I18n.t("项目"); font.pixelSize: Theme.font(10, visible); color: Theme.muted; font.letterSpacing: 1 }
            ActionButton { objectName: "archivedViewButton"; anchors.right: parent.right; anchors.rightMargin: backend.cowork.active ? 22 : 28 + Theme.control(26); y: recentLabel.y - 7; width: Theme.control(26); height: Theme.control(26); glyph: "archive"; quiet: true; hint: backend.showArchived ? I18n.t("返回项目") : I18n.t("查看归档会话"); onClicked: backend.toggleArchived() }
            ActionButton { objectName: "openWorkspacePickerButton"; visible: !backend.cowork.active; anchors.right: parent.right; anchors.rightMargin: 22; y: recentLabel.y - 7; width: Theme.control(26); height: Theme.control(26); glyph: "plus"; quiet: true; hint: I18n.t("打开项目文件夹"); onClicked: workspacePicker.openPicker() }
            ListView {
                id: sessionList; objectName: "projectList"
                x: 12; y: recentLabel.y + Theme.control(28); width: parent.width - 24; height: apiStatus.y - y - 16
                spacing: 2; clip: true; model: backend.cowork.active ? backend.cowork.rows : backend.projectRows
                readonly property int selectedRow: model.findIndex(row => window.sidebarSwitching ? row.id === window.pendingSidebarId && row.kind === window.pendingSidebarKind : row.selected && (row.kind === "session" || row.kind === "coworkDraft" || row.kind === "project" && !backend.activeSession))
                function rowHeight(row) { return row.kind === "project" ? 38 : row.kind === "coworkType" ? 32 : 34 }
                function syncSelection() {
                    currentIndex = selectedRow
                    sidebarHighlight.updateTarget()
                }
                onModelChanged: Qt.callLater(syncSelection)
                onSelectedRowChanged: Qt.callLater(syncSelection)
                highlightFollowsCurrentItem: false
                // A model reset briefly clears currentItem and selects row zero.
                // Derive the target from stable row data, after pending updates,
                // and let the content item handle scrolling without animation.
                Rectangle {
                    id: sidebarHighlight
                    parent: sessionList.contentItem
                    objectName: "sidebarHighlight"
                    property bool positioned: false
                    function updateTarget() {
                        const index = sessionList.selectedRow, rows = sessionList.model
                        if (index < 0 || index >= rows.length) return
                        let top = sessionList.originY
                        for (let i = 0; i < index; ++i) top += sessionList.rowHeight(rows[i]) + sessionList.spacing
                        const rowHeight = sessionList.rowHeight(rows[index])
                        sidebarHeightMotion.targetRect = Qt.rect(0, 0, 1, rowHeight)
                        if (positioned) sidebarMotion.moveTo(top)
                        else {
                            sidebarMotion.snapTo(top)
                            sidebarHeightMotion.snap()
                            positioned = true
                        }
                    }
                    function scheduleTarget() { Qt.callLater(updateTarget) }
                    Component.onCompleted: scheduleTarget()
                    Connections {
                        target: sessionList
                        function onSpacingChanged() { sidebarHighlight.scheduleTarget() }
                        function onOriginYChanged() { sidebarHighlight.scheduleTarget() }
                    }
                    width: sessionList.width; height: sidebarHeightMotion.value.height
                    radius: 7; color: Theme.surface; visible: positioned && sessionList.selectedRow >= 0 && window.page === "chat"; z: -1
                    PidYAnimator { id: sidebarMotion; objectName: "sidebarPidMotion"; target: sidebarHighlight }
                    PidMotion { id: sidebarHeightMotion; targetRect: Qt.rect(0, 0, 1, 34) }
                }

                Text { font.family: Theme.fontFamily; visible: sessionList.count === 0 && (!backend.cowork.active || backend.showArchived); x: 17; y: 8; text: backend.showArchived ? I18n.t("暂无归档会话") : I18n.t("暂无项目"); font.pixelSize: Theme.font(11, visible); color: Theme.muted }
                delegate: Item {
                    id: sidebarItem
                    required property var modelData
                    readonly property bool coworkType: modelData.kind === "coworkType"
                    readonly property bool project: modelData.kind === "project"
                    objectName: "sidebarRow_" + modelData.id
                    width: sessionList.width; height: sessionList.rowHeight(modelData)
                    Rectangle { anchors.fill: parent; radius: 7; color: projectDrop.containsDrag && projectDrop.sessionDrop && projectDrop.targetProjectId === modelData.id ? Theme.accentBg : rowMouse.containsMouse && !(window.sidebarSwitching ? window.pendingSidebarId === modelData.id : modelData.selected) ? Theme.hover : "transparent" }
                    MouseArea { id: rowMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; acceptedButtons: sidebarItem.coworkType ? Qt.LeftButton : Qt.LeftButton | Qt.RightButton; enabled: modelData.kind !== "label"
                        onEntered: if (modelData.kind === "session") backend.sessionPreview.prefetch(modelData.id)
                        onPressed: mouse => { if (mouse.button === Qt.LeftButton && modelData.kind === "session") backend.sessionPreview.prefetch(modelData.id) }
                        onClicked: mouse => { if (mouse.button === Qt.RightButton) { sidebarMenus.openFor(modelData, mapToItem(sidebarMenus, mouse.x, mouse.y)); return } window.selectSidebar(modelData) }
                    }
                    Glyph { visible: sidebarItem.coworkType || sidebarItem.project && !modelData.cowork; name: modelData.glyph || "folder"; x: 15; anchors.verticalCenter: parent.verticalCenter; width: Theme.icon(16); height: Theme.icon(16) }
                    Text {
                        font.family: Theme.fontFamily
                        x: modelData.kind === "label" ? 17 : sidebarItem.coworkType ? 40 : modelData.cowork ? 48 : 42
                        width: Math.max(0, parent.width - x - (sidebarItem.coworkType ? Theme.control(backend && backend.showArchived ? 28 : 84) + 8
                            : sidebarItem.project ? Theme.control(56) + (modelData.pinned ? Theme.icon(12) + 12 : 8)
                            : (sidebarStatus.visible ? sidebarStatus.implicitWidth + 20 + (modelData.pinned ? Theme.icon(12) + 6 : 0) : 32)))
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData.kind === "label" ? I18n.t(modelData.title) : modelData.displayTitle || modelData.title
                        elide: Text.ElideRight
                        font.pixelSize: Theme.font(modelData.kind === "label" ? 10 : 11, visible)
                        font.weight: sidebarItem.coworkType ? Font.DemiBold : Font.Normal
                        color: modelData.kind === "label" ? Theme.muted : Theme.ink
                    }
                    TaskStatus { id: sidebarStatus; objectName: "sessionStatus_" + modelData.id; anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter; compact: true; status: ({state: modelData.kind === "session" ? (modelData.running ? (modelData.outcome === "stopping" ? "stopping" : "running") : modelData.outcome || "") : ""}); unread: modelData.unread === true && !modelData.running }
                    Glyph { anchors.right: parent.right; anchors.rightMargin: modelData.kind === "project" ? Theme.control(56) + 4 : sidebarStatus.visible ? sidebarStatus.implicitWidth + 17 : 11; anchors.verticalCenter: parent.verticalCenter; width: Theme.icon(12); height: Theme.icon(12); name: "pin"; visible: modelData.pinned === true && !modelData.running && !modelData.unread && !(rowMouse.containsMouse) }
                    Accessible.role: Accessible.Button
                    Accessible.name: (modelData.displayTitle || modelData.title) + (sidebarStatus.visible ? " · " + sidebarStatus.text : "")
                    ActionButton { objectName: "newProjectSession_" + modelData.id; anchors.right: parent.right; anchors.rightMargin: Theme.control(28); anchors.verticalCenter: parent.verticalCenter; width: Theme.control(28); height: Theme.control(28); quiet: true; glyph: "plus"; visible: sidebarItem.project && !backend.showArchived; hint: I18n.t("新增会话"); onClicked: window.startProjectChat(modelData) }
                    Loader {
                        active: sidebarItem.coworkType && !backend.showArchived
                        anchors.right: parent.right; anchors.rightMargin: Theme.control(28); anchors.verticalCenter: parent.verticalCenter
                        width: Theme.control(28); height: Theme.control(28)
                        sourceComponent: ActionButton {
                            objectName: "newCoworkInstance_" + modelData.typeId
                            quiet: true; glyph: "plus"
                            hint: backend.language === "en" ? "New instance" : "新建实例"
                            Accessible.name: hint
                            onClicked: window.createCoworker(modelData.typeId, "")
                        }
                    }
                    Loader {
                        active: sidebarItem.coworkType && !backend.showArchived
                        anchors.right: parent.right; anchors.rightMargin: Theme.control(56); anchors.verticalCenter: parent.verticalCenter
                        width: Theme.control(28); height: Theme.control(28)
                        sourceComponent: ActionButton {
                            objectName: "editCoworkType_" + modelData.typeId
                            quiet: true; glyph: "settings"
                            hint: backend.language === "en" ? "Configure Coworker type" : "配置 Coworker 大类"
                            Accessible.name: hint
                            onClicked: window.editCoworkType(modelData.typeId, "")
                        }
                    }
                    Loader {
                        active: modelData.cowork === true && !!modelData.path && rowMouse.containsMouse
                        anchors.fill: parent
                        sourceComponent: HoverTip { active: true; text: modelData.path || "" }
                    }
                    ActionButton {
                        objectName: sidebarItem.coworkType ? "toggleCoworkType_" + modelData.typeId : "toggleProject_" + modelData.id
                        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                        width: Theme.control(28); height: Theme.control(28); quiet: true
                        glyph: modelData.collapsed ? "chevron-right" : "chevron-down"
                        visible: sidebarItem.project || sidebarItem.coworkType
                        onClicked: {
                            if (sidebarItem.coworkType) backend.cowork.toggleType(modelData.typeId)
                            else backend.toggleProject(modelData.id)
                        }
                    }
                }
            }
            SidebarSessionDrop {
                id: projectDrop; anchors.fill: parent; z: 20; listView: sessionList
            }
            Rectangle {
                anchors.fill: parent; anchors.margins: 7; radius: 10; z: 21; visible: projectDrop.containsDrag; color: projectDrop.sessionDrop ? "transparent" : Theme.accentBg; border.color: Theme.accent
                Column { anchors.horizontalCenter: parent.horizontalCenter; y: projectDrop.sessionDrop ? 12 : parent.height / 2 - height / 2; spacing: 12; Glyph { name: projectDrop.sessionDrop ? "chat" : "folder"; width: Theme.icon(26); height: Theme.icon(26); anchors.horizontalCenter: parent.horizontalCenter } Text { font.family: Theme.fontFamily; text: projectDrop.sessionDrop ? (projectDrop.targetProjectTitle ? I18n.t("导入会话到 %1").replace("%1", projectDrop.targetProjectTitle) : I18n.t("导入 JSONL 会话")) : I18n.t("打开项目文件夹"); color: Theme.accent; font.pixelSize: Theme.font(12, visible) } }
            }
            Item {
                id: apiStatus; objectName: "apiProxySidebarStatus"; visible: backend.serverRunning
                x: 26; anchors.bottom: coworkButton.visible ? coworkButton.top : settingsButton.top; anchors.bottomMargin: 9; width: parent.width - 52; height: 29
                Rectangle { x: 1; y: 10; width: 6; height: 6; radius: 3; color: "#72a783" }
                Text { font.family: Theme.fontFamily; x: 17; y: 5; width: Math.max(0, apiPort.x - x - 8); elide: Text.ElideRight; text: I18n.t("API 代理运行中"); color: Theme.muted; font.pixelSize: Theme.font(10, visible) }
                Text { id: apiPort; anchors.right: parent.right; y: 5; text: ":" + backend.config.server.port; color: Theme.muted; font.pixelSize: Theme.font(10, visible); font.family: "Consolas" }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: window.settings(1) }
            }
            ActionButton {
                id: coworkButton; objectName: "openCoworkButton"
                x: settingsButton.x; anchors.bottom: settingsButton.top; anchors.bottomMargin: 4
                width: settingsButton.width; height: Theme.control(40); quiet: true
                visible: backend.desktopSettings.coworkEnabled
                Accessible.name: "Cowork"
                hint: backend.language === "en" ? "Cowork (experimental)" : "Cowork（实验版）"
                onClicked: window.openCowork()
                background: Rectangle {
                    radius: 8
                    color: backend.cowork.active ? Theme.accentBg : coworkButton.interactionHovered ? Theme.hover : "transparent"
                }
                contentItem: Item {
                    RowLayout {
                        anchors.left: parent.left; anchors.leftMargin: 16
                        anchors.right: parent.right; anchors.rightMargin: 16
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 10
                        Glyph { name: "spark"; color: backend.cowork.active ? Theme.accent : Theme.muted; Layout.preferredWidth: Theme.icon(18); Layout.preferredHeight: Theme.icon(18) }
                        Text { text: "Cowork"; font.family: Theme.fontFamily; font.pixelSize: Theme.font(12); color: Theme.ink; Layout.fillWidth: true; elide: Text.ElideRight }
                        ExperimentalBadge {
                            objectName: "coworkSidebarExperimentalBadge"
                            Layout.alignment: Qt.AlignVCenter
                        }
                    }
                }
            }
            ActionButton {
                id: settingsButton; objectName: "settingsButton"
                x: 12; anchors.bottom: parent.bottom; anchors.bottomMargin: 17; width: parent.width - 24; height: Theme.control(44); quiet: true
                onClicked: window.page === "settings" ? window.page = "chat" : window.settings(0)
                contentItem: Item { Row { x: 16; spacing: 12; anchors.verticalCenter: parent.verticalCenter
                    Glyph { name: "settings"; width: Theme.icon(18); height: Theme.icon(18) }
                    Text { font.family: Theme.fontFamily; text: I18n.t("设置"); color: Theme.ink; font.pixelSize: Theme.font(12, visible); anchors.verticalCenter: parent.verticalCenter }
                } }
                AppUpdateBadge { anchors.right: parent.right; anchors.rightMargin: 16; anchors.verticalCenter: parent.verticalCenter }
            }
            }
            ConversationSearch {
                id: searchPane; anchors.fill: parent; visible: window.searchVisible
                onBackRequested: window.closeConversationSearch(false)
                onDismissRequested: window.closeConversationSearch(false)
                onNewChatRequested: window.startChat()
                onResultRequested: row => { window.closeConversationSearch(false); chatCover.begin(); backend.chatSearch.open(row) }
            }
        }
    }

    MouseArea {
        id: sidebarResizeHandle; objectName: "sidebarResizeHandle"
        x: sidebar.width - width / 2; y: 5; width: 14; height: window.height - 10; z: 40
        // A PID target change must not hide the active handle and cancel its grab.
        visible: resizing || !window.sidebarCollapsed && !sidebarWidthMotion.moving; enabled: !chatSelection.dragging
        cursorShape: Qt.SizeHorCursor; hoverEnabled: true; preventStealing: true
        readonly property bool resizing: sidebarGesture.active
        readonly property real dragWidth: sidebarGesture.dragWidth
        PanelResizeGesture {
            id: sidebarGesture
            minimumWidth: window.sidebarMinimumWidth; maximumWidth: window.sidebarMaximumWidth
            collapseThreshold: window.sidebarCollapseThreshold
        }
        function finishResize(collapse) {
            if (!resizing) return
            if (collapse) {
                // Preserve the last committed width for the next expansion.
                window.sidebarCollapseHintPending = true
                window.sidebarCollapsed = true
            } else {
                window.sidebarPreferredWidth = sidebarGesture.settledWidth
            }
            sidebarGesture.end()
            window.saveSidebarLayout()
            window.showSidebarCollapseHint()
        }
        onPressed: mouse => {
            sidebarGesture.begin(mapToItem(window.contentItem, mouse.x, mouse.y).x, sidebar.width)
            window.sidebarCollapseHintPending = false; sidebarToggle.stopCollapseHint()
            sidebarWidthMotion.snap()
        }
        onPositionChanged: mouse => {
            if (!pressed || !resizing) return
            sidebarGesture.move(mapToItem(window.contentItem, mouse.x, mouse.y).x)
            sidebarWidthMotion.snap()
        }
        onReleased: finishResize(sidebarGesture.collapseReady)
        onCanceled: finishResize(false)
        Rectangle { width: 2; height: parent.height; anchors.horizontalCenter: parent.horizontalCenter; color: parent.containsMouse || parent.pressed ? Theme.accent : "transparent"; opacity: 0.5 }
    }

    Item {
        id: mainArea; objectName: "mainArea"
        TapHandler { acceptedButtons: Qt.LeftButton; onPressedChanged: if (pressed && window.searchVisible) window.closeConversationSearch(false) }
        anchors.left: sidebar.right; anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom
        Item {
            id: header; height: 72; width: parent.width
            TitleBarDrag { objectName: "mainTitleDrag"; anchors.fill: parent; enabled: !chatSelection.dragging; targetWindow: window }
            Row { x: 20; anchors.verticalCenter: parent.verticalCenter; spacing: 10
                ActionButton {
                    id: sidebarToggle; objectName: "toggleSidebarButton"; glyph: "layout"; quiet: true
                    width: Theme.control(30); height: Theme.control(30)
                    hint: window.sidebarCollapsed ? I18n.t("展开侧栏（Ctrl+B）") : I18n.t("收起侧栏（Ctrl+B）")
                    Accessible.name: window.sidebarCollapsed ? I18n.t("展开侧栏") : I18n.t("收起侧栏")
                    property real collapseHint: 0
                    function flashCollapseHint() { collapseHintPulse.restart() }
                    function stopCollapseHint() { collapseHintPulse.stop(); collapseHint = 0 }
                    background: Rectangle {
                        radius: 8
                        color: sidebarToggle.interactionHovered ? Theme.hover : Qt.alpha(Theme.accent, sidebarToggle.collapseHint * 0.16)
                        border.color: Qt.alpha(Theme.accent, sidebarToggle.collapseHint * 0.55)
                    }
                    SequentialAnimation {
                        id: collapseHintPulse; objectName: "sidebarCollapseHintPulse"; loops: 2
                        NumberAnimation { target: sidebarToggle; property: "collapseHint"; from: 0; to: 1; duration: 180; easing.type: Easing.InOutSine }
                        NumberAnimation { target: sidebarToggle; property: "collapseHint"; from: 1; to: 0; duration: 260; easing.type: Easing.InOutSine }
                        onStopped: sidebarToggle.collapseHint = 0
                    }
                    onClicked: window.toggleSidebar()
                }
                Text {
                    font.family: Theme.fontFamily
                    text: window.page === "chat" ? (backend.cowork.active ? "Cowork" : I18n.t("工作空间")) : I18n.t("偏好设置")
                    color: coworkHeaderOverview.containsMouse && coworkHeaderOverview.enabled ? Theme.ink : Theme.muted
                    font.pixelSize: Theme.font(11, visible)
                    anchors.verticalCenter: parent.verticalCenter
                    MouseArea {
                        id: coworkHeaderOverview
                        objectName: "coworkHeaderOverview"
                        anchors.fill: parent; anchors.margins: -6
                        enabled: window.page === "chat" && backend.cowork.active && !window.coworkEmpty
                        hoverEnabled: enabled
                        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: { window.cancelSidebarSelection(); backend.cowork.showOverview() }
                    }
                }
                Text { visible: window.page !== "chat" || !window.coworkEmpty; font.family: Theme.fontFamily; text: "/"; color: Theme.line; font.pixelSize: Theme.font(12, visible); anchors.verticalCenter: parent.verticalCenter }
                Text {
                    visible: window.page !== "chat" || !window.coworkEmpty
                    font.family: Theme.fontFamily
                    text: {
                        if (window.page !== "chat")
                            return [I18n.t("账号与供应商"), I18n.t("API 代理服务"), I18n.t("API 代理服务"), "Agent", "Agent", I18n.t("外观"), I18n.t("关于"), I18n.t("Umeko 插件管理")][window.settingsTab]
                        const title = window.sidebarSwitching ? window.pendingSidebarTitle : backend.sessionTitle
                        const prefix = backend.cowork.active ? backend.cowork.roleName + " · " : ""
                        return prefix + (title || I18n.t("新会话"))
                    }
                    color: Theme.ink; font.pixelSize: Theme.font(11, visible)
                    width: 225; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter
                }
            }
            Row { id: windowControls; anchors.right: parent.right; anchors.rightMargin: 14; anchors.top: parent.top; anchors.topMargin: 18; spacing: 2
                WindowControlButton { objectName:"minimizeWindowButton";operation:"minimize"; hint: I18n.t("最小化"); onClicked: window.showMinimized() }
                WindowControlButton { objectName:"maximizeWindowButton";operation:"maximize";maximized:window.visibility===Window.Maximized; hint: I18n.t("最大化"); onClicked: window.visibility === Window.Maximized ? window.showNormal() : window.showMaximized() }
                WindowControlButton { objectName:"closeToTrayButton";operation:"close"; hint: I18n.t("收起到托盘"); onClicked: window.close() }
            }
            ActionButton {
                id: quickOcrButton; objectName: "openQuickOcr"
                visible: window.page === "chat" && backend.cowork.active && backend.cowork.role.typeId === "ocr"
                anchors.right: windowControls.left; anchors.rightMargin: 12; anchors.verticalCenter: windowControls.verticalCenter
                quiet: true; glyph: "eye"
                text: backend.language === "en" ? "Local OCR" : "本地 OCR"
                hint: backend.language === "en" ? "Extract text without uploading the image" : "本地提取文字，不上传图片"
                onClicked: {
                    if (quickOcrLoader.item) quickOcrLoader.item.showDialog()
                    else quickOcrLoader.active = true
                }
            }
            SubagentIndicator { id: subagentIndicator; anchors.right: quickOcrButton.visible ? quickOcrButton.left : windowControls.left; anchors.rightMargin: 13; anchors.verticalCenter: windowControls.verticalCenter; visible: window.page === "chat" && backend.subagents.activeCount > 0 }
        }

        Loader {
            id: quickOcrLoader
            active: false
            sourceComponent: QuickOcrDialog { parent: Overlay.overlay; service: backend.quickOcr }
            onLoaded: item.showDialog()
        }

        Item {
            id: chatPage; objectName: "chatPage"; anchors.top: header.bottom; anchors.bottom: parent.bottom; width: parent.width - (window.page === "chat" ? webPane.animatedWidth : 0)
            visible: window.page === "chat"
            opacity: visible ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 180 } }
            Loader {
                id: coworkOverviewLoader
                active: window.coworkEmpty
                anchors.fill: parent; z: 110
                sourceComponent: CoworkOverview {
                    objectName: "coworkEmptyState"
                    service: backend.cowork
                    onCreateRequested: typeId => window.createCoworker(typeId, "")
                    onEditTypeRequested: typeId => window.editCoworkType(typeId, "")
                    onOpenInstanceRequested: instanceId => {
                        window.cancelSidebarSelection()
                        window.page = "chat"
                        backend.cowork.openRole(instanceId)
                    }
                }
            }
            Item {
                anchors.fill: parent; visible: Theme.yanami; clip: true
                Rectangle { width: parent.width * 0.9; height: width; radius: width / 2; x: parent.width * 0.45; y: -height * 0.55; opacity: 0.38; gradient: Gradient { GradientStop { position: 0; color: "#ccdfff" } GradientStop { position: 1; color: "#f4f7ff" } } }
                Rectangle { width: parent.width * 0.55; height: width; radius: width / 2; x: -width * 0.45; y: parent.height * 0.6; color: "#e2eaff"; opacity: 0.5 }
                Repeater { model: [{x:0.17,y:0.16,size:12},{x:0.82,y:0.30,size:17},{x:0.27,y:0.65,size:9},{x:0.73,y:0.73,size:11}]
                    Glyph { required property var modelData; x: parent.width * modelData.x; y: parent.height * modelData.y; width: modelData.size; height: modelData.size; name: "spark"; opacity: 0.28 }
                }
                CharacterArt { objectName: "yanamiWatermark"; anchors.fill: parent; fallbackSource: "../icons/yanami-chat-watermark.png"; artwork: Character.asset("background", fallbackSource); fillMode: Image.PreserveAspectCrop; horizontalAlignment: Image.AlignHCenter; verticalAlignment: Image.AlignVCenter; mipmap: true; opacity: 0.055 }
            }
            Item {
                id: welcome; width: Math.min(parent.width - 70, 620); height: welcomeMascot.height + 60
                x: composer.x + (composer.width - width) / 2; anchors.verticalCenter: parent.verticalCenter; anchors.verticalCenterOffset: -119
                visible: conversationHost.revealPending ? conversationHost.heldWelcome : backend.messageCount === 0
                WelcomeMascot { id: welcomeMascot; anchors.horizontalCenter: parent.horizontalCenter; portraitIndex: backend.portrait }
                Connections { target: backend; function onViewChanged() { welcomeMascot.reset() } }
                Text { font.family: Theme.fontFamily; objectName: "welcomeGreeting"; anchors.horizontalCenter: parent.horizontalCenter; y: welcomeMascot.height + 21; width: parent.width; text: welcomeMascot.reactionText || welcomeMascot.rareGreeting || Character.greeting(I18n.t(backend.greeting), welcomeMascot.portraitIndex); color: Theme.yanami ? Theme.accent : Theme.muted; font.pixelSize: Theme.font(14, visible); horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; lineHeight: 1.35 }
            }

            Item {
                id: conversationHost
                objectName: "conversationHost"
                property var panes: ({})
                property var paneOrder: []
                property var currentPane: null
                property int retainedCount: 0
                property string parkedTailKey: ""
                // The previous pane (or the welcome page) stays visible until the
                // newly activated pane has positioned its first screen.
                property var heldPane: null
                property bool heldWelcome: false
                property int pendingGeneration: -1
                property string pendingKey: ""
                property int fillGeneration: -1
                property string fillKey: ""
                readonly property bool revealPending: !!currentPane && currentPane.concealed
                x: chatWidth.conversationLeft
                Binding on width {
                    value: chatPage.width - chatWidth.conversationLeft - chatWidth.conversationRight
                    when: !conversation.visible || !sidebarWidthMotion.moving || sidebarResizeHandle.resizing
                    restoreMode: Binding.RestoreNone
                }
                anchors.top: parent.top; anchors.topMargin: 20; anchors.bottom: composer.top; anchors.bottomMargin: 24
                property bool welcomeShown: true
                function deactivate() {
                    pendingGeneration = -1
                    fillGeneration = -1
                    welcomeShown = welcome.visible
                    if (!currentPane) return
                    // Keep the outgoing pane drawn without a gap, so its text
                    // and code colours stay exactly as they were.
                    if (!welcomeShown) currentPane.holding = true
                    currentPane.deactivate()
                }
                function releaseBodies(pane) {
                    pane.renderReady = false
                    pane.view.releaseGroups()
                }
                function park(pane) {
                    pane.holding = false
                    if (pane.current) return
                    if (!pane.view.followTail || !pane.renderReady) {
                        releaseBodies(pane)
                        return
                    }
                    // Preserve the last tail for a quick return. More idle
                    // views retain their models and measured layouts, while
                    // Qt releases the native text nodes and textures.
                    const previous = panes[parkedTailKey]
                    if (previous && previous !== pane && !previous.current)
                        releaseBodies(previous)
                    parkedTailKey = pane.viewKey
                }
                function release() {
                    if (heldPane) park(heldPane)
                    heldPane = null
                    heldWelcome = false
                }
                function reveal() {
                    if (currentPane) {
                        currentPane.view.forceLayout()
                        if (currentPane.view.followTail)
                            currentPane.view.pinTail()
                        currentPane.concealed = false
                        fillKey = currentPane.viewKey
                        fillGeneration = currentPane.renderGeneration
                    }
                    release()
                    // Keep recent native controls for quick reversals. The
                    // longer-lived cache owns the models and measured heights.
                    for (const key of paneOrder.slice(0, -3)) evict(key)
                }
                function stage() {
                    const key = backend.conversationToken
                    if (key === parkedTailKey) parkedTailKey = ""
                    const previous = currentPane
                    let pane = panes[key]
                    if (!pane) {
                        pane = conversationComponent.createObject(conversationHost, {
                            viewKey:key, messageModel:backend.messageModel, renderReady:false
                        })
                        if (!pane) return
                        panes[key] = pane
                        retainedCount = Object.keys(panes).length
                    }
                    const at = paneOrder.indexOf(key)
                    if (at >= 0) paneOrder.splice(at, 1)
                    paneOrder.push(key)
                    if (heldPane && heldPane !== previous && heldPane !== pane) park(heldPane)
                    heldPane = null
                    if (previous && previous !== pane && previous.holding) heldPane = previous
                    else if (previous && previous !== pane) park(previous)
                    pane.holding = false
                    heldWelcome = welcomeShown && previous !== pane
                    currentPane = pane
                    pane.concealed = true
                    pane.current = true
                    pane.view.restoring = true
                    // Attachment, queue and status controls set the viewport
                    // height before a new ListView receives its row model.
                    pendingKey = key
                    pendingGeneration = pane.renderGeneration
                }
                function activate(key, generation) {
                    if (backend.conversationToken !== key || backend.messageModel.openGeneration !== generation)
                        return
                    const pane = panes[key]
                    if (!pane || pane !== currentPane)
                        return
                    pane.renderReady = true
                    pane.activate()
                    if (!pane.view.restoring || pane.view.firstScreenPositioned)
                        reveal()
                }
                FrameAnimation {
                    running: conversationHost.pendingGeneration >= 0 || conversationHost.revealPending || conversationHost.fillGeneration >= 0
                    onTriggered: {
                        const host = conversationHost
                        if (host.pendingGeneration >= 0) {
                            const generation = host.pendingGeneration
                            host.pendingGeneration = -1
                            host.activate(host.pendingKey, generation)
                        } else if (host.revealPending && (!host.currentPane.view.restoring || host.currentPane.view.firstScreenPositioned)) {
                            conversationHost.reveal()
                        } else if (host.fillGeneration >= 0) {
                            const generation = host.fillGeneration
                            const key = host.fillKey
                            host.fillGeneration = -1
                            const pane = host.panes[key]
                            if (pane && pane === host.currentPane && key === backend.conversationToken
                                    && generation === backend.messageModel.openGeneration)
                                pane.finishOpening(generation)
                        }
                    }
                }
                function evict(key) {
                    const pane = panes[key]
                    if (!pane) return
                    if (heldPane === pane) release()
                    if (parkedTailKey === key) parkedTailKey = ""
                    if (currentPane === pane) currentPane = null
                    delete panes[key]
                    const at = paneOrder.indexOf(key)
                    if (at >= 0) paneOrder.splice(at, 1)
                    retainedCount = Object.keys(panes).length
                    pane.release()
                    if (pane.messageModel) pane.messageModel.trimRetainedHistory()
                    pane.destroy()
                }
                Component.onCompleted: {
                    backend.enableFirstFrameStaging()
                    stage()
                }
                Connections { target: backend
                    function onViewAboutToChange() { conversationHost.deactivate() }
                    function onViewChanged() { conversationHost.stage() }
                    function onConversationEvicted(key) { conversationHost.evict(key) }
                    function onConversationViewsClosing() {
                        for (const key of Object.keys(conversationHost.panes)) conversationHost.evict(key)
                    }
                }
                Component {
                    id: conversationComponent
                    ConversationPane { anchors.fill: parent; openAtBottom: true; window: appWindow; requestInspector: sharedRequestInspector; blocked: chatCover.visible }
                }
            }

            ReplyMascot {
                id: widthLimitMascot; objectName: "chatWidthLimitMascot"
                x: composer.x+33; y: Math.max(0,composer.y-height-12); z: 50
                visible: reaction.length > 0
            }
            Connections { target: backend; function onViewChanged() { widthLimitMascot.reset() } }

            QuestionNavigator {
                anchors.right: parent.right
                anchors.top: conversationHost.top; anchors.bottom: conversationHost.bottom
                view: conversation; enabled: !chatCover.visible; z: 20
            }
            ActionButton {
                id: latestMessages; objectName: "latestMessagesButton"
                readonly property real distanceFromBottom: Math.max(0, conversation.originY + conversation.contentHeight - conversation.height - conversation.contentY)
                readonly property bool offered: conversation.visible && !conversation.followTail && !conversation.restoring && !chatCover.visible && distanceFromBottom > Math.max(Theme.control(160), conversation.height * 0.65)
                anchors.horizontalCenter: composer.horizontalCenter; anchors.bottom: composer.top; anchors.bottomMargin: Theme.control(12)
                z: 35; implicitHeight: Theme.control(31)
                text: I18n.t("最新消息"); glyph: "arrow-down"
                opacity: offered ? 1 : 0; visible: opacity > 0.01; enabled: offered
                Behavior on opacity { NumberAnimation { duration: 140 } }
                background: Rectangle { radius: height / 2; color: latestMessages.interactionHovered ? Theme.hover : Theme.surface; border.color: Theme.line }
                onClicked: conversation.jumpToLatest()
            }

            Composer {
                id: composer; objectName: "composer"
                enabled: !chatCover.visible && !window.coworkEmpty
                x: chatWidth.composerLeft; anchors.bottom: parent.bottom
                anchors.bottomMargin: Math.max(57, Math.max(footerActions.height, desktopPluginMenu.height) + Theme.control(10) + 13) + (retryStatus.visible ? retryStatus.implicitHeight + 6 : 0)
                width: parent.width - chatWidth.composerLeft - chatWidth.composerRight
                onOpenModels: modelPopup.toggle()
                onChooseFiles: attachmentDialog.open()
                onMessageSent: if (!conversation.followTail) conversation.jumpToLatest()
            }
            NetworkRetry { id: retryStatus; anchors.left: composer.left; anchors.top: composer.bottom; anchors.topMargin: 6; width: composer.width }
            ChatWidthControls { id: chatWidth; anchors.fill: parent; z: 25; enabled: !chatCover.visible && !imageViewer.visible }
            ChatFileDrop { id: chatDrop; anchors.fill: parent; z: 70; enabled: !chatCover.visible; chatWindow: window }
            ChatLoadingOverlay {
                id: chatCover; anchors.fill: parent; z: 50; view: conversation
                contentHeld: conversationHost.revealPending
                onRevealed: if (window.page === "chat") composer.focusInput()
            }
            Row { id: footerActions; x: composer.x + (composer.width - width) / 2; anchors.bottom: parent.bottom; anchors.bottomMargin: 13; spacing: 8
                ActionButton { height: Theme.control(28); quiet: true; text: "Agent"; glyph: "sliders"; onClicked: window.settings(3) }
                ActionButton { objectName: "forkSessionButton"; visible: backend.messageCount > 0 && backend.sessionBackend !== "dsh"; enabled: !backend.busy; height: Theme.control(28); quiet: true; text: I18n.t("分支"); glyph: "chat-fork"; onClicked: backend.forkSession() }
            }
            DesktopPluginMenu {
                id: desktopPluginMenu
                readonly property bool docked: webPane.opened && chatPage.width - composer.x - composer.width < width + Theme.control(24)
                readonly property bool docking: pluginDockMotion.moving
                anchors.right: parent.right; anchors.bottom: parent.bottom
                anchors.rightMargin: 12 + Math.max(0, pluginDockMotion.value.x); anchors.bottomMargin: 12; z: 45
                onManageRequested: window.settings(7)
            }
            PidMotion {
                id: pluginDockMotion
                targetRect: Qt.rect(desktopPluginMenu.docked ? Math.max(0, chatPage.width - composer.x - composer.width - 12) : 0, 0, 1, 1)
            }
        }

        WebPane {
            id: webPane
            visible: window.page === "chat" && animatedWidth > 0.5
            anchors.right: parent.right; anchors.top: header.bottom; anchors.bottom: parent.bottom
            preferredWidth: Math.max(window.webMinimumWidth, Math.min(window.webMaximumWidth, webResizeHandle.resizing ? webResizeHandle.dragWidth : window.webPreferredWidth > 0 ? window.webPreferredWidth : Math.min(540, Math.max(350, parent.width * 0.46))))
            resizing: webResizeHandle.resizing
            blocked: window.page !== "chat" || !window.visible || window.visibility === Window.Minimized || window.mediaOverlayActive || modelPopup.visible || (subagentMatrix.visible && (subagentMatrix.desiredOpen || subagentMatrix.animating)) || subagentIndicator.popupVisible || desktopPluginMenu.popupVisible || backend.pendingApproval.id !== undefined || backend.desktopPlugins.hostServices.pendingApproval.id !== undefined
        }

        MouseArea {
            id: webResizeHandle; objectName: "webPaneResizeHandle"
            x: webPane.x - 4; width: 8; anchors.top: header.bottom; anchors.bottom: parent.bottom; z: 40
            visible: resizing || webPane.visible && webPane.opened && !webPane.moving
            enabled: !webPane.blocked && !chatSelection.dragging
            cursorShape: Qt.SizeHorCursor; hoverEnabled: true; preventStealing: true
            readonly property bool resizing: webGesture.active
            readonly property real dragWidth: webGesture.dragWidth
            PanelResizeGesture {
                id: webGesture; direction: -1
                minimumWidth: window.webMinimumWidth; maximumWidth: window.webMaximumWidth
                onMaximumExceeded: window.showChatWidthLimitHint()
            }
            function finishResize(collapse) {
                if (!resizing) return
                if (collapse) {
                    if (window.webPreferredWidth <= 0) window.webPreferredWidth = webGesture.pressWidth
                    webPane.dismiss()
                } else window.webPreferredWidth = webGesture.settledWidth
                webGesture.end()
            }
            onPressed: mouse => {
                webGesture.begin(mapToItem(window.contentItem,mouse.x,mouse.y).x,webPane.width)
                webPane.snapWidth()
            }
            onPositionChanged: mouse => {
                if (!pressed || !resizing) return
                webGesture.move(mapToItem(window.contentItem,mouse.x,mouse.y).x)
                webPane.snapWidth()
            }
            onReleased: finishResize(webGesture.collapseReady)
            onCanceled: finishResize(false)
            Rectangle { anchors.horizontalCenter: parent.horizontalCenter; width: 2; height: parent.height; color: parent.containsMouse || parent.pressed ? Theme.accent : "transparent"; opacity: 0.5 }
        }

        // Settings are built after the first frame, in idle frame time. Opening
        // them before that finishes completes the remaining work at once.
        Loader {
            id: settingsLoader
            objectName: "settingsPageLoader"
            anchors.top: header.bottom; anchors.bottom: parent.bottom; width: parent.width
            active: window.settingsPreload || window.page === "settings"
            asynchronous: window.page !== "settings"
            sourceComponent: Component {
                SettingsPage {
                    objectName: "settingsPage"
                    visible: window.page === "settings"
                    tab: window.settingsTab
                    onTabSelected: value => window.settingsTab = value
                    onBack: window.page = "chat"
                }
            }
        }
    }

    ModelPopup {
        id: modelPopup
        parent: composer.modelAnchor
        heightLimit: window.height - 128
        onConfigure: { window.settings(0) }
        onDismissed: Qt.callLater(function() { if (window.page === "chat" && !modelPopup.desiredOpen && !window.mediaOverlayActive) composer.focusInput() })
    }
    SubagentMatrix { id: subagentMatrix; parent: Overlay.overlay }
    Connections { target: backend; function onViewChanged() { subagentMatrix.close() } }
    ApprovalDialog { parent: Overlay.overlay }
    ApprovalDialog { objectName: "widgetHostApproval"; actionPrefix: "widgetHost_"; parent: Overlay.overlay; approvalBackend: backend.desktopPlugins.hostServices }
    SidebarMenus {
        id: sidebarMenus; objectName: "sidebarMenus"; parent: Overlay.overlay; anchors.fill: parent
        onCoworkInstanceRequested: (id, action) => window.manageCoworker(id, action)
    }
    Rectangle {
        z: 100; anchors.horizontalCenter: mainArea.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 27
        width: Math.min(toastLabel.implicitWidth + 40, 750); height: toastLabel.implicitHeight + 24; radius: 10
        color: Theme.ink; visible: window.notification !== ""
        opacity: visible ? 1 : 0
        Text { font.family: Theme.fontFamily; id: toastLabel; anchors.centerIn: parent; text: I18n.t(window.notification); color: Theme.bg; font.pixelSize: Theme.font(12, visible); width: Math.min(implicitWidth, 710); wrapMode: Text.Wrap }
    }
}
