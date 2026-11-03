import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../git-viewer/qml" as Git

Rectangle {
    id: root
    objectName: "changeReviewWidget"
    required property var sdk
    readonly property var c: sdk.colors
    readonly property real s: sdk.scale
    property string viewMode: "timeline"
    property string filterKind: "all"
    property var timelineResult: ({entries: []})
    property var timelineRows: []
    property var latestReport: ({total: 0, empty: true})
    property var report: ({total: 0, empty: true})
    property string selectedCheckpoint: ""
    property var cache: ({})
    property var expanded: ({})
    property var requests: ({})
    property var contextEntry: ({})
    property var diffEntry: ({})
    property string selected: ""
    property string diff: ""
    property var lines: []
    property string error: ""
    property bool truncated: false
    property bool clipped: false
    property int loading: 0
    property int epoch: 0
    property string diffRequest: ""
    property string targetToken: ""
    property string configRequest: ""
    property string configError: ""
    property var restoreReport: ({entries: []})
    property var restoreResult: ({})
    property string lockRequest: ""
    property string lockToken: ""
    property string releaseRequest: ""
    color: c.surface
    readonly property color addInk: c.dark ? "#6ee7a0" : "#146c36"
    readonly property color removeInk: c.dark ? "#ff8f96" : "#a92132"
    readonly property color modifyInk: c.dark ? "#f5d773" : "#755100"
    readonly property color metaInk: c.dark ? "#a9b7c6" : "#4d5d6c"
    readonly property color addBg: c.dark ? Qt.rgba(.2,.75,.4,.22) : Qt.rgba(.1,.55,.25,.16)
    readonly property color removeBg: c.dark ? Qt.rgba(.9,.25,.3,.24) : Qt.rgba(.85,.18,.25,.15)
    readonly property color modifyBg: c.dark ? Qt.rgba(.86,.66,.12,.24) : Qt.rgba(.86,.66,.12,.13)

    function statusInk(status) {
        return status === "A" ? addInk : status === "D" ? removeInk : status === "M" ? modifyInk : metaInk
    }
    function statusBg(status) {
        return status === "A" ? Qt.rgba(.1,.55,.25,.07) : status === "D" ? Qt.rgba(.85,.18,.25,.06) : status === "M" ? Qt.rgba(.86,.66,.12,.07) : "transparent"
    }
    function actionInk(action) {
        return action === "create" ? addInk : action === "delete" || action === "conflict" || action === "unavailable" ? removeInk : action === "restore" ? modifyInk : metaInk
    }
    function timelineBg(index) {
        const currentIndex = timelineRows.findIndex(row => row.checkpointId === (timelineResult.currentId || ""))
        return index === currentIndex ? Qt.rgba(.12,.62,.30,.22) : currentIndex >= 0 && index < currentIndex ? Qt.rgba(.86,.18,.24,.18) : Qt.rgba(.86,.66,.12,.17)
    }
    function timelineInk(index) {
        const currentIndex = timelineRows.findIndex(row => row.checkpointId === (timelineResult.currentId || ""))
        return index === currentIndex ? root.addInk : currentIndex >= 0 && index < currentIndex ? root.removeInk : root.modifyInk
    }
    function t(zh, en) { return sdk.language.indexOf("zh") === 0 ? zh : en }
    function saveSetting(name, value) {
        configError = ""
        const config = Object.assign({}, sdk.config)
        config[name] = value
        configRequest = sdk.saveConfig(config)
        if (!configRequest) configError = t("保存失败，请重试", "Could not save. Please retry.")
    }
    function call(method, args, kind) {
        const token = sdk.call(method, args || {})
        if (!token) { error = t("插件暂时繁忙，请稍后重试", "The Widget is busy. Please retry."); return "" }
        const pending = Object.assign({}, requests)
        pending[token] = {kind: kind || method, path: (args || {}).path || "", epoch: epoch}
        requests = pending; loading++
        return token
    }
    function resetFiles() {
        cache = ({}); expanded = ({}); selected = ""; diff = ""; lines = []; diffRequest = ""
        error = ""; clipped = false; tree.clear()
    }
    function load(refresh, reset) {
        if (reset) {
            fileMenu.close(); epoch++; requests = ({}); loading = 0
            viewMode = "timeline"; selectedCheckpoint = ""; report = ({total: 0, empty: true}); resetFiles()
        }
        call("timeline", {kind: filterKind, offset: 0, limit: 100}, "timeline")
        call(refresh ? "refresh" : "status", {}, "status")
    }
    function rebuildTimeline() {
        const rows = (timelineResult.entries || []).slice()
        if (latestReport.total && !latestReport.active && !latestReport.checkpointId) {
            rows.unshift({checkpointId: "", title: t("本轮变更", "Current turn"), total: latestReport.total,
                added: latestReport.addedTotal || 0, removed: latestReport.removedTotal || 0, ended: latestReport.ended || 0, kind: "agent", state: "complete",
                limited: !!latestReport.limited, restorable: false, pinned: false, active: false, loopId: latestReport.loopId})
        }
        timelineRows = rows.map((row, index) => Object.assign({}, row, {rowIndex: index}))
    }
    function openCheckpoint(identifier) {
        epoch++; requests = ({}); loading = 0; resetFiles()
        selectedCheckpoint = identifier
        report = identifier ? (timelineRows.find(row => row.checkpointId === identifier) || {checkpointId: identifier}) : latestReport
        viewMode = "files"
        loadTree("", false)
    }
    function loadTree(path, more) {
        if (Object.values(requests).some(item => item.kind === "tree" && item.path === path)) return
        call("tree", {path: path, offset: more && cache[path] ? cache[path].entries.length : 0,
            loopId: report.loopId || "", checkpointId: selectedCheckpoint}, "tree")
    }
    function rebuild() {
        tree.clear()
        function append(path, depth) {
            if (depth > 32) { root.clipped = true; return }
            const group = cache[path]
            if (!group) return
            for (const row of group.entries) {
                if (tree.count >= 4000) { root.clipped = true; return }
                tree.append({name: row.name, path: row.path, directory: row.directory, depth: depth,
                    expanded: !!expanded[row.path], more: false, status: row.status,
                    added: row.added, removed: row.removed, omitted: row.omitted, binary: row.binary, count: row.count})
                if (row.directory && expanded[row.path]) append(row.path, depth + 1)
            }
            if (group.hasMore && tree.count < 4000) tree.append({name: t("加载更多", "Load more"), path: path, directory: false,
                depth: depth, expanded: false, more: true, status: "", added: -1, removed: -1, omitted: false, binary: false, count: 0})
        }
        append("", 0)
    }
    function toggle(path) {
        const next = Object.assign({}, expanded); next[path] = !expanded[path]; expanded = next
        if (next[path] && !cache[path]) loadTree(path, false)
        rebuild()
    }
    function lookup(path) {
        for (const group of Object.values(cache)) {
            const entry = group.entries.find(row => !row.directory && row.path === path)
            if (entry) return entry
        }
        return {path: path, status: ""}
    }
    function show(path) {
        selected = path; diffEntry = lookup(path); diff = ""; lines = []; error = ""; truncated = false
        viewMode = "diff"
        diffRequest = call("diff", {path: path, loopId: report.loopId || "", checkpointId: selectedCheckpoint}, "diff")
    }
    function back() {
        fileMenu.close(); error = ""; diffRequest = ""; selected = ""; diff = ""; lines = []
        if (viewMode === "diff" || viewMode === "restoreDiff") viewMode = viewMode === "diff" ? "files" : "restore"
        else if (viewMode === "restore") viewMode = "files"
        else { viewMode = "timeline"; selectedCheckpoint = ""; report = ({total: 0, empty: true}); resetFiles(); load(false, false) }
    }
    function contextMenuAt(item, x, y, entry) {
        contextEntry = entry
        const point = item.mapToItem(root, x, y); fileMenu.x = point.x; fileMenu.y = point.y; fileMenu.open()
    }
    function parse(text) {
        let oldLine = 0, newLine = 0, hunk = false, result = []
        for (const textLine of text.split("\n")) {
            if (!hunk && /^(diff --git |index |--- |\+\+\+ )/.test(textLine)) continue
            const match = /^@@ -(\d+)(?:,\d+)? \+(\d+)/.exec(textLine)
            let oldNumber = "", newNumber = "", kind = "meta"
            if (match) { oldLine = Number(match[1]); newLine = Number(match[2]); hunk = true }
            else if (hunk && textLine.startsWith("+")) { newNumber = String(newLine++); kind = "add" }
            else if (hunk && textLine.startsWith("-")) { oldNumber = String(oldLine++); kind = "remove" }
            else if (hunk && textLine.startsWith(" ")) { newNumber = String(newLine++); kind = "context" }
            result.push({text: textLine, oldNumber: oldNumber, newNumber: newNumber, kind: kind})
        }
        return result
    }
    function relativeTime(timestamp) {
        if (!timestamp) return ""
        const seconds = Math.max(0, Math.floor(Date.now() / 1000 - timestamp))
        if (seconds < 60) return t("刚刚", "now")
        if (seconds < 3600) return Math.floor(seconds / 60) + t(" 分钟前", "m ago")
        if (seconds < 86400) return Math.floor(seconds / 3600) + t(" 小时前", "h ago")
        return Math.floor(seconds / 86400) + t(" 天前", "d ago")
    }
    function fullTime(timestamp) {
        return timestamp ? new Date(timestamp * 1000).toLocaleString() : ""
    }
    function cycleFilter() {
        filterKind = filterKind === "all" ? "agent" : filterKind === "agent" ? "origin" : "all"
        load(false, false)
    }
    function switchDirection() {
        const current = timelineResult.currentId || ""
        if (!current || current === selectedCheckpoint) return t("当前版本", "Current version")
        const selectedIndex = timelineRows.findIndex(row => row.checkpointId === selectedCheckpoint)
        const currentIndex = timelineRows.findIndex(row => row.checkpointId === current)
        return selectedIndex >= 0 && currentIndex >= 0 && selectedIndex < currentIndex ? t("前进到较新版本", "Move to newer version") : t("恢复到较旧版本", "Restore older version")
    }
    function previewRestore() {
        restoreReport = ({entries: []}); restoreResult = ({}); error = ""
        call("restorePreview", {checkpointId: selectedCheckpoint}, "restorePreview")
    }
    function confirmRestore() {
        if (!restoreReport.changes || restoreReport.conflicts || lockRequest || lockToken || releaseRequest) return
        lockRequest = sdk.requestHost("checkpoints.acquire", {id: selectedCheckpoint})
        if (!lockRequest) error = t("无法取得工作目录写锁，请稍后重试", "Could not lock the workspace. Please retry.")
    }
    function releaseLock() {
        if (lockToken) releaseRequest = sdk.requestHost("checkpoints.release", {token: lockToken})
        lockToken = ""; lockRequest = ""
    }
    function showRestoreDiff(path) {
        selected = path; diff = ""; lines = []; viewMode = "restoreDiff"
        diffRequest = call("restoreDiff", {checkpointId: selectedCheckpoint, path: path}, "restoreDiff")
    }
    Component.onCompleted: { targetToken = sdk.session.token || ""; load(false, true) }
    Connections {
        target: root.sdk
        function onConfigSaved(token, value) {
            if (token !== root.configRequest) return
            root.configRequest = ""
            if (!value.ok) root.configError = value.error || root.t("保存失败，请重试", "Could not save. Please retry.")
            autoOpen.checked = Qt.binding(function() { return root.sdk.config.autoOpen !== false })
            checkpoints.checked = Qt.binding(function() { return root.sdk.config.checkpoints === true })
            root.load(false, false)
        }
        function onSessionChanged() {
            if (root.targetToken !== (root.sdk.session.token || "")) {
                root.releaseLock(); root.targetToken = root.sdk.session.token || ""; root.load(false, true)
            }
        }
        function onEvent(topic, data) { if (topic === "review.changed") root.load(false, false) }
        function onHostResponse(id, value) {
            if (id === root.releaseRequest) {
                root.releaseRequest = ""
                if (!value.ok) root.error = value.error || root.t("释放工作目录写锁失败", "Could not release the workspace lock")
                return
            }
            if (id !== root.lockRequest) return
            root.lockRequest = ""
            if (!value.ok) { root.error = value.error || root.t("无法取得工作目录写锁", "Could not lock the workspace"); return }
            root.lockToken = (value.result || {}).token || ""
            if (!root.lockToken) { root.error = root.t("工作目录写锁无效", "Invalid workspace lock"); return }
            root.call("restore", {checkpointId: root.selectedCheckpoint, lockToken: root.lockToken}, "restore")
        }
        function onResponse(token, value) {
            const request = root.requests[token]
            if (!request) return
            const pending = Object.assign({}, root.requests); delete pending[token]; root.requests = pending
            root.loading = Math.max(0, root.loading - 1)
            if (request.epoch !== root.epoch) return
            if (request.kind === "restore") {
                root.releaseLock()
                root.restoreResult = value.ok ? (value.result || {}) : {ok: false, failed: {error: value.error || root.t("恢复失败", "Restore failed")}}
                if (value.ok) root.load(false, false)
                return
            }
            if (!value.ok) { root.error = value.error || root.t("读取失败", "Could not read data"); return }
            const result = value.result || {}
            if (request.kind === "timeline") {
                root.timelineResult = result; root.rebuildTimeline()
            } else if (request.kind === "status") {
                root.latestReport = result; root.error = result.error || ""
                if (!root.selectedCheckpoint) root.report = result
                root.rebuildTimeline()
            } else if (request.kind === "tree") {
                if ((result.checkpointId || "") !== root.selectedCheckpoint) return
                const cache = Object.assign({}, root.cache)
                const previous = result.offset && cache[result.path] ? cache[result.path].entries : []
                const used = Object.keys(cache).filter(path => path !== result.path).reduce((total, path) => total + cache[path].entries.length, 0)
                const incoming = previous.concat(result.entries || [])
                const entries = incoming.slice(0, Math.max(0, 10000 - used))
                root.clipped = root.clipped || entries.length < incoming.length
                cache[result.path] = {entries: entries, hasMore: result.hasMore && entries.length === incoming.length}
                root.cache = cache; root.rebuild()
            } else if ((request.kind === "diff" || request.kind === "restoreDiff") && token === root.diffRequest && root.selected === request.path) {
                root.diff = result.text || root.t("没有文本差异", "No textual diff"); root.lines = root.parse(root.diff); root.truncated = !!result.truncated
            } else if (request.kind === "restorePreview") {
                root.restoreReport = result; root.restoreResult = ({}); root.viewMode = "restore"
            }
        }
    }
    ListModel { id: tree; dynamicRoles: true }
    ColumnLayout {
        anchors.fill: parent; spacing: 0
        RowLayout {
            Layout.fillWidth: true; Layout.preferredHeight: 34 * root.s
            Layout.leftMargin: 7 * root.s; Layout.rightMargin: 5 * root.s; spacing: 3 * root.s
            Git.VsIcon { name: "history"; size: 14 * root.s; color: root.c.muted }
            Text {
                text: "Timeline"
                textFormat: Text.PlainText; color: root.c.ink; font.family: "Segoe UI"; font.pixelSize: 12 * root.s; font.weight: Font.DemiBold; elide: Text.ElideMiddle; Layout.fillWidth: true
            }
            Text {
                visible: !!(root.sdk.session.title || "")
                text: root.sdk.session.title || ""; textFormat: Text.PlainText; color: root.c.muted
                font.family: "Segoe UI"; font.pixelSize: 11 * root.s; elide: Text.ElideRight
                Layout.preferredWidth: Math.min(implicitWidth, 130 * root.s)
            }
            Git.VsButton { objectName: "changeReviewFilter"; uiScale: root.s; iconName: "filter"; hint: root.filterKind === "all" ? root.t("全部检查点", "All checkpoints") : root.filterKind === "agent" ? root.t("Agent 检查点", "Agent checkpoints") : root.t("初始状态", "Initial state"); foreground: root.c.ink; hoverColor: root.c.hover; onClicked: root.cycleFilter() }
            Git.VsButton { objectName: "changeReviewRefresh"; uiScale: root.s; iconName: "refresh"; hint: root.t("刷新", "Refresh"); foreground: root.c.ink; hoverColor: root.c.hover; enabled: !root.loading; onClicked: root.load(true, false) }
            Git.VsButton { objectName: "changeReviewMore"; uiScale: root.s; iconName: "ellipsis"; hint: root.t("检查点设置", "Checkpoint settings"); foreground: root.c.muted; hoverColor: root.c.hover; onClicked: settingsPopup.open() }
        }
        Text {
            visible: !!root.configError || !!root.error; text: root.configError || root.error; textFormat: Text.PlainText
            Layout.fillWidth: true; Layout.leftMargin: 10 * root.s; Layout.rightMargin: 10 * root.s
            wrapMode: Text.Wrap; color: root.c.danger; font.pixelSize: 11 * root.s
        }
        Text {
            visible: root.viewMode === "timeline" && (!!root.timelineResult.notice || !!root.timelineResult.diverged)
            text: root.timelineResult.notice || root.t("当前有未记录修改；新修改将放弃当前点之后的 ", "Unrecorded changes detected. A new turn will discard ") + (root.timelineResult.futureCount || 0) + root.t(" 个未来检查点", " future checkpoints")
            textFormat: Text.PlainText; Layout.fillWidth: true; Layout.leftMargin: 10 * root.s; Layout.rightMargin: 10 * root.s
            wrapMode: Text.Wrap; color: root.c.danger; font.pixelSize: 11 * root.s
        }
        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: root.c.line }
        SplitView {
            Layout.fillWidth: true; Layout.fillHeight: true
            orientation: Qt.Vertical
            handle: Rectangle {
                objectName: "changeReviewSplitHandle"
                implicitHeight: 6 * root.s; color: root.c.line
                Column {
                    anchors.centerIn: parent; spacing: 2 * root.s
                    Rectangle { width: 26 * root.s; height: 1; color: root.c.muted }
                    Rectangle { width: 26 * root.s; height: 1; color: root.c.muted }
                }
                MouseArea { anchors.fill: parent; cursorShape: Qt.SplitVCursor; acceptedButtons: Qt.NoButton }
            }
            Item {
                SplitView.preferredHeight: 210 * root.s
                SplitView.minimumHeight: 105 * root.s
                SplitView.maximumHeight: Math.max(90 * root.s, root.height - 150 * root.s)
            ListView {
                id: timeline; objectName: "changeReviewTimeline"; anchors.fill: parent; visible: true
                model: root.timelineRows; clip: true; boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: Rectangle {
                    id: timelineRow
                    required property var modelData
                    objectName: "changeReviewTimelineRow_" + modelData.checkpointId
                    width: timeline.width; height: 30 * root.s
                    color: root.timelineBg(modelData.rowIndex)
                    MouseArea {
                        id: timelineMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: root.openCheckpoint(modelData.checkpointId)
                    }
                    Rectangle { anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom; width: 3 * root.s; color: root.timelineInk(modelData.rowIndex) }
                    RowLayout {
                        anchors.fill: parent; anchors.leftMargin: 8 * root.s; anchors.rightMargin: 8 * root.s; spacing: 7 * root.s
                        Git.VsIcon { name: modelData.kind === "recovery" ? "history" : "git-commit"; size: 14 * root.s; color: root.timelineInk(modelData.rowIndex) }
                        Text { text: (modelData.current ? root.t("当前 · ", "Current · ") : "") + (modelData.title || root.t("代码检查点", "Code checkpoint")); textFormat: Text.PlainText; color: root.timelineInk(modelData.rowIndex); font.family: "Segoe UI"; font.pixelSize: 12 * root.s; font.weight: modelData.current ? Font.DemiBold : Font.Normal; elide: Text.ElideRight; Layout.fillWidth: true }
                        Text {
                            visible: timeline.width > 300 * root.s
                            text: modelData.active ? root.t("采集中…", "Capturing…") : (modelData.total || 0) + root.t(" 文件", " files") + "  +" + (modelData.added || 0) + " −" + (modelData.removed || 0) + (modelData.limited ? " · !" : "")
                            color: root.timelineInk(modelData.rowIndex); font.family: "Segoe UI"; font.pixelSize: 10 * root.s; elide: Text.ElideRight
                            Layout.preferredWidth: Math.min(implicitWidth, 118 * root.s)
                        }
                        Text { text: root.relativeTime(modelData.ended || modelData.started); color: root.timelineInk(modelData.rowIndex); font.family: "Segoe UI"; font.pixelSize: 10 * root.s; horizontalAlignment: Text.AlignRight; Layout.preferredWidth: 40 * root.s }
                    }
                    Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 1; color: root.timelineInk(modelData.rowIndex); opacity: .45 }
                    ToolTip.visible: timelineMouse.containsMouse; ToolTip.delay: 600
                    ToolTip.text: (modelData.title || "") + "\n" + (modelData.total || 0) + root.t(" 个文件", " files") + "  +" + (modelData.added || 0) + " −" + (modelData.removed || 0) + "\n" + root.fullTime(modelData.ended || modelData.started) + (modelData.limited ? "\n" + root.t("未完整采集，恢复前将检查覆盖范围。", "Partial coverage is checked before restore.") : "") + (modelData.pinned ? "\n" + root.t("已保留", "Pinned") : "")
                }
            }
            Text {
                objectName: "changeReviewEmpty"; visible: root.viewMode === "timeline" && !root.timelineRows.length
                anchors.centerIn: parent; width: parent.width * .78
                text: root.sdk.config.checkpoints === true ? root.t("暂无检查点\n\n完成一轮任务后，历史记录会出现在这里。", "No checkpoints yet\n\nFinish a turn to create the first entry.") : root.t("暂无历史检查点\n\n点击右上角 ⋯ 开启“保存检查点”。", "No checkpoint history\n\nEnable “Save checkpoints” in the ⋯ menu.")
                color: root.c.muted; font.family: "Segoe UI"; font.pixelSize: 12 * root.s; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter; lineHeight: 1.25
            }
            }
            Item {
                SplitView.fillHeight: true
                RowLayout {
                    visible: root.viewMode !== "timeline"
                    anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right
                    height: 32 * root.s; anchors.leftMargin: 5 * root.s; anchors.rightMargin: 5 * root.s; spacing: 3 * root.s
                    Git.VsButton { objectName: "changeReviewBack"; uiScale: root.s; iconName: "arrow-left"; hint: root.t("返回", "Back"); foreground: root.c.ink; hoverColor: root.c.hover; onClicked: root.back() }
                    Text {
                        text: root.viewMode === "files" ? (root.report.title || root.t("历史差异", "Historical diff")) : root.viewMode === "restore" ? root.t("恢复前预览", "Restore preview") : root.selected
                        textFormat: Text.PlainText; color: root.c.ink; font.family: "Segoe UI"; font.pixelSize: 12 * root.s; font.weight: Font.DemiBold; elide: Text.ElideMiddle; Layout.fillWidth: true
                    }
                    Git.VsButton { objectName: "changeReviewRestore"; visible: root.viewMode === "files" && !!root.selectedCheckpoint && !!root.report.restorable; uiScale: root.s; iconName: "history"; hint: root.t("切换到此版本…", "Switch to this version…"); foreground: root.c.ink; hoverColor: root.c.hover; onClicked: root.previewRestore() }
                    Git.VsButton { objectName: "changeReviewCopy"; visible: root.viewMode === "diff" || root.viewMode === "restoreDiff"; enabled: !!root.diff; uiScale: root.s; iconName: "copy"; hint: root.t("复制差异", "Copy diff"); foreground: root.c.ink; hoverColor: root.c.hover; onClicked: root.sdk.copyText(root.diff) }
                }
                Rectangle { visible: root.viewMode !== "timeline"; anchors.top: parent.top; anchors.topMargin: 31 * root.s; width: parent.width; height: 1; color: root.c.line }
                Text {
                    objectName: "changeReviewPreviewEmpty"; visible: root.viewMode === "timeline" && root.timelineRows.length > 0
                    anchors.centerIn: parent; width: parent.width * .8
                    text: root.t("选择上方历史记录，查看该版本的文件变动。", "Select a checkpoint above to preview its file changes.")
                    color: root.c.muted; font.family: "Segoe UI"; font.pixelSize: 12 * root.s; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter
                }
            ListView {
                id: files; objectName: "changeReviewFiles"; anchors.fill: parent; anchors.topMargin: root.viewMode === "timeline" ? 0 : 32 * root.s; visible: root.viewMode === "files"
                model: tree; clip: true; boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: Rectangle {
                    id: row
                    required property string name
                    required property string path
                    required property bool directory
                    required property int depth
                    required property bool expanded
                    required property bool more
                    required property string status
                    required property int added
                    required property int removed
                    required property bool omitted
                    required property bool binary
                    required property int count
                    objectName: "changeReviewRow_" + path
                    width: files.width; height: 24 * root.s
                    color: mouse.containsMouse ? root.c.hover : root.statusBg(row.status)
                    MouseArea {
                        id: mouse; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.RightButton
                        cursorShape: Qt.PointingHandCursor
                        onClicked: event => {
                            if (row.more) { root.loadTree(row.path, true); return }
                            if (row.directory) { if (event.button === Qt.LeftButton) root.toggle(row.path); return }
                            if (event.button === Qt.RightButton) root.contextMenuAt(mouse, event.x, event.y, root.lookup(row.path))
                            else root.show(row.path)
                        }
                    }
                    RowLayout {
                        anchors.fill: parent; anchors.leftMargin: (row.depth * 14 + 3) * root.s; anchors.rightMargin: 8 * root.s; spacing: 6 * root.s
                        Item { Layout.preferredWidth: 16 * root.s; Layout.fillHeight: true
                            Git.VsIcon { visible: row.directory; anchors.centerIn: parent; name: row.expanded ? "chevron-down" : "chevron-right"; size: 16 * root.s; color: root.c.ink }
                        }
                        Git.FileIcon { visible: !row.more; fileName: row.name; directory: row.directory; expanded: row.expanded; dark: root.c.dark; uiScale: root.s }
                        Text { text: row.name; textFormat: Text.PlainText; color: row.more ? root.c.muted : root.statusInk(row.status); font.strikeout: row.status === "D"; font.family: "Segoe UI"; font.pixelSize: 13 * root.s; elide: Text.ElideRight; Layout.fillWidth: true }
                        Text { text: row.directory ? row.count : row.omitted ? "!" : row.binary ? "" : row.added >= 0 ? "+" + row.added : ""; color: row.directory ? root.metaInk : root.addInk; font.family: "Segoe UI"; font.pixelSize: 11 * root.s }
                        Text { text: !row.directory && !row.omitted && !row.binary && row.removed >= 0 ? "−" + row.removed : ""; color: root.removeInk; font.family: "Segoe UI"; font.pixelSize: 11 * root.s }
                        Text { text: row.status; color: root.statusInk(row.status); font.pixelSize: 12 * root.s; Layout.preferredWidth: row.status ? 18 * root.s : 0; horizontalAlignment: Text.AlignHCenter }
                    }
                    ToolTip.visible: mouse.containsMouse; ToolTip.delay: 700
                    ToolTip.text: row.path + (row.omitted ? "\n" + root.t("文件未完整采集", "Incomplete file") : row.binary ? "\n" + root.t("二进制文件", "Binary file") : "")
                }
            }
            Text { visible: root.viewMode === "files" && !files.count; anchors.top: parent.top; anchors.topMargin: 36 * root.s; anchors.left: parent.left; anchors.leftMargin: 16 * root.s; text: root.t("暂无变更", "No changes"); color: root.c.muted; font.family: "Segoe UI"; font.pixelSize: 13 * root.s }
            ListView {
                id: diffView; objectName: "changeReviewDiff"; anchors.fill: parent; anchors.topMargin: 32 * root.s; visible: root.viewMode === "diff" || root.viewMode === "restoreDiff"
                clip: true; model: root.lines; boundsBehavior: Flickable.StopAtBounds
                contentWidth: Math.max(width, Math.min(2000, root.diff.split("\n").reduce((maximum, line) => Math.max(maximum, line.length), 0)) * 8 * root.s + 115 * root.s)
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: Rectangle {
                    required property var modelData
                    width: diffView.contentWidth; height: 21 * root.s
                    color: modelData.kind === "add" ? root.addBg : modelData.kind === "remove" ? root.removeBg : "transparent"
                    Row {
                        height: parent.height; spacing: 8 * root.s
                        Text { width: 42 * root.s; text: modelData.oldNumber; horizontalAlignment: Text.AlignRight; color: root.metaInk; font.family: "Consolas"; font.pixelSize: 11 * root.s }
                        Text { width: 42 * root.s; text: modelData.newNumber; horizontalAlignment: Text.AlignRight; color: root.metaInk; font.family: "Consolas"; font.pixelSize: 11 * root.s }
                        Text { text: modelData.text; textFormat: Text.PlainText; color: modelData.kind === "add" ? root.addInk : modelData.kind === "remove" ? root.removeInk : modelData.kind === "meta" ? root.metaInk : root.c.ink; font.family: "Consolas"; font.pixelSize: 12 * root.s }
                    }
                }
                MouseArea { anchors.fill: parent; acceptedButtons: Qt.RightButton; onClicked: event => root.contextMenuAt(diffView, event.x, event.y, root.diffEntry) }
            }
            ColumnLayout {
                anchors.fill: parent; anchors.topMargin: 32 * root.s; visible: root.viewMode === "restore"; spacing: 0
                Rectangle {
                    Layout.fillWidth: true; implicitHeight: summaryColumn.implicitHeight + 16 * root.s; color: root.restoreReport.conflicts ? Qt.rgba(.9,.2,.2,.08) : root.c.hover
                    ColumnLayout {
                        id: summaryColumn; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 8 * root.s; spacing: 4 * root.s
                        Text { text: root.switchDirection() + " · " + (root.restoreReport.title || "") + "\n" + root.t("切换工作区到此版本并更新当前位置。聊天、Git 暂存区、分支和提交历史不会改变。", "Switch files to this version and move the current pointer. Chat, Git index, branches and commits are unchanged."); color: root.c.ink; font.pixelSize: 12 * root.s; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Text { visible: !!root.restoreReport.overwrites; text: root.t("将覆盖 ", "Overwrites: ") + (root.restoreReport.overwrites || 0) + root.t(" 个文件的版本差异；当前状态会保存为内部恢复安全记录。", " files with version differences. The current state is saved as an internal recovery record."); color: root.c.ink; font.pixelSize: 11 * root.s; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Text { text: (root.restoreReport.changes || 0) + root.t(" 项待恢复 · ", " changes · ") + (root.restoreReport.conflicts || 0) + root.t(" 项冲突", " conflicts") + (root.restoreReport.partial ? " · " + root.t("部分覆盖", "partial coverage") : ""); color: root.restoreReport.conflicts ? root.c.danger : root.c.muted; font.pixelSize: 11 * root.s }
                        Text { visible: !!root.restoreResult.ok; text: root.t("已切换到此版本，当前指针已更新；恢复安全记录已保存。", "Switched to this version. Current pointer updated and recovery record saved."); color: root.c.accent; font.pixelSize: 11 * root.s; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Text { visible: root.restoreResult.ok === false; text: ((root.restoreResult.failed || {}).error || root.t("恢复失败", "Restore failed")) + "\n" + root.t("已完成 ", "Completed: ") + (root.restoreResult.completed || []).length + root.t(" 项；未处理 ", "Pending: ") + (root.restoreResult.pending || []).length + root.t(" 项", ""); color: root.c.danger; font.pixelSize: 11 * root.s; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }
                ListView {
                    id: restoreFiles; objectName: "changeReviewRestoreFiles"; Layout.fillWidth: true; Layout.fillHeight: true
                    model: root.restoreReport.entries || []; clip: true
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    delegate: Rectangle {
                        required property var modelData
                        objectName: "changeReviewRestoreRow_" + modelData.path
                        width: restoreFiles.width; height: 26 * root.s; color: restoreMouse.containsMouse ? root.c.hover : "transparent"
                        MouseArea { id: restoreMouse; anchors.fill: parent; hoverEnabled: true; onClicked: root.showRestoreDiff(modelData.path) }
                        RowLayout {
                            anchors.fill: parent; anchors.leftMargin: 8 * root.s; anchors.rightMargin: 8 * root.s; spacing: 6 * root.s
                            Text { text: modelData.action === "delete" ? "−" : modelData.action === "create" ? "+" : modelData.action === "conflict" || modelData.action === "unavailable" ? "!" : "↔"; color: root.actionInk(modelData.action); font.pixelSize: 13 * root.s }
                            Text { text: modelData.path; color: root.actionInk(modelData.action); font.family: "Segoe UI"; font.pixelSize: 12 * root.s; elide: Text.ElideMiddle; Layout.fillWidth: true }
                            Text { text: modelData.action === "restore" ? root.t("替换", "Restore") : modelData.action === "create" ? root.t("重建", "Recreate") : modelData.action === "delete" ? root.t("删除", "Delete") : modelData.action === "none" ? root.t("无变化", "Unchanged") : modelData.action === "conflict" ? root.t("冲突", "Conflict") : root.t("未覆盖", "Unavailable"); color: root.actionInk(modelData.action); font.pixelSize: 11 * root.s }
                        }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true; Layout.margins: 8 * root.s; spacing: 8 * root.s
                    Item { Layout.fillWidth: true }
                    Button { objectName: "changeReviewRestoreCancel"; text: root.t("返回", "Back"); onClicked: { root.releaseLock(); root.back() } }
                    Button {
                        objectName: "changeReviewRestoreConfirm"; text: root.lockRequest || root.lockToken || root.releaseRequest ? root.t("正在恢复…", "Restoring…") : root.t("确认恢复", "Restore")
                        enabled: !!root.restoreReport.changes && !root.restoreReport.conflicts && !root.lockRequest && !root.lockToken && !root.releaseRequest && root.restoreResult.ok !== true
                        onClicked: root.confirmRestore()
                    }
                }
            }
        }
        }
    }
    Popup {
        id: settingsPopup
        x: Math.max(4 * root.s, root.width - width - 6 * root.s); y: 32 * root.s
        width: 226 * root.s; height: 150 * root.s; padding: 8 * root.s
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: root.c.surface; border.color: root.c.line; border.width: 1; radius: 6 * root.s }
        ColumnLayout {
            anchors.fill: parent; spacing: 5 * root.s
            Text { text: root.t("Timeline 设置", "Timeline settings"); color: root.c.ink; font.family: "Segoe UI"; font.pixelSize: 12 * root.s; font.weight: Font.DemiBold; bottomPadding: 2 * root.s }
            Rectangle {
                id: checkpoints; objectName: "changeReviewCheckpoints"
                property bool checked: root.sdk.config.checkpoints === true
                Layout.fillWidth: true; height: 30 * root.s; radius: 4 * root.s; color: checkpointMouse.containsMouse ? root.c.hover : "transparent"
                MouseArea {
                    id: checkpointMouse; anchors.fill: parent; hoverEnabled: true; enabled: root.sdk.active && !root.configRequest
                    onClicked: { checkpoints.checked = !checkpoints.checked; root.saveSetting("checkpoints", checkpoints.checked) }
                }
                RowLayout {
                    anchors.fill: parent; anchors.leftMargin: 5 * root.s; anchors.rightMargin: 5 * root.s; spacing: 8 * root.s
                    Rectangle {
                        width: 13 * root.s; height: 13 * root.s; radius: 3 * root.s
                        color: checkpoints.checked ? root.c.accent : "transparent"; border.color: checkpoints.checked ? root.c.accent : root.c.muted; border.width: 1
                        Git.VsIcon { anchors.centerIn: parent; name: "check"; size: 10 * root.s; visible: checkpoints.checked; color: root.c.surface }
                    }
                    Text { text: root.t("保存检查点", "Save checkpoints"); color: root.c.ink; font.family: "Segoe UI"; font.pixelSize: 12 * root.s; Layout.fillWidth: true }
                }
            }
            Rectangle {
                id: autoOpen; objectName: "changeReviewPageAutoOpen"
                property bool checked: root.sdk.config.autoOpen !== false
                Layout.fillWidth: true; height: 30 * root.s; radius: 4 * root.s; color: autoOpenMouse.containsMouse ? root.c.hover : "transparent"
                MouseArea {
                    id: autoOpenMouse; anchors.fill: parent; hoverEnabled: true; enabled: root.sdk.active && !root.configRequest
                    onClicked: { autoOpen.checked = !autoOpen.checked; root.saveSetting("autoOpen", autoOpen.checked) }
                }
                RowLayout {
                    anchors.fill: parent; anchors.leftMargin: 5 * root.s; anchors.rightMargin: 5 * root.s; spacing: 8 * root.s
                    Rectangle {
                        width: 13 * root.s; height: 13 * root.s; radius: 3 * root.s
                        color: autoOpen.checked ? root.c.accent : "transparent"; border.color: autoOpen.checked ? root.c.accent : root.c.muted; border.width: 1
                        Git.VsIcon { anchors.centerIn: parent; name: "check"; size: 10 * root.s; visible: autoOpen.checked; color: root.c.surface }
                    }
                    Text { text: root.t("每轮后自动展开", "Open after each turn"); color: root.c.ink; font.family: "Segoe UI"; font.pixelSize: 12 * root.s; Layout.fillWidth: true }
                }
            }
            Text { text: root.t("本机保存 · 默认 20 份 / 512 MiB\n重启后仍可查看历史差异", "Stored locally · 20 entries / 512 MiB\nHistory survives application restarts"); color: root.c.muted; font.family: "Segoe UI"; font.pixelSize: 10 * root.s; wrapMode: Text.Wrap; Layout.fillWidth: true; leftPadding: 5 * root.s }
        }
    }
    Git.FileContextMenu {
        id: fileMenu; parent: root; sdk: root.sdk; entry: root.contextEntry; readOnly: true
        onOperation: (method, args) => { if (method === "diff") root.show(args.path); else root.call(method, Object.assign({checkpointId: root.selectedCheckpoint}, args)) }
    }
}
