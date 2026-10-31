import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import QtQuick.Window

ApplicationWindow {
    id: window
    objectName: "mainWindow"
    width: 1320; height: 860
    minimumWidth: 1060; minimumHeight: 700
    visible: true
    title: "Umeko"
    color: Theme.bg
    flags: Qt.Window | Qt.FramelessWindowHint
    property string page: "chat"
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
        function onJumpReady(row, entryId) {
            window.page = "chat"; window.searchVisible = false
            chatCover.contentReady()
            if (row >= 0) Qt.callLater(() => { conversation.jumpToMessage(row); window.searchHighlightRow = row; searchHighlightTimer.restart() })
        }
    }
    Loader {
        id:petWindowLoader;objectName:"desktopPetWindowLoader"
        active:backend.desktopPlugins.pet.visible
        sourceComponent:Component { DesktopPetWindow { pet:backend.desktopPlugins.pet } }
    }
    Connections {
        target:backend.desktopPlugins.pet
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
    property int sidebarFrames: 0
    property bool sidebarStarted: false
    property bool sidebarPrepared: false
    readonly property bool sidebarSwitching: pendingSidebarId.length > 0
    function cancelSidebarSelection() {
        sidebarToken++; pendingSidebarId = ""
        backend.sessionPreview.cancel(); chatCover.cancel()
    }
    function selectSidebar(row) {
        if (row.selected && !sidebarSwitching && (row.kind === "session" || !backend.activeSession)) { window.page = "chat"; return }
        backend.sessionPreview.cancel(); sidebarToken++
        pendingSidebarKind = row.kind; pendingSidebarTitle = row.title; pendingSidebarId = row.id
        sidebarFrames = 0; sidebarStarted = false; sidebarPrepared = false
        chatCover.begin(); window.page = "chat"
    }
    function commitSidebarSelection() {
        if (!sidebarSwitching || !sidebarPrepared || sidebarMotion.moving) return
        const token = sidebarToken
        let ok = true
        if (pendingSidebarKind === "project") backend.openProject(pendingSidebarId)
        else ok = backend.sessionPreview.activate(token)
        if (token !== sidebarToken) return
        pendingSidebarId = ""
        if (!ok) { window.notification = I18n.t("暂时无法打开所选聊天，请重试"); toastTimer.restart() }
        chatCover.contentReady()
    }
    // Present the cover before starting disk I/O. Cold reads can overlap the
    // sidebar motion; activate the latest result only after the PID settles.
    FrameAnimation {
        running: window.sidebarSwitching && !window.sidebarStarted
        onTriggered: {
            window.sidebarFrames++
            if (window.sidebarFrames < 2) return
            window.sidebarStarted = true
            if (window.pendingSidebarKind === "project") window.sidebarPrepared = true
            else backend.sessionPreview.prepare(window.pendingSidebarId, window.sidebarToken)
        }
    }
    Connections {
        target: backend.sessionPreview
        function onReady(token, ok) {
            if (token !== window.sidebarToken || !window.sidebarSwitching) return
            if (ok) window.sidebarPrepared = true
            else { window.pendingSidebarId = ""; chatCover.contentReady() }
        }
    }
    Timer { interval: 16; repeat: true; running: window.sidebarSwitching; onTriggered: window.commitSidebarSelection() }
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
    function startChat() { searchVisible = false; cancelSidebarSelection(); backend.newSession(); page = "chat"; composer.focusInput() }
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
        if (!backend.webviewAvailable) { window.notification = I18n.t("网页预览组件尚未安装或无法加载"); toastTimer.restart(); return }
        window.page = "chat"; webPane.submit(url, item.title || item.name || "")
    }
    function previewChatDocument(item) { window.page = "chat"; webPane.showDocument(item) }
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
    Shortcut { sequence: "Ctrl+S"; enabled: window.page === "chat" && !chatCover.visible && !webPane.subagentInputFocused && !webPane.pluginInputFocused; onActivated: composer.sendMessage(true) }
    Shortcut { sequence: "Ctrl+,"; onActivated: window.settings(0) }
    Shortcut { sequence: "Ctrl+B"; onActivated: window.toggleSidebar() }
    Shortcut { sequences: [StandardKey.Copy]; enabled: chatSelection.activeFocus && chatSelection.hasSelection; onActivated: Qt.callLater(chatSelection.copy) }
    Shortcut { sequences: [StandardKey.SelectAll]; enabled: chatSelection.activeFocus; onActivated: chatSelection.selectAll() }
    Shortcut { sequence: "Escape"; enabled: backend.pendingApproval.id === undefined && backend.desktopPlugins.hostServices.pendingApproval.id === undefined && !imageViewer.visible; onActivated: { if (window.searchVisible) window.closeConversationSearch(false); else if (window.page === "settings") window.page = "chat"; else modelPopup.close() } }
    Connections { target: backend; function onToast(message) { window.notification = message; toastTimer.restart() }
        function onViewChanged() { window.avatarChatKey = String(Math.random()); if (backend.desktopPlugins.page.id !== "global-agents") webPane.dismiss() }
        function onWebRequested(url, title) { window.page = "chat"; webPane.submit(url, title) }
        function onDocumentRequested(path, title, kind) { window.previewChatDocument({path:path, title:title, kind:kind}) } }
    Connections { target: backend; function onLayoutChanged() { window.sidebarPreferredWidth = backend.sidebarWidth; window.sidebarCollapsed = backend.sidebarCollapsed } }
    Timer { id: toastTimer; interval: 4200; onTriggered: window.notification = "" }
    RequestDetails { id: requestInspector }
    FolderDialog { id: folderDialog; title: I18n.t("选择工作目录"); onAccepted: backend.setWorkspace(selectedFolder.toString()) }
    FileDialog { id: attachmentDialog; title: I18n.t("添加文件"); fileMode: FileDialog.OpenFiles; onAccepted: window.acceptChatFiles(selectedFiles.map(url => url.toString())) }
    ImagePreview { id: imageViewer }

    Rectangle { anchors.fill: parent; color: "transparent"; border.color: Theme.line; z: 30 }
    WindowResizeHandles { anchors.fill: parent; z: 100; targetWindow: window }

    PidMotion {
        id: sidebarWidthMotion; objectName: "sidebarWidthMotion"
        targetRect: Qt.rect(0, 0, (sidebarResizeHandle.resizing ? sidebarResizeHandle.dragWidth : window.sidebarLayoutCollapsed ? 0 : Math.min(window.sidebarPreferredWidth, window.sidebarMaximumWidth)) + 1, 1)
        onMovingChanged: if (!moving) window.showSidebarCollapseHint()
    }
    Connections { target: backend.desktopPlugins; function onRequested() { window.page = "chat"; webPane.showPlugin() } }
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
            ActionButton {
                objectName: "searchChatsButton"
                x: 16; y: 24; width: parent.width - 32; height: Theme.control(42)
                text: I18n.t("搜索会话"); glyph: "search"; hint: I18n.t("搜索") + " Ctrl+K"
                onClicked: window.openConversationSearch()
                Text { anchors.right: parent.right; anchors.rightMargin: 13; anchors.verticalCenter: parent.verticalCenter; visible: Theme.fontScale <= 1.25; text: "Ctrl K"; color: Theme.muted; font.pixelSize: Theme.font(10) }
                contentItem: Item { Row { x: 13; width: parent.width - (Theme.fontScale <= 1.25 ? 65 : 26); spacing: 9; anchors.verticalCenter: parent.verticalCenter; Glyph { name: "search"; width: Theme.icon(18); height: Theme.icon(18) } Text { width: Math.max(0, parent.width - Theme.icon(18) - 9); elide: Text.ElideRight; text: I18n.t("搜索会话"); font.pixelSize: Theme.font(12); color: Theme.ink; anchors.verticalCenter: parent.verticalCenter } } }
            }
            Text { id: recentLabel; x: 29; y: 52 + Theme.control(42); text: backend.showArchived ? I18n.t("已归档") : I18n.t("项目"); font.pixelSize: Theme.font(10); color: Theme.muted; font.letterSpacing: 1 }
            ActionButton { objectName: "archivedViewButton"; anchors.right: parent.right; anchors.rightMargin: 28 + Theme.control(26); y: recentLabel.y - 7; width: Theme.control(26); height: Theme.control(26); glyph: "archive"; quiet: true; hint: backend.showArchived ? I18n.t("返回项目") : I18n.t("查看归档会话"); onClicked: backend.toggleArchived() }
            ActionButton { anchors.right: parent.right; anchors.rightMargin: 22; y: recentLabel.y - 7; width: Theme.control(26); height: Theme.control(26); glyph: "plus"; quiet: true; hint: I18n.t("打开项目文件夹"); onClicked: folderDialog.open() }
            ListView {
                id: sessionList; objectName: "projectList"
                x: 12; y: recentLabel.y + Theme.control(28); width: parent.width - 24; height: apiStatus.y - y - 16
                spacing: 2; clip: true; model: backend.projectRows
                currentIndex: backend.projectRows.findIndex(row => window.sidebarSwitching ? row.id === window.pendingSidebarId && row.kind === window.pendingSidebarKind : row.selected && (row.kind === "session" || row.kind === "project" && !backend.activeSession))
                highlightFollowsCurrentItem: false
                PidMotion { id: sidebarMotion; objectName: "sidebarPidMotion"; targetRect: Qt.rect(0,sessionList.currentItem ? sessionList.currentItem.y : 0,sessionList.width,sessionList.currentItem ? sessionList.currentItem.height : 34) }
                highlight: Rectangle { objectName: "sidebarHighlight"; x: sidebarMotion.value.x; y: sidebarMotion.value.y; width: sidebarMotion.value.width; height: sidebarMotion.value.height; radius: 7; color: Theme.surface; visible: sessionList.currentIndex >= 0 && window.page === "chat"; z: -1 }

                Text { visible: sessionList.count === 0; x: 17; y: 8; text: backend.showArchived ? I18n.t("暂无归档会话") : I18n.t("暂无项目"); font.pixelSize: Theme.font(11); color: Theme.muted }
                delegate: Item {
                    required property var modelData
                    objectName: "sidebarRow_" + modelData.id
                    width: sessionList.width; height: modelData.kind === "project" ? 38 : 34
                    Rectangle { anchors.fill: parent; radius: 7; color: rowMouse.containsMouse && !(window.sidebarSwitching ? window.pendingSidebarId === modelData.id : modelData.selected) ? Theme.hover : "transparent" }
                    MouseArea { id: rowMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; acceptedButtons: Qt.LeftButton | Qt.RightButton; enabled: modelData.kind !== "label"
                        onClicked: mouse => { if (mouse.button === Qt.RightButton) { sidebarMenus.openFor(modelData, mapToItem(sidebarMenus, mouse.x, mouse.y)); return } window.selectSidebar(modelData) }
                    }
                    Glyph { visible: modelData.kind === "project"; name: "folder"; x: 15; anchors.verticalCenter: parent.verticalCenter; width: Theme.icon(16); height: Theme.icon(16) }
                    Text { x: modelData.kind === "label" ? 17 : 42; width: Math.max(0, parent.width - x - (modelData.kind === "project" ? Theme.control(56) + (modelData.pinned ? Theme.icon(12) + 12 : 8) : (sidebarStatus.visible ? sidebarStatus.implicitWidth + 20 + (modelData.pinned ? Theme.icon(12) + 6 : 0) : 32))); anchors.verticalCenter: parent.verticalCenter; text: modelData.kind === "label" ? I18n.t(modelData.title) : modelData.title; elide: Text.ElideRight; font.pixelSize: Theme.font(modelData.kind === "label" ? 10 : 11); color: modelData.kind === "label" ? Theme.muted : Theme.ink }
                    TaskStatus { id: sidebarStatus; objectName: "sessionStatus_" + modelData.id; anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter; compact: true; status: ({state: modelData.kind === "session" ? (modelData.running ? (modelData.outcome === "stopping" ? "stopping" : "running") : modelData.outcome || "") : ""}); unread: modelData.unread === true && !modelData.running }
                    Glyph { anchors.right: parent.right; anchors.rightMargin: modelData.kind === "project" ? Theme.control(56) + 4 : sidebarStatus.visible ? sidebarStatus.implicitWidth + 17 : 11; anchors.verticalCenter: parent.verticalCenter; width: Theme.icon(12); height: Theme.icon(12); name: "pin"; visible: modelData.pinned === true && !modelData.running && !modelData.unread && !(rowMouse.containsMouse) }
                    Accessible.role: Accessible.Button
                    Accessible.name: modelData.title + (sidebarStatus.visible ? " · " + sidebarStatus.text : "")
                    ActionButton { objectName: "newProjectSession_" + modelData.id; anchors.right: parent.right; anchors.rightMargin: Theme.control(28); anchors.verticalCenter: parent.verticalCenter; width: Theme.control(28); height: Theme.control(28); quiet: true; glyph: "plus"; visible: modelData.kind === "project" && !backend.showArchived; hint: I18n.t("新增会话"); onClicked: window.startProjectChat(modelData) }
                    ActionButton { objectName: "toggleProject_" + modelData.id; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; width: Theme.control(28); height: Theme.control(28); quiet: true; glyph: modelData.collapsed ? "chevron-right" : "chevron-down"; visible: modelData.kind === "project"; onClicked: backend.toggleProject(modelData.id) }
                }
            }
            DropArea {
                id: projectDrop; objectName: "projectDropArea"; anchors.fill: parent; z: 20
                onEntered: drag => { drag.accepted = drag.urls.length > 0 }
                onDropped: drop => { backend.dropProjects(JSON.stringify(drop.urls.map(url => url.toString()))); drop.acceptProposedAction(); window.page = "chat" }
            }
            Rectangle {
                anchors.fill: parent; anchors.margins: 7; radius: 10; z: 21; visible: projectDrop.containsDrag; color: Theme.accentBg; border.color: Theme.accent
                Column { anchors.centerIn: parent; spacing: 12; Glyph { name: "folder"; width: Theme.icon(26); height: Theme.icon(26); anchors.horizontalCenter: parent.horizontalCenter } Text { text: I18n.t("打开项目文件夹"); color: Theme.accent; font.pixelSize: Theme.font(12) } }
            }
            Item {
                id: apiStatus; objectName: "apiProxySidebarStatus"; visible: backend.serverRunning
                x: 26; anchors.bottom: settingsButton.top; anchors.bottomMargin: 9; width: parent.width - 52; height: 29
                Rectangle { x: 1; y: 10; width: 6; height: 6; radius: 3; color: "#72a783" }
                Text { x: 17; y: 5; width: Math.max(0, apiPort.x - x - 8); elide: Text.ElideRight; text: I18n.t("API 代理运行中"); color: Theme.muted; font.pixelSize: Theme.font(10) }
                Text { id: apiPort; anchors.right: parent.right; y: 5; text: ":" + backend.config.server.port; color: Theme.muted; font.pixelSize: Theme.font(10); font.family: "Consolas" }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: window.settings(1) }
            }
            ActionButton {
                id: settingsButton; objectName: "settingsButton"
                x: 12; anchors.bottom: parent.bottom; anchors.bottomMargin: 17; width: parent.width - 24; height: Theme.control(44); quiet: true
                onClicked: window.page === "settings" ? window.page = "chat" : window.settings(0)
                contentItem: Item { Row { x: 16; spacing: 12; anchors.verticalCenter: parent.verticalCenter
                    Glyph { name: "settings"; width: Theme.icon(18); height: Theme.icon(18) }
                    Text { text: I18n.t("设置"); color: Theme.ink; font.pixelSize: Theme.font(12); anchors.verticalCenter: parent.verticalCenter }
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
                Text { text: window.page === "chat" ? I18n.t("工作空间") : I18n.t("偏好设置"); color: Theme.muted; font.pixelSize: Theme.font(11); anchors.verticalCenter: parent.verticalCenter }
                Text { text: "/"; color: Theme.line; font.pixelSize: Theme.font(12); anchors.verticalCenter: parent.verticalCenter }
                Text { text: window.page === "chat" ? (window.sidebarSwitching ? window.pendingSidebarTitle : backend.sessionTitle) : [I18n.t("账号与供应商"), I18n.t("API 代理服务"), I18n.t("API 代理服务"), "Agent", "Agent", I18n.t("外观"), I18n.t("关于"), I18n.t("Umeko 插件管理")][window.settingsTab]; color: Theme.ink; font.pixelSize: Theme.font(11); width: 225; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter }
            }
            Row { id: windowControls; anchors.right: parent.right; anchors.rightMargin: 14; anchors.top: parent.top; anchors.topMargin: 18; spacing: 2
                ActionButton { glyph: "minus"; width: Theme.control(32); height: Theme.control(30); quiet: true; hint: I18n.t("最小化"); onClicked: window.showMinimized() }
                ActionButton { glyph: "maximize"; width: Theme.control(32); height: Theme.control(30); quiet: true; hint: I18n.t("最大化"); onClicked: window.visibility === Window.Maximized ? window.showNormal() : window.showMaximized() }
                ActionButton { objectName: "closeToTrayButton"; glyph: "x"; width: Theme.control(32); height: Theme.control(30); quiet: true; hint: I18n.t("收起到托盘"); onClicked: window.close() }
            }
            SubagentIndicator { id: subagentIndicator; anchors.right: windowControls.left; anchors.rightMargin: 13; anchors.verticalCenter: windowControls.verticalCenter; visible: window.page === "chat" && backend.subagents.activeCount > 0 }
        }

        Item {
            id: chatPage; objectName: "chatPage"; anchors.top: header.bottom; anchors.bottom: parent.bottom; width: parent.width - (window.page === "chat" ? webPane.animatedWidth : 0)
            visible: window.page === "chat"
            opacity: visible ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 180 } }
            Item {
                anchors.fill: parent; visible: Theme.yanami; clip: true
                Rectangle { width: parent.width * 0.9; height: width; radius: width / 2; x: parent.width * 0.45; y: -height * 0.55; opacity: 0.38; gradient: Gradient { GradientStop { position: 0; color: "#ccdfff" } GradientStop { position: 1; color: "#f4f7ff" } } }
                Rectangle { width: parent.width * 0.55; height: width; radius: width / 2; x: -width * 0.45; y: parent.height * 0.6; color: "#e2eaff"; opacity: 0.5 }
                Repeater { model: [{x:0.17,y:0.16,size:12},{x:0.82,y:0.30,size:17},{x:0.27,y:0.65,size:9},{x:0.73,y:0.73,size:11}]
                    Glyph { required property var modelData; x: parent.width * modelData.x; y: parent.height * modelData.y; width: modelData.size; height: modelData.size; name: "spark"; opacity: 0.28 }
                }
                CharacterArt { objectName: "yanamiWatermark"; anchors.fill: parent; fallbackSource: "../icons/portraits/02.png"; artwork: Character.asset("background", fallbackSource); fillMode: Image.PreserveAspectCrop; horizontalAlignment: Image.AlignHCenter; verticalAlignment: Image.AlignVCenter; mipmap: true; opacity: 0.055 }
            }
            Item {
                id: welcome; width: Math.min(parent.width - 70, 620); height: 270
                x: composer.x + (composer.width - width) / 2; anchors.verticalCenter: parent.verticalCenter; anchors.verticalCenterOffset: -119
                visible: backend.messageCount === 0
                WelcomeMascot { id: welcomeMascot; anchors.horizontalCenter: parent.horizontalCenter; portraitIndex: backend.portrait }
                Connections { target: backend; function onViewChanged() { welcomeMascot.reset() } }
                Text { objectName: "welcomeGreeting"; anchors.horizontalCenter: parent.horizontalCenter; y: 231; width: parent.width; text: welcomeMascot.reactionText || welcomeMascot.rareGreeting || Character.greeting(I18n.t(backend.greeting), welcomeMascot.portraitIndex); color: Theme.yanami ? Theme.accent : Theme.muted; font.pixelSize: Theme.font(14); horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; lineHeight: 1.35 }
            }

            ListView {
                id: conversation; objectName: "conversation"
                property bool followTail: true
                property bool restoring: false
                property real restoreOffset: -1
                property int restoreIndex: -1
                property int restoreAttempts: 0
                property int pageAnchor: -1
                property real pageOffset: 0
                readonly property string layoutKey: width + "/" + Theme.fontScale + "/" + window.font.family
                onLayoutKeyChanged: { backend.messageModel.setLayout(layoutKey); if (!followTail && count) restoreViewport() }
                function rememberPageAnchor() {
                    if (followTail || restoring) return
                    pageAnchor = indexAt(1, contentY + 1)
                    const item = pageAnchor >= 0 ? itemAtIndex(pageAnchor) : null
                    pageOffset = item ? contentY - item.y : 0
                }
                function restorePageAnchor() {
                    if (followTail) { tailTimer.restart(); return }
                    if (pageAnchor < 0 || restoring) return
                    restoreIndex = pageAnchor; restoreOffset = pageOffset; restoreAttempts = 1; restoring = true
                    pageAnchor = -1; restoreTimer.restart()
                }
                function beginBrowsing() { tailTimer.stop(); restoreTimer.stop(); restoring = false; cancelFlick(); followTail = false }
                function jumpToMessage(row) {
                    if (row < 0 || row >= count) return
                    beginBrowsing()
                    chatSelection.clear()
                    restoring = true; restoreIndex = row; restoreOffset = 0; restoreAttempts = 0
                    restoreTimer.restart()
                }
                function scrollBy(delta) {
                    beginBrowsing()
                    const top = originY
                    const bottom = Math.max(top, originY + contentHeight - height)
                    contentY = Math.max(top, Math.min(bottom, contentY + delta))
                    if (atYEnd && !chatSelection.dragging) followTail = true
                }
                function saveViewport() {
                    if (restoring) return
                    let index = indexAt(1, contentY + 1)
                    if (index < 0) index = indexAt(1, contentY + spacing + 2)
                    const item = index >= 0 ? itemAtIndex(index) : null
                    backend.saveViewport(index, item ? contentY - item.y : 0, followTail)
                }
                function restoreViewport() {
                    restoring = true
                    tailTimer.stop()
                    followTail = backend.followTail
                    restoreOffset = backend.scrollPosition
                    restoreIndex = backend.scrollAnchor
                    restoreAttempts = 0
                    restoreTimer.restart()
                }
                acceptedButtons: Qt.NoButton
                visible: backend.messageCount > 0
                x: chatWidth.conversationLeft; width: parent.width - chatWidth.conversationLeft - chatWidth.conversationRight
                anchors.top: parent.top; anchors.topMargin: 20; anchors.bottom: composer.top; anchors.bottomMargin: 24
                clip: true; spacing: 27; model: backend.messageModel
                // A hidden attached ScrollBar still writes contentY when its
                // size changes. Variable-height rows must have one scroll owner.
                onAtYEndChanged: if (atYEnd && !restoring && !chatSelection.dragging) followTail = true
                onFollowTailChanged: saveViewport()
                onContentYChanged: { saveViewport(); pagePrefetch.restart() }
                Timer { id: pagePrefetch; interval: 0; onTriggered: {
                    let first = conversation.indexAt(1, conversation.contentY + 1)
                    let last = conversation.indexAt(1, conversation.contentY + conversation.height - 1)
                    if (first < 0) first = conversation.atYEnd ? conversation.count - 1 : 0
                    backend.messageModel.requestRange(first, last < first ? first + 4 : last)
                } }
                onContentHeightChanged: if (followTail && !restoring) tailTimer.restart()
                onCountChanged: if (followTail && !restoring) tailTimer.restart()
                Timer { id: tailTimer; interval: 0; onTriggered: { if (conversation.followTail && !conversation.restoring) conversation.positionViewAtEnd() } }
                Timer { id: restoreTimer; interval: 16; repeat: true
                    onTriggered: {
                        conversation.forceLayout()
                        conversation.restoreAttempts++
                        if (conversation.followTail || conversation.restoreIndex < 0) conversation.positionViewAtEnd()
                        else {
                            const index = Math.min(conversation.restoreIndex, conversation.count - 1)
                            backend.messageModel.requestRange(index, index + 4)
                            if (conversation.restoreAttempts === 1) { conversation.positionViewAtIndex(index, ListView.Beginning); conversation.forceLayout(); return }
                            if (!backend.messageModel.isReady(index) && conversation.restoreAttempts < 200) return
                            const item = conversation.itemAtIndex(index)
                            if (!item && conversation.restoreAttempts < 5) return
                            if (item) {
                                conversation.positionViewAtIndex(index, ListView.Beginning)
                                if (!conversation.atYEnd) conversation.contentY += Math.min(conversation.restoreOffset, item.height - 1)
                            }
                        }
                        if (conversation.restoreAttempts >= 3) {
                            stop()
                            conversation.restoring = false
                            conversation.saveViewport()
                        }
                    }
                }
                Connections { target: backend
                    function onTranscriptChanged() { if (conversation.followTail && !conversation.restoring) tailTimer.restart() }
                    function onViewChanged() { conversation.restoreViewport() }
                }
                Connections { target: backend.messageModel
                    function onViewportAboutToChange() { conversation.rememberPageAnchor() }
                    function onViewportChanged() { conversation.restorePageAnchor() }
                }
                footer: Item {
                    width: conversation.width; height: turnStatus.visible ? turnStatus.implicitHeight + 20 : 0
                    TaskStatus { id: turnStatus; objectName: "turnStatus"; x: 33; y: 8; status: backend.turnStatus }
                }
                delegate: Column {
                    id: messageRow
                    readonly property var replyMascot: closingMascot
                    required property var modelData
                    required property int index
                    readonly property bool compactionNotice: modelData.customType === "umeko-compaction"
                    readonly property point hoverPoint: chatSelection.mapToItem(messageRow, chatSelection.pointer.x, chatSelection.pointer.y)
                    readonly property bool hovered: chatSelection.hovering && hoverPoint.x >= 0 && hoverPoint.x <= width && hoverPoint.y >= 0 && hoverPoint.y <= height
                    width: conversation.width - 16; spacing: 10
                    onImplicitHeightChanged: if (!modelData._loading) backend.messageModel.recordHeight(index, implicitHeight)
                    Item {
                        visible: !!modelData._loading
                        width: parent.width; height: modelData._estimatedHeight || 100
                        Column { x: 33; y: 16; spacing: 10; visible: !modelData._loadError
                            Rectangle { width: 160; height: 10; radius: 5; color: Theme.line; opacity: 0.5 }
                            Rectangle { width: Math.max(40, Math.min(320, messageRow.width - 66)); height: 10; radius: 5; color: Theme.line; opacity: 0.3 }
                        }
                        ActionButton { x: 33; y: 16; visible: !!modelData._loadError; text: I18n.t("重新加载消息"); glyph: "refresh-cw"; onClicked: backend.messageModel.retryPage(messageRow.index) }
                    }
                    Row { visible: !modelData._loading && !messageRow.compactionNotice && !modelData.continuation && modelData.role !== "user"; spacing: 9
                        AssistantAvatar { objectName: "assistantAvatar_" + messageRow.index; messageKey: window.avatarChatKey + "/" + messageRow.index }
                        SelectableText { selectionController: chatSelection; messageIndex: messageRow.index; blockIndex: -100000; text: "umeko"; anchors.verticalCenter: parent.verticalCenter; color: Theme.ink; font.pixelSize: Theme.font(11); font.weight: Font.DemiBold }
                    }
                    Rectangle {
                        objectName: "messageBubble_" + messageRow.index
                        border.width: 1; border.color: window.searchHighlightRow === messageRow.index ? Theme.accent : "transparent"
                        Behavior on border.color { ColorAnimation { duration: 180 } }
                        visible: !modelData._loading && !messageRow.compactionNotice
                        readonly property bool userMessage: modelData.role === "user"
                        width: userMessage ? (modelData.text.length > 512 ? messageRow.width * 0.82 : Math.min(messageRow.width * 0.82, Math.max(64, userBody.implicitWidth + 28))) : parent.width - 33
                        x: userMessage ? parent.width - width : 33
                        height: replyColumn.implicitHeight + (userMessage ? 22 : modelData.error ? 28 : 4); radius: userMessage ? 13 : 8
                        color: userMessage ? Theme.userBubble : modelData.error ? Theme.accentBg : "transparent"
                        Column { id: replyColumn; x: parent.userMessage || modelData.error ? 14 : 0; y: parent.userMessage ? 11 : modelData.error ? 14 : 0; width: parent.width - x * 2; spacing: 10
                            ActivityHistory { width: parent.width; activity: modelData.activity || []; selectionController: chatSelection; messageIndex: messageRow.index }
                            UserMessageBody { id: userBody; width: parent.width; visible: modelData.role === "user"
                                text: modelData.role === "user" ? modelData.text : ""; attachments: modelData.attachments || []
                                selectionController: chatSelection; messageIndex: messageRow.index }
                            MessageBody { id: reply; width: parent.width
                                selectionController: chatSelection; messageIndex: messageRow.index
                                visible: modelData.role !== "user" && text.length > 0 && !(modelData.activity || []).length
                                text: modelData.role === "user" || (modelData.activity || []).length ? "" : modelData.text || (messageRow.index === conversation.count - 1 && backend.busy ? I18n.t(backend.toolStatus) + "…" : "")
                                markdown: modelData.role === "assistant" && !modelData.error
                                textColor: modelData.error ? Theme.danger : Theme.ink }
                        }
                    }
                    ActionButton {
                        objectName: "requestDetails_" + messageRow.index
                        selectionController: chatSelection
                        visible: !modelData._loading && !messageRow.compactionNotice && !!modelData.error && (modelData.diagnosticId || "").length > 0
                        x: 33; text: I18n.t("查看请求与返回"); glyph: "code"; quiet: true
                        onClicked: requestInspector.show(modelData.diagnosticId)
                    }
                    Column {
                        id: compactionEvent
                        objectName: "compactionEvent_" + messageRow.index
                        x: 33; width: parent.width - 33
                        visible: !modelData._loading && messageRow.compactionNotice
                        readonly property var record: modelData.compaction || ({})
                        readonly property string eventState: record.state || "success"
                        readonly property string heading: eventState === "running" ? I18n.t("正在压缩上下文") : eventState === "failure" ? I18n.t("上下文压缩失败") : I18n.t("上下文已压缩")
                        property bool expanded: false
                        spacing: 6
                        onExpandedChanged: if (!expanded) chatSelection.hideDetails(messageRow.index, 0, 1)
                        Item {
                            width: Math.min(parent.width, compactionHeading.implicitWidth); height: Theme.control(24)
                            Row {
                                id: compactionHeading; height: parent.height; spacing: 7
                                ActivitySpinner { visible: compactionEvent.eventState === "running"; width: Theme.icon(12); height: Theme.icon(12); anchors.verticalCenter: parent.verticalCenter }
                                Text { text: compactionEvent.heading; color: compactionHover.interactionHovered ? Theme.ink : Theme.muted; font.pixelSize: Theme.font(12); anchors.verticalCenter: parent.verticalCenter }
                                Glyph { name: compactionEvent.expanded ? "chevron-down" : "chevron-right"; width: Theme.icon(12); height: Theme.icon(12); anchors.verticalCenter: parent.verticalCenter }
                            }
                            ChatHitArea {
                                id: compactionHover; objectName: "compactionEventToggle_" + messageRow.index
                                anchors.fill: parent; selectionController: chatSelection
                                onClicked: compactionEvent.expanded = !compactionEvent.expanded
                            }
                            Accessible.role: Accessible.Button; Accessible.name: compactionEvent.heading
                            Accessible.description: compactionEvent.expanded ? I18n.t("已展开") : I18n.t("已折叠")
                        }
                        Item {
                            visible: compactionEvent.expanded
                            width: parent.width; height: compactionDetails.implicitHeight
                            Rectangle { width: 1; height: parent.height; color: Theme.line; x: 6 }
                            SelectableText {
                                id: compactionDetails; objectName: "compactionEventDetails_" + messageRow.index
                                x: 23; width: parent.width - x
                                text: {
                                    const detail = compactionEvent.record, lines = []
                                    if (typeof detail.before === "number") lines.push(I18n.t("压缩前：") + detail.before + " tokens")
                                    if (typeof detail.after === "number") lines.push(I18n.t("压缩后：") + detail.after + " tokens")
                                    if (detail.summary) lines.push("\n" + I18n.t("压缩摘要") + "\n" + detail.summary)
                                    if (detail.error) lines.push("\n" + I18n.t(detail.error))
                                    return lines.join("\n")
                                }
                                color: Theme.muted; font.pixelSize: Theme.font(13); wrapMode: TextEdit.Wrap; textFormat: TextEdit.PlainText
                                selectionController: chatSelection; messageIndex: messageRow.index; blockIndex: 0
                                conditionalSelection: true
                            }
                        }
                    }
                    OutputLimitNotice {
                        objectName: "outputLimitNotice_" + messageRow.index
                        x: 33; width: parent.width - 33
                        visible: !modelData._loading && !messageRow.compactionNotice && modelData.segmentLast !== false && modelData.role === "assistant" && modelData.stopReason === "length"
                        continuable: messageRow.index === conversation.count - 1 && !backend.busy
                        onContinued: backend.send(I18n.t("继续刚才未完成的回答，从中断处接着输出，不要重复已有内容。"))
                    }
                    Item {
                        objectName: "messageActions_" + messageRow.index
                        visible: !modelData._loading && !messageRow.compactionNotice && modelData.segmentLast !== false
                        width: parent.width; height: 18
                        opacity: messageRow.hovered || actionHover.hovered ? 1 : 0
                        HoverHandler { id: actionHover }
                        Row {
                            x: modelData.role === "user" ? parent.width - width : 33
                            height: parent.height; spacing: 7
                            Text { objectName: "messageTime_" + messageRow.index; anchors.verticalCenter: parent.verticalCenter; color: Theme.muted; font.pixelSize: Theme.font(11)
                                text: { if (!modelData.timestamp) return ""; const date = new Date(modelData.timestamp); if (isNaN(date.getTime())) return ""; return Qt.formatDateTime(date, date.toDateString() === new Date().toDateString() ? "hh:mm" : "MM-dd hh:mm") } }
                            ActionButton { objectName: "copyMessage_" + messageRow.index; selectionController: chatSelection; glyph: "copy"; width: Theme.control(22); height: Theme.control(18); quiet: true; enabled: parent.parent.opacity > 0; hint: I18n.t("复制消息")
                                onClicked: backend.copyDisplayMessage(messageRow.index) }
                        }
                    }
                    ReplyMascot {
                        id: closingMascot
                        objectName: "replyEndMascot_" + messageRow.index
                        selectionController: chatSelection
                        visible: !modelData._loading && !messageRow.compactionNotice && messageRow.index === conversation.count - 1 && modelData.role === "assistant" && !modelData.error && (modelData.text || "").trim().length > 0 && !backend.running && backend.turnStatus.state === "finished"
                        x: 33
                    }
                }
            }

            ChatSelection { id: chatSelection; anchors.fill: conversation; view: conversation; visible: conversation.visible; enabled: !chatCover.visible }
            ReplyMascot {
                id: widthLimitMascot; objectName: "chatWidthLimitMascot"
                x: composer.x+33; y: Math.max(0,composer.y-height-12); z: 50
                visible: reaction.length > 0
            }
            Connections { target: backend; function onViewChanged() { widthLimitMascot.reset() } }

            QuestionNavigator {
                anchors.right: parent.right
                anchors.top: conversation.top; anchors.bottom: conversation.bottom
                view: conversation; enabled: !chatCover.visible; z: 20
            }

            Composer {
                id: composer; objectName: "composer"
                enabled: !chatCover.visible
                x: chatWidth.composerLeft; anchors.bottom: parent.bottom
                anchors.bottomMargin: Math.max(57, Math.max(footerActions.height, desktopPluginMenu.height) + Theme.control(10) + 13) + (retryStatus.visible ? retryStatus.implicitHeight + 6 : 0)
                width: parent.width - chatWidth.composerLeft - chatWidth.composerRight
                onOpenModels: modelPopup.toggle()
                onChooseFiles: attachmentDialog.open()
            }
            NetworkRetry { id: retryStatus; anchors.left: composer.left; anchors.top: composer.bottom; anchors.topMargin: 6; width: composer.width }
            ChatWidthControls { id: chatWidth; anchors.fill: parent; z: 25; enabled: !chatCover.visible && !imageViewer.visible }
            ChatFileDrop { id: chatDrop; anchors.fill: parent; z: 70; enabled: !chatCover.visible; chatWindow: window }
            ChatLoadingOverlay {
                id: chatCover; anchors.fill: parent; z: 50; view: conversation
                onRevealed: if (window.page === "chat") composer.focusInput()
            }
            Row { id: footerActions; x: composer.x + (composer.width - width) / 2; anchors.bottom: parent.bottom; anchors.bottomMargin: 13; spacing: 8
                ActionButton { height: Theme.control(28); quiet: true; text: "Agent"; glyph: "sliders"; onClicked: window.settings(3) }
                ActionButton { objectName: "forkSessionButton"; visible: backend.messageCount > 0; enabled: !backend.busy; height: Theme.control(28); quiet: true; text: I18n.t("分支"); glyph: "branch"; onClicked: backend.forkSession() }
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

        SettingsPage {
            id: settingsPage
            objectName: "settingsPage"
            anchors.top: header.bottom; anchors.bottom: parent.bottom; width: parent.width
            visible: window.page === "settings"
            tab: window.settingsTab
            onTabSelected: value => window.settingsTab = value
            onBack: window.page = "chat"
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
    SidebarMenus { id: sidebarMenus; objectName: "sidebarMenus"; parent: Overlay.overlay; anchors.fill: parent }
    Rectangle {
        z: 100; anchors.horizontalCenter: mainArea.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 27
        width: Math.min(toastLabel.implicitWidth + 40, 750); height: toastLabel.implicitHeight + 24; radius: 10
        color: Theme.ink; visible: window.notification !== ""
        opacity: visible ? 1 : 0
        Text { id: toastLabel; anchors.centerIn: parent; text: I18n.t(window.notification); color: Theme.bg; font.pixelSize: Theme.font(12); width: Math.min(implicitWidth, 710); wrapMode: Text.Wrap }
    }
}
