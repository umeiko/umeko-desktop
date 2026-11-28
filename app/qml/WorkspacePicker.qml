/**
 * Local / Remote working directory picker dialog.
 * Dialog layout, copy, per-host+folder 30s listing cache, concurrent request
 * deduplication, fresh bypass, host-match check, and Windows drive listing are
 * adapted from dsh-remote 1.4.1 (lib/client.js, lib/routes-fs.js),
 * Copyright (c) 2026 dsh-remote contributors (MIT).
 * Full license: ../../licenses/dsh-remote-MIT.txt.
 */
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: root
    objectName: "workspacePicker"
    parent: Overlay.overlay
    anchors.centerIn: parent
    modal: true
    focus: true
    padding: 0
    closePolicy: Popup.CloseOnPressOutside
    width: Math.min(parent ? Math.max(460, parent.width - 48) : 680, 680)

    signal browseLocalRequested()
    signal workspaceSelected()

    property string activeTab: "local"
    property bool allowRemote: false
    onAllowRemoteChanged: if (!allowRemote) {
        activeTab = "local"
        _afterEnsure = null
        autocompleteTimer.stop()
    }
    property bool newConversation: false
    property string localProjectStatus: ""
    property string pendingLocalProjectPath: ""
    property var hostChoices: []
    property string selectedEnvName: ""
    property string selectedHost: ""
    property string selectedPlatform: "linux"
    property bool ensuringHost: false
    property string ensureReqId: ""

    property string typedPath: ""
    property bool browserOpen: false
    property string currentBrowsePath: ""
    property string parentBrowsePath: ""
    property var browserEntries: []
    property int selectedIndex: -1
    property bool browserLoading: false
    property string browserError: ""

    property bool mkdirOpen: false
    property string mkdirName: ""
    property bool mkdirBusy: false
    property string mkdirReqId: ""
    property string mkdirTargetPath: ""

    property bool homeLoading: false
    property string homeReqId: ""

    property var autocompleteItems: []
    property int autocompleteIndex: -1
    property bool autocompleteVisible: false

    // Per-host+dir 30s cache, concurrent request merge, and host-match validation.
    property var dirCache: ({})
    property var inflightByKey: ({})
    property var pendingRequests: ({})
    readonly property int cacheTtlMs: 30000

    readonly property var selectedEnvRow: {
        const list = backend.remoteEnvironments || []
        for (let i = 0; i < list.length; i++) {
            if (list[i].name === selectedEnvName || (!selectedEnvName && list[i].host === selectedHost))
                return list[i]
        }
        return null
    }

    readonly property bool isReconnecting: {
        if (ensuringHost) return true
        const row = selectedEnvRow
        return !!row && (row.state === "reconnecting" || row.state === "connecting")
    }

    readonly property string effectiveSelectedPath: {
        if (browserOpen && selectedIndex >= 0 && selectedIndex < browserEntries.length) {
            return browserEntries[selectedIndex].path || currentBrowsePath
        }
        if (browserOpen && currentBrowsePath) return currentBrowsePath
        return typedPath.trim()
    }

    function openPicker(initialTab) { openForWorkspace(initialTab, false) }
    function openForConversation() { openForWorkspace("", true) }

    function openForWorkspace(initialTab, newConversation) {
        root.newConversation = newConversation === true
        activeTab = allowRemote ? (initialTab || (backend.activeRemoteWorkspace && backend.activeRemoteWorkspace.environment ? "remote" : "local")) : "local"
        mkdirOpen = false
        mkdirName = ""
        browserError = ""
        autocompleteVisible = false
        const defaultPath = root.newConversation ? backend.defaultWorkspace : backend.projectPickerDefaultPath
        localPathInput.text = typeof defaultPath === "function" ? (root.newConversation ? backend.defaultWorkspace() : backend.projectPickerDefaultPath()) : ""
        localProjectStatus = ""
        pendingLocalProjectPath = ""
        if (allowRemote) {
            backend.refreshSshConfigHosts()
            rebuildHostChoices()
        }
        if (activeTab === "remote") {
            const active = backend.activeRemoteWorkspace
            if (active && active.environment) {
                selectHostByKey(active.environment, active.host)
                typedPath = active.remotePath || ""
                pathInput.text = typedPath
            } else if (!selectedHost && hostChoices.length > 0) {
                applyHostChoice(0)
            }
        }
        open()
        Qt.callLater(() => {
            if (activeTab === "remote") pathInput.forceActiveFocus()
        })
    }

    function finishSelection() {
        if (root.newConversation) backend.newSession()
        root.close()
        root.workspaceSelected()
    }

    function chooseLocalUrl(url) {
        if (backend.setWorkspace(url)) finishSelection()
    }

    function localProjectText(code) {
        const english = backend.language === "en"
        switch (code) {
        case "missing": return english ? "This directory does not exist." : "目录不存在。"
        case "invalid": return english ? "Enter a valid absolute local path." : "请输入有效的本机绝对路径。"
        case "not_directory": return english ? "The path is not a directory." : "该路径不是目录。"
        case "missing_parent": return english ? "Choose an existing parent directory." : "请使用已有的父目录。"
        case "permission": return english ? "Permission denied. Choose a writable directory." : "权限不足，请选择有写入权限的目录。"
        case "changed": return english ? "The path changed. Check it and try again." : "路径已发生变化，请确认后重试。"
        default: return english ? "This path is unavailable. Check it and try again." : "该路径不可用，请检查后重试。"
        }
    }

    function chooseTypedLocal(create) {
        const value = localPathInput.text.trim()
        if (!value) return
        if (root.newConversation) {
            root.chooseLocalUrl(value)
            return
        }
        if (create && value !== pendingLocalProjectPath) return
        const result = backend.selectLocalProjectDirectory(value, create)
        if (result === "selected") {
            root.finishSelection()
            return
        }
        localProjectStatus = result
        pendingLocalProjectPath = result === "missing" || (create && result === "permission") ? value : ""
    }

    function rebuildHostChoices() {
        const configured = backend.remoteEnvironments || []
        const sshHosts = backend.sshConfigHosts || []
        const seenHosts = ({})
        const items = []
        for (let i = 0; i < configured.length; i++) {
            const row = configured[i]
            seenHosts[row.host] = true
            items.push({
                envName: row.name,
                host: row.host,
                platform: row.platform,
                configured: true,
                label: row.name === row.host ? row.host : (row.host + " (" + row.name + ")")
            })
        }
        for (let j = 0; j < sshHosts.length; j++) {
            const h = sshHosts[j]
            if (!h || !h.alias || seenHosts[h.alias]) continue
            seenHosts[h.alias] = true
            items.push({
                envName: "",
                host: h.alias,
                platform: "",
                configured: false,
                label: h.alias
            })
        }
        hostChoices = items
        if (selectedHost) {
            for (let k = 0; k < items.length; k++) {
                if (items[k].host === selectedHost || (selectedEnvName && items[k].envName === selectedEnvName)) {
                    selectedEnvName = items[k].envName
                    selectedHost = items[k].host
                    if (items[k].platform) selectedPlatform = items[k].platform
                    if (hostCombo.currentIndex !== k) hostCombo.currentIndex = k
                    return
                }
            }
        }
        if (items.length > 0 && !selectedHost) {
            selectedEnvName = items[0].envName
            selectedHost = items[0].host
            selectedPlatform = items[0].platform || "linux"
            hostCombo.currentIndex = 0
        }
    }

    function selectHostByKey(envName, host) {
        for (let i = 0; i < hostChoices.length; i++) {
            if ((envName && hostChoices[i].envName === envName) || (host && hostChoices[i].host === host)) {
                hostCombo.currentIndex = i
                applyHostChoice(i)
                return
            }
        }
    }

    function applyHostChoice(index) {
        if (index < 0 || index >= hostChoices.length) return
        const choice = hostChoices[index]
        const changedHost = choice.host !== selectedHost || choice.envName !== selectedEnvName
        selectedHost = choice.host
        selectedEnvName = choice.envName
        if (choice.platform) selectedPlatform = choice.platform
        if (changedHost) {
            browserError = ""
            browserEntries = []
            selectedIndex = -1
            autocompleteItems = []
            autocompleteVisible = false
            mkdirOpen = false
        }
        if (!choice.configured && choice.host) {
            ensuringHost = true
            browserError = ""
            ensureReqId = backend.ensureRemoteHost(choice.host, "")
        }
    }

    function ensureReadyThen(callback) {
        if (selectedEnvName) {
            callback(selectedEnvName)
            return
        }
        if (!selectedHost) {
            browserError = I18n.t("请先选择一台远程机器")
            return
        }
        root._afterEnsure = callback
        if (!ensuringHost) {
            ensuringHost = true
            browserError = ""
            ensureReqId = backend.ensureRemoteHost(selectedHost, "")
        }
    }
    property var _afterEnsure: null

    function cacheKeyFor(host, dirPath) {
        return String(host || "") + "\n" + String(dirPath || "")
    }

    function invalidateDirCache(host, dirPath) {
        const key = cacheKeyFor(host, dirPath)
        const next = Object.assign({}, dirCache)
        delete next[key]
        dirCache = next
    }

    function requestDirListing(dirPath, opts) {
        const fresh = !!(opts && opts.fresh)
        const purpose = (opts && opts.purpose) || "browse"
        const attempt = (opts && opts.attempt) || 0
        const targetHost = selectedHost
        const targetEnv = selectedEnvName
        if (!targetEnv || !targetHost) return

        const key = cacheKeyFor(targetHost, dirPath)
        const now = Date.now()
        if (!fresh) {
            const cached = dirCache[key]
            if (cached && (now - cached.at) < cacheTtlMs && cached.host === targetHost) {
                applyListingResult(cached.result, purpose, targetHost)
                return
            }
        }

        if (purpose === "browse") {
            browserLoading = true
            browserError = ""
        }

        // Concurrent request merge for identical (host, dirPath) when not bypassing cache.
        if (!fresh && inflightByKey[key]) {
            const existingReq = inflightByKey[key]
            if (pendingRequests[existingReq]) {
                pendingRequests[existingReq].waiters.push({ purpose: purpose, host: targetHost })
                return
            }
        }

        const reqId = backend.browseRemoteDirectory(targetEnv, dirPath)
        const waiters = [{ purpose: purpose, host: targetHost }]
        pendingRequests[reqId] = {
            key: key,
            host: targetHost,
            envName: targetEnv,
            dirPath: dirPath,
            attempt: attempt,
            fresh: fresh,
            waiters: waiters
        }
        if (!fresh) inflightByKey[key] = reqId
    }

    function applyListingResult(result, purpose, expectedHost) {
        // Host-match check: discard stale listings belonging to a different machine.
        if (expectedHost !== selectedHost) return
        if (result.host && result.host !== selectedHost) return

        if (purpose === "browse") {
            browserLoading = false
            if (!result.ok) {
                browserError = result.error || I18n.t("无法读取远程目录")
                return
            }
            browserError = ""
            if (result.platform) selectedPlatform = result.platform
            currentBrowsePath = result.path || ""
            parentBrowsePath = result.parent || ""
            browserEntries = result.directories || result.entries || []
            selectedIndex = browserEntries.length > 0 ? 0 : -1
            if (currentBrowsePath) {
                typedPath = currentBrowsePath
                pathInput.text = currentBrowsePath
            }
        } else if (purpose === "autocomplete") {
            if (!result.ok) {
                autocompleteItems = []
                autocompleteVisible = false
                return
            }
            updateAutocompleteFromEntries(result.path || "", result.directories || result.entries || [])
        }
    }

    function splitForAutocomplete(raw) {
        const text = String(raw || "").trim()
        if (!text) return null
        const isWin = selectedPlatform === "windows" || /^[a-zA-Z]:/.test(text) || text.indexOf("\\") >= 0
        if (isWin) {
            const norm = text.replace(/\//g, "\\")
            if (/^[a-zA-Z]:\\?$/.test(norm)) {
                return { dir: norm.endsWith("\\") ? norm : norm + "\\", prefix: "" }
            }
            const idx = norm.lastIndexOf("\\")
            if (idx < 0) return null
            const dir = idx === 2 && /^[a-zA-Z]:/.test(norm) ? norm.slice(0, 3) : norm.slice(0, idx)
            return { dir: dir, prefix: norm.slice(idx + 1) }
        }
        if (text === "~" || text === "~/") return { dir: "~", prefix: "" }
        const idx = text.lastIndexOf("/")
        if (idx < 0) return null
        const dir = idx === 0 ? "/" : text.slice(0, idx)
        return { dir: dir, prefix: text.slice(idx + 1) }
    }

    function updateAutocompleteFromEntries(baseDir, entries) {
        const split = splitForAutocomplete(typedPath)
        if (!split) {
            autocompleteItems = []
            autocompleteVisible = false
            return
        }
        const needle = split.prefix.toLowerCase()
        const filtered = []
        for (let i = 0; i < entries.length; i++) {
            const item = entries[i]
            const name = String(item.name || "")
            if (!needle || name.toLowerCase().indexOf(needle) === 0 || name.toLowerCase().indexOf(needle) >= 0) {
                filtered.push(item)
                if (filtered.length >= 12) break
            }
        }
        autocompleteItems = filtered
        autocompleteIndex = filtered.length > 0 ? 0 : -1
        autocompleteVisible = filtered.length > 0 && pathInput.activeFocus
    }

    function triggerAutocomplete() {
        if (!selectedEnvName || !typedPath.trim()) {
            autocompleteItems = []
            autocompleteVisible = false
            return
        }
        const split = splitForAutocomplete(typedPath)
        if (!split) {
            autocompleteItems = []
            autocompleteVisible = false
            return
        }
        requestDirListing(split.dir, { fresh: false, purpose: "autocomplete" })
    }

    function acceptAutocomplete(index) {
        if (index < 0 || index >= autocompleteItems.length) return
        const item = autocompleteItems[index]
        const sep = (selectedPlatform === "windows" || String(item.path).indexOf("\\") >= 0) ? "\\" : "/"
        const completed = String(item.path || "").endsWith(sep) ? item.path : (item.path + sep)
        typedPath = completed
        pathInput.text = completed
        pathInput.cursorPosition = completed.length
        autocompleteVisible = false
        autocompleteTimer.restart()
    }

    function openBrowserFresh(pathOverride) {
        const startPath = pathOverride !== undefined ? pathOverride : typedPath.trim()
        browserOpen = true
        autocompleteVisible = false
        mkdirOpen = false
        ensureReadyThen(function() {
            requestDirListing(startPath, { fresh: true, purpose: "browse" })
        })
    }

    function goUpDirectory() {
        if (!selectedEnvName) return
        if (selectedPlatform === "windows") {
            if (!currentBrowsePath) return
            const up = parentBrowsePath || ""
            requestDirListing(up, { fresh: false, purpose: "browse" })
        } else {
            if (!currentBrowsePath || currentBrowsePath === "/") return
            requestDirListing(parentBrowsePath || "/", { fresh: false, purpose: "browse" })
        }
    }

    function enterSelectedDirectory() {
        if (selectedIndex < 0 || selectedIndex >= browserEntries.length) return
        const entry = browserEntries[selectedIndex]
        if (!entry || !entry.path) return
        requestDirListing(entry.path, { fresh: false, purpose: "browse" })
    }

    function joinChildPath(parent, child) {
        const p = String(parent || "")
        const c = String(child || "").trim()
        if (!p) return c
        const sep = (selectedPlatform === "windows" || p.indexOf("\\") >= 0) ? "\\" : "/"
        return p.endsWith(sep) ? (p + c) : (p + sep + c)
    }

    function submitMkdir() {
        const name = mkdirName.trim()
        if (!name || /[\\/\0]/.test(name) || name === "." || name === "..") {
            browserError = I18n.t("请输入有效的目录名")
            return
        }
        const base = currentBrowsePath || typedPath.trim()
        if (!base) {
            browserError = I18n.t("请先进入一个目录后再新建子目录")
            return
        }
        mkdirBusy = true
        browserError = ""
        mkdirTargetPath = joinChildPath(base, name)
        mkdirReqId = backend.createRemoteDirectory(selectedEnvName, mkdirTargetPath)
    }

    function confirmRemoteSelection() {
        if (!allowRemote) return
        const chosen = effectiveSelectedPath
        if (!chosen) return
        ensureReadyThen(function(envName) {
            if (root.allowRemote && backend.setRemoteWorkspace(envName, chosen)) root.finishSelection()
        })
    }

    function handleEscape() {
        if (mkdirOpen) {
            mkdirOpen = false
            mkdirName = ""
            return
        }
        if (autocompleteVisible) {
            autocompleteVisible = false
            return
        }
        if (activeTab === "remote" && browserOpen) {
            browserOpen = false
            pathInput.forceActiveFocus()
            return
        }
        root.close()
    }

    Timer {
        id: autocompleteTimer
        interval: 140
        repeat: false
        onTriggered: root.triggerAutocomplete()
    }

    Connections {
        target: backend
        function onRemoteEnvironmentsChanged() { root.rebuildHostChoices() }
        function onRemoteHostsChanged() { root.rebuildHostChoices() }

        function onRemoteAddHostFinished(reqId, result) {
            if (reqId !== root.ensureReqId) return
            root.ensuringHost = false
            root.ensureReqId = ""
            if (!result.ok) {
                root.browserError = result.error || I18n.t("无法添加远程机器")
                root._afterEnsure = null
                return
            }
            const env = result.environment || {}
            root.selectedEnvName = env.name || ""
            root.selectedHost = env.host || root.selectedHost
            root.selectedPlatform = env.platform || root.selectedPlatform
            root.rebuildHostChoices()
            const cb = root._afterEnsure
            root._afterEnsure = null
            if (cb && root.selectedEnvName) cb(root.selectedEnvName)
        }

        function onRemoteHomeFinished(reqId, result) {
            if (reqId !== root.homeReqId) return
            root.homeLoading = false
            root.homeReqId = ""
            if (!result.ok) {
                root.browserError = result.error || I18n.t("无法获取远程主目录")
                return
            }
            if (result.host && result.host !== root.selectedHost) return
            if (result.platform) root.selectedPlatform = result.platform
            const homePath = result.home || result.cwd || ""
            if (homePath) {
                root.typedPath = homePath
                pathInput.text = homePath
                root.browserOpen = true
                root.requestDirListing(homePath, { fresh: true, purpose: "browse" })
            }
        }

        function onRemoteBrowseFinished(reqId, result) {
            const meta = root.pendingRequests[reqId]
            if (!meta) return
            delete root.pendingRequests[reqId]
            if (root.inflightByKey[meta.key] === reqId) delete root.inflightByKey[meta.key]

            // Auto-retry a failed listing once (except when path simply does not exist).
            if (!result.ok && !result.missing && meta.attempt === 0 && meta.host === root.selectedHost) {
                const retryWaiter = meta.waiters[0] || { purpose: "browse" }
                root.requestDirListing(meta.dirPath, { fresh: true, purpose: retryWaiter.purpose, attempt: 1 })
                return
            }

            if (result.ok && (!result.host || result.host === meta.host)) {
                const nextCache = Object.assign({}, root.dirCache)
                nextCache[meta.key] = { at: Date.now(), host: meta.host, result: result }
                root.dirCache = nextCache
            }

            for (let i = 0; i < meta.waiters.length; i++) {
                root.applyListingResult(result, meta.waiters[i].purpose, meta.waiters[i].host)
            }
        }

        function onRemoteMkdirFinished(reqId, result) {
            if (reqId !== root.mkdirReqId) return
            root.mkdirBusy = false
            root.mkdirReqId = ""
            if (!result.ok) {
                root.browserError = result.error || I18n.t("无法新建目录")
                return
            }
            root.mkdirOpen = false
            root.mkdirName = ""
            const base = root.currentBrowsePath || ""
            root.invalidateDirCache(root.selectedHost, base)
            const created = result.path || root.mkdirTargetPath
            root.typedPath = created
            pathInput.text = created
            root.requestDirListing(created, { fresh: true, purpose: "browse" })
        }
    }

    Overlay.modal: Rectangle { color: Theme.dark ? "#99000000" : "#55000000" }

    background: Rectangle {
        radius: 12
        color: Theme.surface
        border.color: Theme.line
        border.width: 1
    }

    contentItem: Item {
        implicitWidth: root.width
        implicitHeight: dialogColumn.implicitHeight + 36
        Keys.onEscapePressed: event => { root.handleEscape(); event.accepted = true }

        ColumnLayout {
            id: dialogColumn
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 18
            spacing: 14

            // Header row: title + close button
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Text {
                    Layout.fillWidth: true
                    text: I18n.t("选择工作目录")
                    color: Theme.ink
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.font(16)
                    font.weight: Font.DemiBold
                }
                Button {
                    objectName: "workspacePickerClose"
                    implicitWidth: Theme.control(28)
                    implicitHeight: Theme.control(28)
                    hoverEnabled: true
                    padding: 0
                    Accessible.name: I18n.t("关闭")
                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                    background: Rectangle {
                        radius: 6
                        color: parent.hovered ? Theme.hover : "transparent"
                    }
                    contentItem: Glyph {
                        name: "x"
                        color: Theme.muted
                        anchors.centerIn: parent
                        width: Theme.icon(16)
                        height: Theme.icon(16)
                    }
                    onClicked: root.close()
                }
            }

            // Segmented tabs: 本机 / 远程
            Rectangle {
                visible: root.allowRemote
                implicitHeight: Theme.control(34)
                implicitWidth: tabRow.implicitWidth + 8
                radius: 8
                color: Theme.bg
                border.color: Theme.line
                Row {
                    id: tabRow
                    anchors.centerIn: parent
                    spacing: 4
                    Button {
                        objectName: "workspaceTabLocal"
                        implicitHeight: Theme.control(26)
                        leftPadding: 14; rightPadding: 14
                        hoverEnabled: true
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        background: Rectangle {
                            radius: 6
                            color: root.activeTab === "local" ? Theme.surface : (parent.hovered ? Theme.hover : "transparent")
                            border.color: root.activeTab === "local" ? Theme.line : "transparent"
                        }
                        contentItem: Text {
                            text: I18n.t("本机")
                            color: root.activeTab === "local" ? Theme.ink : Theme.muted
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.font(13)
                            font.weight: root.activeTab === "local" ? Font.DemiBold : Font.Normal
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        onClicked: root.activeTab = "local"
                    }
                    Button {
                        objectName: "workspaceTabRemote"
                        visible: root.allowRemote
                        implicitHeight: Theme.control(26)
                        leftPadding: 14; rightPadding: 14
                        hoverEnabled: true
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        background: Rectangle {
                            radius: 6
                            color: root.activeTab === "remote" ? Theme.surface : (parent.hovered ? Theme.hover : "transparent")
                            border.color: root.activeTab === "remote" ? Theme.line : "transparent"
                        }
                        contentItem: Text {
                            text: I18n.t("远程")
                            color: root.activeTab === "remote" ? Theme.ink : Theme.muted
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.font(13)
                            font.weight: root.activeTab === "remote" ? Font.DemiBold : Font.Normal
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        onClicked: {
                            root.activeTab = "remote"
                            backend.refreshSshConfigHosts()
                            root.rebuildHostChoices()
                            Qt.callLater(() => pathInput.forceActiveFocus())
                        }
                    }
                }
            }

            // Local Tab Content
            ColumnLayout {
                Layout.fillWidth: true
                visible: root.activeTab === "local"
                spacing: 12

                Text {
                    Layout.fillWidth: true
                    text: I18n.t("选择本机文件夹作为当前会话的工作目录。")
                    color: Theme.muted
                    wrapMode: Text.Wrap
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.font(13)
                }

                Picker {
                    id: recentLocalFolders
                    objectName: "workspaceRecentLocal"
                    Layout.fillWidth: true
                    readonly property var folders: root.visible && root.newConversation ?
                        backend.projectRows.filter(row => row.kind === "project" && !row.isRemote) : []
                    visible: folders.length > 0
                    model: [I18n.t("已打开的目录")].concat(folders.map(row => row.title + "  ·  " + row.path))
                    currentIndex: 0
                    Accessible.name: I18n.t("已打开的目录")
                    onActivated: index => {
                        if (index > 0) root.chooseLocalUrl(folders[index - 1].path)
                        currentIndex = 0
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    TextField {
                        id: localPathInput
                        objectName: "localPathInput"
                        Layout.fillWidth: true
                        implicitHeight: Theme.control(38)
                        placeholderText: I18n.t("输入或浏览本机目录路径")
                        placeholderTextColor: Theme.muted
                        color: Theme.ink
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.font(13)
                        selectByMouse: true
                        leftPadding: 12; rightPadding: 12
                        background: Rectangle {
                            radius: 8
                            color: Theme.bg
                            border.color: localPathInput.activeFocus ? Theme.accent : Theme.line
                        }
                        onTextChanged: {
                            root.localProjectStatus = ""
                            root.pendingLocalProjectPath = ""
                        }
                        Keys.onReturnPressed: if (text.trim()) root.chooseTypedLocal(false)
                        Keys.onEnterPressed: if (text.trim()) root.chooseTypedLocal(false)
                    }
                    Button {
                        objectName: "localBrowseButton"
                        implicitHeight: Theme.control(38)
                        leftPadding: 14; rightPadding: 14
                        hoverEnabled: true
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        background: Rectangle {
                            radius: 8
                            color: parent.hovered ? Theme.hover : Theme.bg
                            border.color: Theme.line
                        }
                        contentItem: Text {
                            text: I18n.t("浏览…")
                            color: Theme.ink
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.font(13)
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        onClicked: {
                            root.close()
                            root.browseLocalRequested()
                        }
                    }
                }

                Text {
                    objectName: "localProjectStatus"
                    Layout.fillWidth: true
                    visible: root.localProjectStatus.length > 0
                    text: visible ? root.localProjectText(root.localProjectStatus) : ""
                    color: root.localProjectStatus === "missing" ? Theme.muted : Theme.danger
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.font(12)
                    wrapMode: Text.Wrap
                    textFormat: Text.PlainText
                }
                RowLayout {
                    Layout.fillWidth: true
                    Item { Layout.fillWidth: true }
                    ActionButton {
                        objectName: "localCreateProjectButton"
                        visible: !root.newConversation && root.pendingLocalProjectPath.length > 0
                        enabled: visible
                        text: backend.language === "en" ? "Create folder and project" : "创建目录并新建项目"
                        primary: true
                        onClicked: root.chooseTypedLocal(true)
                    }
                    Button {
                        objectName: "localChooseButton"
                        visible: root.pendingLocalProjectPath.length === 0
                        enabled: localPathInput.text.trim().length > 0
                        implicitHeight: Theme.control(36)
                        leftPadding: 16; rightPadding: 16
                        hoverEnabled: true
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        background: Rectangle {
                            radius: 8
                            color: parent.enabled ? Theme.button : Theme.hover
                            opacity: parent.enabled ? (parent.hovered ? 0.9 : 1.0) : 0.5
                        }
                        contentItem: Text {
                            text: I18n.t("选用此路径")
                            color: parent.enabled ? Theme.buttonText : Theme.muted
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.font(13)
                            font.weight: Font.DemiBold
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        onClicked: root.chooseTypedLocal(false)
                    }
                }
            }

            // Remote Tab Content (matches target-dialog.jpg order)
            ColumnLayout {
                Layout.fillWidth: true
                visible: root.activeTab === "remote"
                spacing: 12

                // 1. Host row
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    Text {
                        text: I18n.t("远程机器：")
                        color: Theme.muted
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.font(13)
                    }
                    ComboBox {
                        id: hostCombo
                        objectName: "remoteHostCombo"
                        Layout.preferredWidth: 240
                        implicitHeight: Theme.control(34)
                        model: root.hostChoices.map(item => item.label)
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.font(13)
                        palette.text: Theme.ink
                        palette.buttonText: Theme.ink
                        palette.base: Theme.surface
                        palette.window: Theme.surface
                        palette.highlight: Theme.accentBg
                        palette.highlightedText: Theme.ink
                        Accessible.name: I18n.t("远程机器")
                        onActivated: index => root.applyHostChoice(index)
                        background: Rectangle {
                            radius: 7
                            color: Theme.bg
                            border.color: hostCombo.activeFocus ? Theme.accent : Theme.line
                        }
                        contentItem: Text {
                            text: hostCombo.count > 0 ? hostCombo.displayText : I18n.t("未找到远程机器")
                            font: hostCombo.font
                            color: hostCombo.count > 0 ? Theme.ink : Theme.muted
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                            leftPadding: 10
                            rightPadding: 28
                        }
                        indicator: Glyph {
                            name: "chevron-down"
                            width: Theme.icon(13)
                            height: width
                            x: parent.width - width - 10
                            y: (parent.height - height) / 2
                            color: Theme.muted
                        }
                    }
                    RowLayout {
                        visible: root.isReconnecting
                        spacing: 6
                        BusyIndicator {
                            running: root.isReconnecting
                            Layout.preferredWidth: Theme.icon(16)
                            Layout.preferredHeight: Theme.icon(16)
                        }
                        Text {
                            objectName: "remoteReconnectingLabel"
                            text: I18n.t("正在重新连接")
                            color: Theme.muted
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.font(12)
                        }
                    }
                    Item { Layout.fillWidth: true }
                }

                // 2. Path input row + Browse... + ~ Home
                Item {
                    Layout.fillWidth: true
                    implicitHeight: pathRow.implicitHeight
                    z: 20

                    RowLayout {
                        id: pathRow
                        anchors.left: parent.left
                        anchors.right: parent.right
                        spacing: 8

                        TextField {
                            id: pathInput
                            objectName: "remotePathInput"
                            Layout.fillWidth: true
                            implicitHeight: Theme.control(38)
                            placeholderText: I18n.t("输入远程路径（自动补全）")
                            placeholderTextColor: Theme.muted
                            color: Theme.ink
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.font(13)
                            selectByMouse: true
                            leftPadding: 12; rightPadding: 12
                            background: Rectangle {
                                radius: 8
                                color: Theme.bg
                                border.color: pathInput.activeFocus ? Theme.accent : Theme.line
                            }
                            onTextEdited: {
                                root.typedPath = text
                                root.browserError = ""
                                autocompleteTimer.restart()
                            }
                            Keys.onDownPressed: event => {
                                if (root.autocompleteVisible && root.autocompleteItems.length > 0) {
                                    root.autocompleteIndex = (root.autocompleteIndex + 1) % root.autocompleteItems.length
                                    event.accepted = true
                                } else if (root.browserOpen && root.browserEntries.length > 0) {
                                    dirListView.forceActiveFocus()
                                    event.accepted = true
                                }
                            }
                            Keys.onUpPressed: event => {
                                if (root.autocompleteVisible && root.autocompleteItems.length > 0) {
                                    root.autocompleteIndex = (root.autocompleteIndex - 1 + root.autocompleteItems.length) % root.autocompleteItems.length
                                    event.accepted = true
                                }
                            }
                            Keys.onTabPressed: event => {
                                if (root.autocompleteVisible && root.autocompleteIndex >= 0) {
                                    root.acceptAutocomplete(root.autocompleteIndex)
                                    event.accepted = true
                                }
                            }
                            Keys.onReturnPressed: event => {
                                if (root.autocompleteVisible && root.autocompleteIndex >= 0) {
                                    root.acceptAutocomplete(root.autocompleteIndex)
                                } else {
                                    root.openBrowserFresh(pathInput.text.trim())
                                }
                                event.accepted = true
                            }
                            Keys.onEscapePressed: event => {
                                root.handleEscape()
                                event.accepted = true
                            }
                        }

                        Button {
                            objectName: "remoteBrowseButton"
                            implicitHeight: Theme.control(38)
                            leftPadding: 14; rightPadding: 14
                            hoverEnabled: true
                            enabled: !!root.selectedHost
                            HoverHandler { cursorShape: Qt.PointingHandCursor }
                            background: Rectangle {
                                radius: 8
                                color: parent.hovered ? Theme.hover : Theme.bg
                                border.color: Theme.line
                            }
                            contentItem: Text {
                                text: I18n.t("浏览…")
                                color: Theme.ink
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.font(13)
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                            onClicked: root.openBrowserFresh()
                        }

                        Button {
                            objectName: "remoteHomeButton"
                            implicitHeight: Theme.control(38)
                            leftPadding: 12; rightPadding: 12
                            hoverEnabled: true
                            enabled: !!root.selectedHost && !root.homeLoading
                            HoverHandler { cursorShape: Qt.PointingHandCursor }
                            background: Rectangle {
                                radius: 8
                                color: parent.hovered ? Theme.hover : Theme.bg
                                border.color: Theme.line
                            }
                            contentItem: Text {
                                text: I18n.t("~ 主目录")
                                color: Theme.ink
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.font(13)
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                            onClicked: {
                                root.autocompleteVisible = false
                                root.browserError = ""
                                root.ensureReadyThen(function(envName) {
                                    root.homeLoading = true
                                    root.homeReqId = backend.fetchRemoteHome(envName)
                                })
                            }
                        }
                    }

                    // Autocomplete dropdown anchored directly below pathInput
                    Rectangle {
                        id: autocompleteBox
                        objectName: "remoteAutocompleteBox"
                        visible: root.autocompleteVisible && root.autocompleteItems.length > 0
                        x: pathInput.x
                        y: pathInput.y + pathInput.height + 4
                        width: pathInput.width
                        height: Math.min(autocompleteList.contentHeight + 8, 220)
                        radius: 8
                        color: Theme.surface
                        border.color: Theme.line
                        z: 30

                        ListView {
                            id: autocompleteList
                            anchors.fill: parent
                            anchors.margins: 4
                            clip: true
                            model: root.autocompleteItems
                            delegate: Rectangle {
                                required property var modelData
                                required property int index
                                width: autocompleteList.width
                                height: Theme.control(30)
                                radius: 6
                                color: index === root.autocompleteIndex || autoHover.hovered ? Theme.hover : "transparent"
                                HoverHandler { id: autoHover; cursorShape: Qt.PointingHandCursor }
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 8
                                    anchors.rightMargin: 8
                                    spacing: 8
                                    Glyph {
                                        name: "folder"
                                        color: "#d99b26"
                                        Layout.preferredWidth: Theme.icon(14)
                                        Layout.preferredHeight: Theme.icon(14)
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: modelData.name
                                        textFormat: Text.PlainText
                                        color: Theme.ink
                                        elide: Text.ElideRight
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.font(13)
                                    }
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    onClicked: root.acceptAutocomplete(index)
                                }
                            }
                        }
                    }
                }

                // 3. Directory browser panel (bordered card)
                Rectangle {
                    id: browserPanel
                    objectName: "remoteBrowserPanel"
                    Layout.fillWidth: true
                    visible: root.browserOpen
                    implicitHeight: browserLayout.implicitHeight
                    radius: 10
                    color: Theme.bg
                    border.color: Theme.line
                    clip: true

                    ColumnLayout {
                        id: browserLayout
                        anchors.left: parent.left
                        anchors.right: parent.right
                        spacing: 0

                        // Browser toolbar: ^ 回上一级 | current path | 新建目录 | ×
                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: Theme.control(44)
                            color: "transparent"
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                spacing: 10

                                Button {
                                    id: upButton
                                    objectName: "remoteUpButton"
                                    implicitHeight: Theme.control(28)
                                    leftPadding: 10; rightPadding: 10
                                    hoverEnabled: true
                                    enabled: root.selectedPlatform === "windows" ? (root.currentBrowsePath !== "") : (root.currentBrowsePath !== "" && root.currentBrowsePath !== "/")
                                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                                    background: Rectangle {
                                        radius: 6
                                        color: upButton.hovered ? Theme.hover : Theme.surface
                                        border.color: Theme.line
                                    }
                                    contentItem: Row {
                                        spacing: 4
                                        Glyph {
                                            name: "chevron-up"
                                            color: upButton.enabled ? Theme.ink : Theme.muted
                                            width: Theme.icon(12)
                                            height: Theme.icon(12)
                                            anchors.verticalCenter: parent.verticalCenter
                                        }
                                        Text {
                                            text: I18n.t("回上一级")
                                            color: upButton.enabled ? Theme.ink : Theme.muted
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.font(12)
                                            anchors.verticalCenter: parent.verticalCenter
                                        }
                                    }
                                    onClicked: root.goUpDirectory()
                                }

                                Text {
                                    objectName: "remoteBrowsePathLabel"
                                    Layout.fillWidth: true
                                    text: root.currentBrowsePath || (root.selectedPlatform === "windows" ? I18n.t("磁盘列表") : "/")
                                    textFormat: Text.PlainText
                                    elide: Text.ElideMiddle
                                    color: Theme.muted
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.font(12)
                                }

                                Button {
                                    id: mkdirBtn
                                    objectName: "remoteMkdirButton"
                                    implicitHeight: Theme.control(28)
                                    leftPadding: 10; rightPadding: 10
                                    hoverEnabled: true
                                    enabled: !!root.currentBrowsePath && !root.browserLoading
                                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                                    background: Rectangle {
                                        radius: 6
                                        color: mkdirBtn.hovered ? Theme.hover : Theme.surface
                                        border.color: Theme.line
                                    }
                                    contentItem: Text {
                                        text: I18n.t("新建目录")
                                        color: mkdirBtn.enabled ? Theme.ink : Theme.muted
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.font(12)
                                        horizontalAlignment: Text.AlignHCenter
                                        verticalAlignment: Text.AlignVCenter
                                    }
                                    onClicked: {
                                        root.mkdirOpen = !root.mkdirOpen
                                        root.mkdirName = ""
                                        if (root.mkdirOpen) Qt.callLater(() => mkdirInput.forceActiveFocus())
                                    }
                                }

                                Button {
                                    objectName: "remoteBrowserCloseButton"
                                    implicitWidth: Theme.control(26)
                                    implicitHeight: Theme.control(26)
                                    padding: 0
                                    hoverEnabled: true
                                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                                    background: Rectangle {
                                        radius: 6
                                        color: parent.hovered ? Theme.hover : "transparent"
                                    }
                                    contentItem: Glyph {
                                        name: "x"
                                        color: Theme.muted
                                        anchors.centerIn: parent
                                        width: Theme.icon(14)
                                        height: Theme.icon(14)
                                    }
                                    onClicked: {
                                        root.browserOpen = false
                                        pathInput.forceActiveFocus()
                                    }
                                }
                            }
                        }

                        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }

                        // Inline mkdir input bar
                        Rectangle {
                            Layout.fillWidth: true
                            visible: root.mkdirOpen
                            implicitHeight: Theme.control(44)
                            color: Theme.surface
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                spacing: 8
                                TextField {
                                    id: mkdirInput
                                    objectName: "remoteMkdirInput"
                                    Layout.fillWidth: true
                                    implicitHeight: Theme.control(30)
                                    text: root.mkdirName
                                    placeholderText: I18n.t("输入新目录名")
                                    placeholderTextColor: Theme.muted
                                    color: Theme.ink
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.font(12)
                                    selectByMouse: true
                                    leftPadding: 10; rightPadding: 10
                                    background: Rectangle {
                                        radius: 6
                                        color: Theme.bg
                                        border.color: mkdirInput.activeFocus ? Theme.accent : Theme.line
                                    }
                                    onTextEdited: root.mkdirName = text
                                    Keys.onReturnPressed: event => { root.submitMkdir(); event.accepted = true }
                                    Keys.onEscapePressed: event => { root.mkdirOpen = false; event.accepted = true }
                                }
                                Button {
                                    objectName: "remoteMkdirConfirm"
                                    implicitHeight: Theme.control(30)
                                    leftPadding: 12; rightPadding: 12
                                    enabled: !root.mkdirBusy && root.mkdirName.trim().length > 0
                                    hoverEnabled: true
                                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                                    background: Rectangle {
                                        radius: 6
                                        color: parent.enabled ? Theme.button : Theme.hover
                                    }
                                    contentItem: Text {
                                        text: I18n.t("创建")
                                        color: parent.enabled ? Theme.buttonText : Theme.muted
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.font(12)
                                        horizontalAlignment: Text.AlignHCenter
                                        verticalAlignment: Text.AlignVCenter
                                    }
                                    onClicked: root.submitMkdir()
                                }
                                Button {
                                    implicitHeight: Theme.control(30)
                                    leftPadding: 10; rightPadding: 10
                                    hoverEnabled: true
                                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                                    background: Rectangle {
                                        radius: 6
                                        color: parent.hovered ? Theme.hover : "transparent"
                                        border.color: Theme.line
                                    }
                                    contentItem: Text {
                                        text: I18n.t("取消")
                                        color: Theme.muted
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.font(12)
                                        horizontalAlignment: Text.AlignHCenter
                                        verticalAlignment: Text.AlignVCenter
                                    }
                                    onClicked: { root.mkdirOpen = false; root.mkdirName = "" }
                                }
                            }
                        }
                        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line; visible: root.mkdirOpen }

                        // Directory listing body
                        Item {
                            Layout.fillWidth: true
                            implicitHeight: Theme.control(34) * 8
                            clip: true

                            ListView {
                                id: dirListView
                                objectName: "remoteDirList"
                                anchors.fill: parent
                                visible: !root.browserLoading && root.browserEntries.length > 0
                                clip: true
                                boundsBehavior: Flickable.StopAtBounds
                                model: root.browserEntries
                                currentIndex: root.selectedIndex
                                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                                Keys.onDownPressed: event => {
                                    if (root.browserEntries.length > 0) {
                                        root.selectedIndex = Math.min(root.browserEntries.length - 1, root.selectedIndex + 1)
                                        positionViewAtIndex(root.selectedIndex, ListView.Contain)
                                    }
                                    event.accepted = true
                                }
                                Keys.onUpPressed: event => {
                                    if (root.browserEntries.length > 0) {
                                        root.selectedIndex = Math.max(0, root.selectedIndex - 1)
                                        positionViewAtIndex(root.selectedIndex, ListView.Contain)
                                    }
                                    event.accepted = true
                                }
                                Keys.onReturnPressed: event => { root.enterSelectedDirectory(); event.accepted = true }
                                Keys.onEnterPressed: event => { root.enterSelectedDirectory(); event.accepted = true }
                                Keys.onEscapePressed: event => { root.handleEscape(); event.accepted = true }

                                delegate: Item {
                                    required property var modelData
                                    required property int index
                                    width: dirListView.width
                                    height: Theme.control(34)

                                    Rectangle {
                                        anchors.fill: parent
                                        color: index === root.selectedIndex ? Theme.hover : (rowHover.hovered ? Theme.accentBg : "transparent")
                                    }
                                    Rectangle {
                                        anchors.left: parent.left
                                        anchors.right: parent.right
                                        anchors.bottom: parent.bottom
                                        height: 1
                                        color: Theme.line
                                        opacity: 0.45
                                    }
                                    HoverHandler { id: rowHover; cursorShape: Qt.PointingHandCursor }
                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 12
                                        anchors.rightMargin: 12
                                        spacing: 10
                                        Glyph {
                                            name: modelData.isDrive ? "server" : "folder"
                                            color: "#d99b26"
                                            Layout.preferredWidth: Theme.icon(15)
                                            Layout.preferredHeight: Theme.icon(15)
                                        }
                                        Text {
                                            Layout.fillWidth: true
                                            text: modelData.name
                                            textFormat: Text.PlainText
                                            elide: Text.ElideRight
                                            color: Theme.ink
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.font(13)
                                        }
                                    }
                                    MouseArea {
                                        anchors.fill: parent
                                        onClicked: {
                                            root.selectedIndex = index
                                            dirListView.forceActiveFocus()
                                        }
                                        onDoubleClicked: {
                                            root.selectedIndex = index
                                            root.enterSelectedDirectory()
                                        }
                                    }
                                }
                            }

                            // Loading / Reconnecting / Empty / Error placeholder
                            ColumnLayout {
                                anchors.centerIn: parent
                                width: parent.width - 32
                                spacing: 8
                                visible: root.browserLoading || root.browserEntries.length === 0

                                BusyIndicator {
                                    Layout.alignment: Qt.AlignHCenter
                                    running: root.browserLoading || root.isReconnecting
                                    visible: running
                                    Layout.preferredWidth: Theme.icon(24)
                                    Layout.preferredHeight: Theme.icon(24)
                                }

                                Text {
                                    objectName: "remoteBrowserStatusText"
                                    Layout.fillWidth: true
                                    horizontalAlignment: Text.AlignHCenter
                                    wrapMode: Text.Wrap
                                    textFormat: Text.PlainText
                                    text: root.isReconnecting ? I18n.t("正在重新连接")
                                        : root.browserLoading ? I18n.t("正在加载…")
                                        : root.browserError ? root.browserError
                                        : I18n.t("此目录下没有子目录")
                                    color: (!root.isReconnecting && !root.browserLoading && root.browserError) ? Theme.danger : Theme.muted
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.font(13)
                                }
                            }
                        }

                        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }

                        // Browser footer: 所选：…  |  选用此路径
                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: Theme.control(52)
                            color: "transparent"
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 12
                                anchors.rightMargin: 12
                                spacing: 12

                                Text {
                                    objectName: "remoteSelectedLabel"
                                    Layout.fillWidth: true
                                    text: I18n.t("所选：") + (root.effectiveSelectedPath || I18n.t("未选择"))
                                    textFormat: Text.PlainText
                                    elide: Text.ElideMiddle
                                    color: Theme.muted
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.font(12)
                                }

                                Button {
                                    id: chooseBtn
                                    objectName: "remoteChooseButton"
                                    implicitHeight: Theme.control(34)
                                    leftPadding: 16; rightPadding: 16
                                    enabled: !!root.selectedHost && !!root.effectiveSelectedPath
                                    hoverEnabled: true
                                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                                    background: Rectangle {
                                        radius: 7
                                        color: chooseBtn.enabled ? Theme.button : Theme.hover
                                        opacity: chooseBtn.enabled ? (chooseBtn.hovered ? 0.9 : 1.0) : 0.5
                                    }
                                    contentItem: Text {
                                        text: I18n.t("选用此路径")
                                        color: chooseBtn.enabled ? Theme.buttonText : Theme.muted
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.font(13)
                                        font.weight: Font.DemiBold
                                        horizontalAlignment: Text.AlignHCenter
                                        verticalAlignment: Text.AlignVCenter
                                    }
                                    onClicked: root.confirmRemoteSelection()
                                }
                            }
                        }
                    }
                }

                // Error line + direct choose button when browser pane is collapsed
                RowLayout {
                    Layout.fillWidth: true
                    visible: !root.browserOpen
                    spacing: 10
                    Text {
                        Layout.fillWidth: true
                        visible: !!root.browserError && !root.isReconnecting
                        text: root.browserError
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        color: Theme.danger
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.font(12)
                    }
                    Item { Layout.fillWidth: true; visible: !root.browserError || root.isReconnecting }
                    Button {
                        objectName: "remoteDirectChooseButton"
                        implicitHeight: Theme.control(34)
                        leftPadding: 16; rightPadding: 16
                        enabled: !!root.selectedHost && root.typedPath.trim().length > 0
                        hoverEnabled: true
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        background: Rectangle {
                            radius: 7
                            color: parent.enabled ? Theme.button : Theme.hover
                            opacity: parent.enabled ? (parent.hovered ? 0.9 : 1.0) : 0.5
                        }
                        contentItem: Text {
                            text: I18n.t("选用此路径")
                            color: parent.enabled ? Theme.buttonText : Theme.muted
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.font(13)
                            font.weight: Font.DemiBold
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        onClicked: root.confirmRemoteSelection()
                    }
                }

                // 4. Keyboard hint line (matches target-dialog.jpg)
                Text {
                    objectName: "remoteKeyboardHint"
                    Layout.fillWidth: true
                    text: I18n.t("Enter 进入目录  Esc 返回路径输入")
                    color: Theme.muted
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.font(12)
                }
            }
        }
    }
}
