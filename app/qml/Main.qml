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
    property int settingsTab: 0
    property string notification: ""
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
    property real sidebarPreferredWidth: backend.sidebarWidth
    property bool sidebarCollapsed: backend.sidebarCollapsed
    readonly property real sidebarMinimumWidth: 200
    readonly property real sidebarMaximumWidth: Math.min(480, width - 760)
    function saveSidebarLayout() {
        backend.saveSidebarLayout(Math.round(sidebarPreferredWidth), sidebarCollapsed)
        sidebarPreferredWidth = backend.sidebarWidth
        sidebarCollapsed = backend.sidebarCollapsed
    }
    function toggleSidebar() { sidebarCollapsed = !sidebarCollapsed; saveSidebarLayout() }
    function settings(tab) { settingsTab = tab === 2 ? 1 : tab === 4 ? 3 : tab; page = "settings" }
    function startChat() { cancelSidebarSelection(); backend.newSession(); page = "chat"; composer.focusInput() }
    onPageChanged: { if (page !== "chat") cancelSidebarSelection(); backend.setConversationVisible(page === "chat" && active) }
    onActiveChanged: backend.setConversationVisible(page === "chat" && active)
    Component.onCompleted: backend.setConversationVisible(page === "chat" && active)
    Shortcut { sequence: "Ctrl+N"; onActivated: window.startChat() }
    Shortcut { sequence: "Ctrl+S"; enabled: window.page === "chat" && !chatCover.visible; onActivated: composer.sendMessage(true) }
    Shortcut { sequence: "Ctrl+,"; onActivated: window.settings(0) }
    Shortcut { sequence: "Ctrl+B"; onActivated: window.toggleSidebar() }
    Shortcut { sequences: [StandardKey.Copy]; enabled: chatSelection.activeFocus && chatSelection.hasSelection; onActivated: Qt.callLater(chatSelection.copy) }
    Shortcut { sequences: [StandardKey.SelectAll]; enabled: chatSelection.activeFocus; onActivated: chatSelection.selectAll() }
    Shortcut { sequence: "Escape"; onActivated: { if (window.page === "settings") window.page = "chat"; else modelPopup.close() } }
    Connections { target: backend; function onToast(message) { window.notification = message; toastTimer.restart() } }
    Connections { target: backend; function onLayoutChanged() { window.sidebarPreferredWidth = backend.sidebarWidth; window.sidebarCollapsed = backend.sidebarCollapsed } }
    Timer { id: toastTimer; interval: 4200; onTriggered: window.notification = "" }
    RequestDetails { id: requestInspector }
    FolderDialog { id: folderDialog; title: I18n.t("选择工作目录"); onAccepted: backend.setWorkspace(selectedFolder.toString()) }
    FileDialog { id: attachmentDialog; title: I18n.t("添加文件"); fileMode: FileDialog.OpenFiles; onAccepted: backend.addAttachments(JSON.stringify(selectedFiles.map(url => url.toString()))) }

    Rectangle { anchors.fill: parent; color: "transparent"; border.color: Theme.line; z: 30 }
    WindowResizeHandles { anchors.fill: parent; z: 100; targetWindow: window }

    Rectangle {
        id: sidebar; objectName: "sidebar"
        width: window.sidebarCollapsed ? 0 : Math.min(window.sidebarPreferredWidth, window.sidebarMaximumWidth)
        visible: !window.sidebarCollapsed; clip: true
        anchors.top: parent.top; anchors.bottom: parent.bottom
        color: Theme.sidebar
        Rectangle { width: 1; anchors.right: parent.right; height: parent.height; color: Theme.line }
        MouseArea { width: parent.width; height: 20; enabled: !chatSelection.dragging; onPressed: window.startSystemMove(); onDoubleClicked: window.visibility === Window.Maximized ? window.showNormal() : window.showMaximized() }
        ActionButton {
            objectName: "newChatButton"
            x: 16; y: 24; width: parent.width - 32; height: 42
            text: I18n.t("新建会话"); glyph: "plus"
            onClicked: window.startChat()
            Text { anchors.right: parent.right; anchors.rightMargin: 13; anchors.verticalCenter: parent.verticalCenter; visible: Theme.fontScale <= 1.25; text: "Ctrl N"; color: Theme.muted; font.pixelSize: Theme.font(10) }
            contentItem: Item { Row { x: 13; width: parent.width - (Theme.fontScale <= 1.25 ? 65 : 26); spacing: 9; anchors.verticalCenter: parent.verticalCenter; Glyph { name: "plus"; width: 18; height: 18 } Text { width: Math.max(0, parent.width - 27); elide: Text.ElideRight; text: I18n.t("新建会话"); font.pixelSize: Theme.font(12); color: Theme.ink; anchors.verticalCenter: parent.verticalCenter } } }
        }
        Text { id: recentLabel; x: 29; y: 94; text: backend.showArchived ? I18n.t("已归档") : I18n.t("项目"); font.pixelSize: Theme.font(10); color: Theme.muted; font.letterSpacing: 1 }
        ActionButton { objectName: "archivedViewButton"; anchors.right: parent.right; anchors.rightMargin: 54; y: recentLabel.y - 7; width: 26; height: 26; glyph: "archive"; quiet: true; hint: backend.showArchived ? I18n.t("返回项目") : I18n.t("查看归档会话"); onClicked: backend.toggleArchived() }
        ActionButton { anchors.right: parent.right; anchors.rightMargin: 22; y: recentLabel.y - 7; width: 26; height: 26; glyph: "plus"; quiet: true; hint: I18n.t("打开项目文件夹"); onClicked: folderDialog.open() }
        ListView {
            id: sessionList; objectName: "projectList"
            x: 12; y: recentLabel.y + 28; width: parent.width - 24; height: apiStatus.y - y - 16
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
                Glyph { visible: modelData.kind === "project"; name: "folder"; x: 15; anchors.verticalCenter: parent.verticalCenter; width: 16; height: 16 }
                Text { x: modelData.kind === "label" ? 17 : 42; width: parent.width - x - 32; anchors.verticalCenter: parent.verticalCenter; text: modelData.kind === "label" ? I18n.t(modelData.title) : modelData.title; elide: Text.ElideRight; font.pixelSize: Theme.font(modelData.kind === "label" ? 10 : 11); color: modelData.kind === "label" ? Theme.muted : Theme.ink }
                ActivitySpinner { objectName: "sessionSpinner_" + modelData.id; anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter; width: 15; height: 15; visible: modelData.kind === "session" && modelData.running === true; color: modelData.waiting ? Theme.accent : Theme.muted }
                Rectangle { objectName: "sessionUnread_" + modelData.id; anchors.right: parent.right; anchors.rightMargin: 14; anchors.verticalCenter: parent.verticalCenter; width: 6; height: 6; radius: 3; color: "#4c9c6d"; visible: modelData.kind === "session" && modelData.unread === true && !modelData.running }
                Glyph { anchors.right: parent.right; anchors.rightMargin: 11; anchors.verticalCenter: parent.verticalCenter; width: 12; height: 12; name: "pin"; visible: modelData.pinned === true && !modelData.running && !modelData.unread && !(rowMouse.containsMouse) }
                ActionButton { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; width: 28; height: 28; quiet: true; glyph: modelData.collapsed ? "chevron-right" : "chevron-down"; visible: modelData.kind === "project" && (rowMouse.containsMouse || hovered || modelData.collapsed); onClicked: backend.toggleProject(modelData.id) }
            }
        }
        DropArea {
            id: projectDrop; objectName: "projectDropArea"; anchors.fill: parent; z: 20
            onEntered: drag => { drag.accepted = drag.urls.length > 0 }
            onDropped: drop => { backend.dropProjects(JSON.stringify(drop.urls.map(url => url.toString()))); drop.acceptProposedAction(); window.page = "chat" }
        }
        Rectangle {
            anchors.fill: parent; anchors.margins: 7; radius: 10; z: 21; visible: projectDrop.containsDrag; color: Theme.accentBg; border.color: Theme.accent
            Column { anchors.centerIn: parent; spacing: 12; Glyph { name: "folder"; width: 26; height: 26; anchors.horizontalCenter: parent.horizontalCenter } Text { text: I18n.t("打开项目文件夹"); color: Theme.accent; font.pixelSize: Theme.font(12) } }
        }
        Item {
            id: apiStatus; x: 26; anchors.bottom: settingsButton.top; anchors.bottomMargin: 9; width: parent.width - 52; height: 29
            Rectangle { x: 1; y: 10; width: 6; height: 6; radius: 3; color: backend.serverRunning ? "#72a783" : "#a6ada5" }
            Text { x: 17; y: 5; width: Math.max(0, apiPort.x - x - 8); elide: Text.ElideRight; text: backend.serverRunning ? I18n.t("API 代理运行中") : I18n.t("API 代理未启动"); color: Theme.muted; font.pixelSize: Theme.font(10) }
            Text { id: apiPort; anchors.right: parent.right; y: 5; text: ":" + backend.config.server.port; color: Theme.muted; font.pixelSize: Theme.font(10); font.family: "Consolas" }
            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: window.settings(1) }
        }
        ActionButton {
            id: settingsButton; objectName: "settingsButton"
            x: 12; anchors.bottom: parent.bottom; anchors.bottomMargin: 17; width: parent.width - 24; height: 44; quiet: true
            onClicked: window.page === "settings" ? window.page = "chat" : window.settings(0)
            contentItem: Item { Row { x: 16; spacing: 12; anchors.verticalCenter: parent.verticalCenter
                Glyph { name: "settings"; width: 18; height: 18 }
                Text { text: I18n.t("设置"); color: Theme.ink; font.pixelSize: Theme.font(12); anchors.verticalCenter: parent.verticalCenter }
            } }
            Text { anchors.right: parent.right; anchors.rightMargin: 16; anchors.verticalCenter: parent.verticalCenter; visible: Theme.fontScale <= 1.5; text: "v" + backend.appAbout.info.version; font.pixelSize: Theme.font(10); color: Theme.muted }
        }
    }

    MouseArea {
        id: sidebarResizeHandle; objectName: "sidebarResizeHandle"
        x: sidebar.width - width / 2; y: 5; width: 8; height: window.height - 10; z: 40
        visible: !window.sidebarCollapsed; enabled: !chatSelection.dragging
        cursorShape: Qt.SizeHorCursor; hoverEnabled: true; preventStealing: true
        property real pressX: 0
        property real pressWidth: 0
        onPressed: mouse => {
            pressX = mapToItem(window.contentItem, mouse.x, mouse.y).x
            pressWidth = sidebar.width
        }
        onPositionChanged: mouse => {
            if (!pressed) return
            const delta = mapToItem(window.contentItem, mouse.x, mouse.y).x - pressX
            window.sidebarPreferredWidth = Math.max(window.sidebarMinimumWidth, Math.min(window.sidebarMaximumWidth, pressWidth + delta))
        }
        onReleased: window.saveSidebarLayout()
        onCanceled: window.saveSidebarLayout()
        Rectangle { width: 2; height: parent.height; anchors.horizontalCenter: parent.horizontalCenter; color: parent.containsMouse || parent.pressed ? Theme.accent : "transparent"; opacity: 0.5 }
    }

    Item {
        id: mainArea; objectName: "mainArea"
        anchors.left: sidebar.right; anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom
        Item {
            id: header; height: 72; width: parent.width
            MouseArea { anchors.fill: parent; enabled: !chatSelection.dragging; onPressed: window.startSystemMove(); onDoubleClicked: window.visibility === Window.Maximized ? window.showNormal() : window.showMaximized() }
            Row { x: 20; anchors.verticalCenter: parent.verticalCenter; spacing: 10
                ActionButton { objectName: "toggleSidebarButton"; glyph: "layout"; quiet: true; width: 30; height: 30; hint: window.sidebarCollapsed ? I18n.t("展开侧栏（Ctrl+B）") : I18n.t("收起侧栏（Ctrl+B）"); Accessible.name: window.sidebarCollapsed ? I18n.t("展开侧栏") : I18n.t("收起侧栏"); onClicked: window.toggleSidebar() }
                Text { text: window.page === "chat" ? I18n.t("工作空间") : I18n.t("偏好设置"); color: Theme.muted; font.pixelSize: Theme.font(11); anchors.verticalCenter: parent.verticalCenter }
                Text { text: "/"; color: Theme.line; font.pixelSize: Theme.font(12); anchors.verticalCenter: parent.verticalCenter }
                Text { text: window.page === "chat" ? (window.sidebarSwitching ? window.pendingSidebarTitle : backend.sessionTitle) : [I18n.t("账号与供应商"), I18n.t("API 代理服务"), I18n.t("API 代理服务"), "Agent", "Agent", I18n.t("外观"), I18n.t("关于")][window.settingsTab]; color: Theme.ink; font.pixelSize: Theme.font(11); width: 225; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter }
            }
            Row {
                anchors.right: windowControls.left; anchors.rightMargin: 18; anchors.verticalCenter: parent.verticalCenter; spacing: 7
                Rectangle { width: 5; height: 5; radius: 3; color: Theme.accent; anchors.verticalCenter: parent.verticalCenter }
                Text { text: I18n.t("本机工作空间"); font.pixelSize: Theme.font(10); color: Theme.muted }
            }
            Row { id: windowControls; anchors.right: parent.right; anchors.rightMargin: 14; anchors.top: parent.top; anchors.topMargin: 18; spacing: 2
                ActionButton { glyph: "minus"; width: 32; height: 30; quiet: true; hint: I18n.t("最小化"); onClicked: window.showMinimized() }
                ActionButton { glyph: "maximize"; width: 32; height: 30; quiet: true; hint: I18n.t("最大化"); onClicked: window.visibility === Window.Maximized ? window.showNormal() : window.showMaximized() }
                ActionButton { glyph: "x"; width: 32; height: 30; quiet: true; hint: I18n.t("关闭"); onClicked: window.close() }
            }
        }

        Item {
            id: chatPage; objectName: "chatPage"; anchors.top: header.bottom; anchors.bottom: parent.bottom; width: parent.width
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
                Image { objectName: "yanamiWatermark"; anchors.fill: parent; source: "../icons/portraits/02.png"; fillMode: Image.PreserveAspectCrop; horizontalAlignment: Image.AlignHCenter; verticalAlignment: Image.AlignVCenter; mipmap: true; opacity: 0.055 }
            }
            Item {
                id: welcome; width: Math.min(parent.width - 70, 620); height: 270
                anchors.horizontalCenter: parent.horizontalCenter; anchors.verticalCenter: parent.verticalCenter; anchors.verticalCenterOffset: -119
                visible: backend.messages.length === 0
                WelcomeMascot { id: welcomeMascot; anchors.horizontalCenter: parent.horizontalCenter; portraitIndex: backend.portrait }
                Connections { target: backend; function onViewChanged() { welcomeMascot.reset() } }
                Text { objectName: "welcomeGreeting"; anchors.horizontalCenter: parent.horizontalCenter; y: 231; width: parent.width; text: welcomeMascot.reactionText || I18n.t(backend.greeting); color: Theme.yanami ? Theme.accent : Theme.muted; font.pixelSize: Theme.font(14); horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; lineHeight: 1.35 }
            }

            ListView {
                id: conversation; objectName: "conversation"
                property bool followTail: true
                property bool restoring: false
                property real restoreOffset: -1
                property int restoreIndex: -1
                property int restoreAttempts: 0
                function beginBrowsing() { tailTimer.stop(); restoreTimer.stop(); restoring = false; cancelFlick(); followTail = false }
                function scrollBy(delta) {
                    beginBrowsing()
                    const first = itemAtIndex(0), last = itemAtIndex(count - 1)
                    const top = first ? first.y : originY
                    const bottom = Math.max(top, last ? last.y + last.height - height : originY + contentHeight - height)
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
                visible: backend.messages.length > 0
                x: Math.max(38, (parent.width - 830) / 2); width: Math.min(parent.width - 76, 830)
                anchors.top: parent.top; anchors.topMargin: 20; anchors.bottom: composer.top; anchors.bottomMargin: 24
                clip: true; spacing: 27; model: backend.messageModel
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded
                    onPressedChanged: { if (pressed) conversation.followTail = false; else if (conversation.atYEnd) conversation.followTail = true }
                }
                onAtYEndChanged: if (atYEnd && !restoring && !chatSelection.dragging) followTail = true
                onFollowTailChanged: saveViewport()
                onContentYChanged: saveViewport()
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
                            if (conversation.restoreAttempts === 1) { conversation.positionViewAtIndex(index, ListView.Beginning); conversation.forceLayout(); return }
                            const item = conversation.itemAtIndex(index)
                            if (!item && conversation.restoreAttempts < 5) return
                            if (item) {
                                let target = item.y + Math.min(conversation.restoreOffset, item.height - 1)
                                const last = conversation.itemAtIndex(conversation.count - 1)
                                if (last) target = Math.min(target, last.y + last.height - conversation.height)
                                const first = conversation.itemAtIndex(0)
                                if (first) target = Math.max(target, first.y)
                                conversation.contentY = target
                            }
                        }
                        if (conversation.restoreAttempts >= 2) {
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
                delegate: Column {
                    id: messageRow
                    required property var modelData
                    required property int index
                    readonly property point hoverPoint: chatSelection.mapToItem(messageRow, chatSelection.pointer.x, chatSelection.pointer.y)
                    readonly property bool hovered: chatSelection.hovering && hoverPoint.x >= 0 && hoverPoint.x <= width && hoverPoint.y >= 0 && hoverPoint.y <= height
                    width: conversation.width - 16; spacing: 10
                    Row { visible: modelData.role !== "user"; spacing: 9
                        Rectangle { width: 24; height: 24; radius: 7; color: Theme.accentBg
                            Glyph { anchors.centerIn: parent; name: "spark"; width: 14; height: 14 } }
                        SelectableText { selectionController: chatSelection; messageIndex: messageRow.index; blockIndex: -100000; text: "umeko"; anchors.verticalCenter: parent.verticalCenter; color: Theme.ink; font.pixelSize: Theme.font(11); font.weight: Font.DemiBold }
                    }
                    Rectangle {
                        objectName: "messageBubble_" + messageRow.index
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
                                text: modelData.role === "user" || (modelData.activity || []).length ? "" : modelData.text || (messageRow.index === conversation.count - 1 && backend.busy ? backend.toolStatus + "…" : "")
                                markdown: modelData.role === "assistant" && !modelData.error
                                textColor: modelData.error ? Theme.danger : Theme.ink }
                        }
                    }
                    ActionButton {
                        objectName: "requestDetails_" + messageRow.index
                        selectionController: chatSelection
                        visible: modelData.error && (modelData.diagnosticId || "").length > 0
                        x: 33; text: I18n.t("查看请求详情"); glyph: "code"; quiet: true
                        onClicked: requestInspector.show(modelData.diagnosticId)
                    }
                    Item {
                        objectName: "messageActions_" + messageRow.index
                        width: parent.width; height: 18
                        opacity: messageRow.hovered || actionHover.hovered ? 1 : 0
                        HoverHandler { id: actionHover }
                        Row {
                            x: modelData.role === "user" ? parent.width - width : 33
                            height: parent.height; spacing: 7
                            Text { objectName: "messageTime_" + messageRow.index; anchors.verticalCenter: parent.verticalCenter; color: Theme.muted; font.pixelSize: Theme.font(11)
                                text: { if (!modelData.timestamp) return ""; const date = new Date(modelData.timestamp); if (isNaN(date.getTime())) return ""; return Qt.formatDateTime(date, date.toDateString() === new Date().toDateString() ? "hh:mm" : "MM-dd hh:mm") } }
                            ActionButton { objectName: "copyMessage_" + messageRow.index; selectionController: chatSelection; glyph: "copy"; width: 22; height: 18; quiet: true; enabled: parent.parent.opacity > 0; hint: I18n.t("复制消息")
                                onClicked: { const activity = modelData.activity || []; const prose = activity.filter(item => item.kind === "text").map(item => item.text).join("\n\n"); backend.copy([prose || modelData.text || "", ...(modelData.attachments || []).map(item => item.name)].filter(part => !!part).join("\n")) } }
                        }
                    }
                    ReplyMascot {
                        objectName: "replyEndMascot_" + messageRow.index
                        selectionController: chatSelection
                        visible: messageRow.index === conversation.count - 1 && modelData.role === "assistant" && !modelData.error && (modelData.text || "").trim().length > 0 && !backend.running
                        x: 33
                    }
                }
            }

            ChatSelection { id: chatSelection; anchors.fill: conversation; view: conversation; visible: conversation.visible; enabled: !chatCover.visible }

            Composer {
                id: composer; objectName: "composer"
                enabled: !chatCover.visible
                anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 57
                width: Math.min(parent.width - 94, 850)
                onOpenModels: modelPopup.toggle()
                onChooseFiles: attachmentDialog.open()
            }
            ChatLoadingOverlay {
                id: chatCover; anchors.fill: parent; z: 50; view: conversation
                onRevealed: if (window.page === "chat") composer.focusInput()
            }
            Row { anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 13; spacing: 8
                ActionButton { height: 28; quiet: true; text: "Agent"; glyph: "sliders"; onClicked: window.settings(3) }
                ActionButton { objectName: "forkSessionButton"; visible: backend.messages.length > 0; enabled: !backend.busy; height: 28; quiet: true; text: I18n.t("分支"); glyph: "branch"; onClicked: backend.forkSession() }
            }
        }

        SettingsPage {
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
    }
    ApprovalDialog { parent: Overlay.overlay }
    SidebarMenus { id: sidebarMenus; parent: Overlay.overlay; anchors.fill: parent }
    Rectangle {
        z: 100; anchors.horizontalCenter: mainArea.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 27
        width: Math.min(toastLabel.implicitWidth + 40, 750); height: toastLabel.implicitHeight + 24; radius: 10
        color: Theme.ink; visible: window.notification !== ""
        opacity: visible ? 1 : 0
        Text { id: toastLabel; anchors.centerIn: parent; text: I18n.t(window.notification); color: Theme.bg; font.pixelSize: Theme.font(12); width: Math.min(implicitWidth, 710); wrapMode: Text.Wrap }
    }
}
