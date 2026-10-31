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
    property var report: ({total: 0, empty: true})
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
    readonly property string help: error || ((report.limited || clipped) ? "部分文件超过采集限制，预览不完整。" : truncated ? "差异预览已截断。" : "仅本轮变更，可能包含同目录的并发编辑。\n只保留最近一轮，重启后清除。")
    color: c.surface

    function call(method, args, kind) {
        const token = sdk.call(method, args || {})
        if (!token) { error = "插件暂时繁忙，请稍后重试"; return "" }
        const pending = Object.assign({}, requests)
        pending[token] = {kind: kind || method, path: (args || {}).path || "", epoch: epoch}
        requests = pending; loading++
        return token
    }
    function load(refresh) {
        fileMenu.close()
        epoch++; requests = ({}); loading = 0; cache = ({}); expanded = ({})
        selected = ""; diff = ""; lines = []; diffRequest = ""; error = ""; clipped = false; tree.clear()
        call(refresh ? "refresh" : "status", {}, "status")
    }
    function loadTree(path, more) {
        if (Object.values(requests).some(item => item.kind === "tree" && item.path === path)) return
        call("tree", {path: path, offset: more && cache[path] ? cache[path].entries.length : 0, loopId: report.loopId}, "tree")
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
            if (group.hasMore && tree.count < 4000) tree.append({name: "加载更多", path: path, directory: false,
                depth: depth, expanded: false, more: true, status: "", added: -1, removed: -1, omitted: false, binary: false, count: 0})
        }
        append("", 0)
    }
    function toggle(path) {
        const next = Object.assign({}, expanded); next[path] = !next[path]; expanded = next
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
        diffRequest = call("diff", {path: path, loopId: report.loopId}, "diff")
    }
    function back() { selected = ""; diff = ""; lines = []; diffRequest = ""; error = ""; truncated = false }
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
            else if (hunk && textLine.startsWith(" ")) { oldNumber = String(oldLine++); newNumber = String(newLine++); kind = "context" }
            result.push({text: textLine, oldNumber: oldNumber, newNumber: newNumber, kind: kind})
        }
        return result
    }
    Component.onCompleted: { targetToken = sdk.session.token || ""; load(false) }
    Connections {
        target: root.sdk
        function onSessionChanged() {
            if (root.targetToken !== (root.sdk.session.token || "")) { root.targetToken = root.sdk.session.token || ""; root.load(false) }
        }
        function onEvent(topic, data) { if (topic === "review.changed") root.load(false) }
        function onResponse(token, value) {
            const request = root.requests[token]
            if (!request) return
            const pending = Object.assign({}, root.requests); delete pending[token]; root.requests = pending
            root.loading = Math.max(0, root.loading - 1)
            if (request.epoch !== root.epoch) return
            if (!value.ok) { root.error = value.error || "读取失败"; return }
            const result = value.result || {}
            if (request.kind === "status") {
                root.report = result; root.error = result.error || ""
                if (result.total && !result.active) root.loadTree("", false)
            } else if (request.kind === "tree") {
                if (result.loopId !== root.report.loopId) return
                const cache = Object.assign({}, root.cache)
                const previous = result.offset && cache[result.path] ? cache[result.path].entries : []
                const used = Object.keys(cache).filter(path => path !== result.path).reduce((total, path) => total + cache[path].entries.length, 0)
                const incoming = previous.concat(result.entries || [])
                const entries = incoming.slice(0, Math.max(0, 10000 - used))
                root.clipped = root.clipped || entries.length < incoming.length
                cache[result.path] = {entries: entries, hasMore: result.hasMore && entries.length === incoming.length}
                root.cache = cache; root.rebuild()
            } else if (request.kind === "diff" && token === root.diffRequest && root.selected === request.path) {
                root.diff = result.text || "没有文本差异"; root.lines = root.parse(root.diff); root.truncated = !!result.truncated
            }
        }
    }
    ListModel { id: tree; dynamicRoles: true }
    ColumnLayout {
        anchors.fill: parent; spacing: 0
        RowLayout {
            Layout.fillWidth: true; Layout.preferredHeight: 30 * root.s
            Layout.leftMargin: 6 * root.s; Layout.rightMargin: 6 * root.s; spacing: 3 * root.s
            Git.VsButton { objectName: "changeReviewBack"; visible: !!root.selected; uiScale: root.s; iconName: "arrow-left"; hint: "返回更改"; foreground: root.c.ink; hoverColor: root.c.hover; onClicked: root.back() }
            Text { visible: !!root.selected; text: root.selected; textFormat: Text.PlainText; color: root.c.ink; font.family: "Segoe UI"; font.pixelSize: 13 * root.s; elide: Text.ElideMiddle; Layout.fillWidth: true }
            Item { visible: !root.selected; Layout.fillWidth: true }
            Git.VsButton { objectName: "changeReviewCopy"; visible: !!root.selected; enabled: !!root.diff; uiScale: root.s; iconName: "copy"; hint: "复制差异"; foreground: root.c.ink; hoverColor: root.c.hover; onClicked: root.sdk.copyText(root.diff) }
            Git.VsButton { objectName: "changeReviewHelp"; visible: root.report.total > 0 || !!root.error || root.report.limited || root.clipped; uiScale: root.s; iconName: "question"; hint: root.help; foreground: root.c.muted; hoverColor: root.c.hover; onClicked: ToolTip.show(root.help, 5000) }
            Git.VsButton { objectName: "changeReviewRefresh"; visible: !root.selected; uiScale: root.s; iconName: "refresh"; hint: "刷新"; foreground: root.c.ink; hoverColor: root.c.hover; enabled: !root.loading && !root.report.active; onClicked: root.load(true) }
        }
        Item {
            Layout.fillWidth: true; Layout.fillHeight: true
            ListView {
                id: files; objectName: "changeReviewFiles"; anchors.fill: parent; visible: !root.selected
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
                    width: files.width; height: 22 * root.s
                    color: mouse.containsMouse ? root.c.hover : "transparent"
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
                        Text { text: row.name; textFormat: Text.PlainText; color: row.more ? root.c.muted : row.status === "D" ? root.c.danger : root.c.ink; font.strikeout: row.status === "D"; font.family: "Segoe UI"; font.pixelSize: 13 * root.s; elide: Text.ElideRight; Layout.fillWidth: true }
                        Text { text: row.directory ? row.count : row.omitted ? "!" : row.binary ? "" : row.added >= 0 ? "+" + row.added + "  −" + row.removed : ""; color: root.c.muted; font.family: "Segoe UI"; font.pixelSize: 11 * root.s }
                        Text { text: row.status; color: row.status === "D" ? root.c.danger : root.c.accent; font.pixelSize: 12 * root.s; Layout.preferredWidth: row.status ? 18 * root.s : 0; horizontalAlignment: Text.AlignHCenter }
                    }
                    ToolTip.visible: mouse.containsMouse; ToolTip.delay: 700
                    ToolTip.text: row.path + (row.omitted ? "\n文件未完整采集" : row.binary ? "\n二进制文件" : "")
                }
            }
            Text { objectName: "changeReviewEmpty"; visible: !root.selected && !files.count; anchors.top: parent.top; anchors.left: parent.left; anchors.margins: 16 * root.s; text: root.error ? "无法读取变更" : "暂无变更"; color: root.c.muted; font.family: "Segoe UI"; font.pixelSize: 13 * root.s }
            ListView {
                id: diffView; objectName: "changeReviewDiff"; anchors.fill: parent; visible: !!root.selected
                clip: true; model: root.lines; boundsBehavior: Flickable.StopAtBounds
                contentWidth: Math.max(width, Math.min(2000, root.diff.split("\n").reduce((maximum, line) => Math.max(maximum, line.length), 0)) * 8 * root.s + 115 * root.s)
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: Rectangle {
                    required property var modelData
                    width: diffView.contentWidth; height: 21 * root.s
                    color: modelData.kind === "add" ? Qt.rgba(.2,.65,.3,.12) : modelData.kind === "remove" ? Qt.rgba(.9,.2,.2,.12) : "transparent"
                    Row {
                        height: parent.height; spacing: 8 * root.s
                        Text { width: 42 * root.s; text: modelData.oldNumber; horizontalAlignment: Text.AlignRight; color: root.c.muted; font.family: "Consolas"; font.pixelSize: 11 * root.s }
                        Text { width: 42 * root.s; text: modelData.newNumber; horizontalAlignment: Text.AlignRight; color: root.c.muted; font.family: "Consolas"; font.pixelSize: 11 * root.s }
                        Text { text: modelData.text; textFormat: Text.PlainText; color: modelData.kind === "meta" ? root.c.muted : root.c.ink; font.family: "Consolas"; font.pixelSize: 12 * root.s }
                    }
                }
                MouseArea { anchors.fill: parent; acceptedButtons: Qt.RightButton; onClicked: event => root.contextMenuAt(diffView, event.x, event.y, root.diffEntry) }
            }
        }
    }
    Git.FileContextMenu {
        id: fileMenu; parent: root; sdk: root.sdk; entry: root.contextEntry; readOnly: true
        onOperation: (method, args) => { if (method === "diff") root.show(args.path); else root.call(method, args) }
    }
}
