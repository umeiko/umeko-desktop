import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../../app/qml" as Umeko

FocusScope {
    id: root
    objectName: "systemPromptWidget"
    required property var sdk
    clip: true
    property bool initialized: false
    property var tree: []
    property var drafts: ({})
    property var collapsed: ({})
    property var pending: ({})
    property string selectedId: ""
    property string restoreId: ""
    property string notice: ""
    property int originalCharacters: 0
    property int effectiveCharacters: 0
    property real treeHeight: 240 * sdk.scale
    readonly property bool working: Object.keys(pending).length > 0
    readonly property bool sessionBusy: !!(sdk.session && sdk.session.busy)
    readonly property bool available: !!sdk.active && !working && !sessionBusy
    readonly property var selected: findNode(tree, selectedId)
    readonly property string draftText: selected ? Object.prototype.hasOwnProperty.call(drafts, selectedId) ? drafts[selectedId] : currentText(selected) : ""
    readonly property bool dirty: !!selected && draftText !== currentText(selected)
    readonly property var entries: flatten(tree, 0)
    readonly property bool dark: !!sdk.colors.dark
    // Amber stays legible on both the dark and the light surfaces.
    readonly property color changedColor: dark ? "#d7b65b" : "#946200"
    readonly property color changedBg: dark ? "#1fd7b65b" : "#1fe0a526"
    readonly property var breadcrumb: pathTo(tree, selectedId, [])
    function t(zh, en) { return sdk.language.indexOf("zh") === 0 ? zh : en }
    function count(value) { return Number(value || 0).toLocaleString(Qt.locale("en_US"), "f", 0) }
    // Known runtime names are translated here; Skill, Widget and file names are shown as they are.
    readonly property var labels: ({
        "group:core": ["Pi 内核", "Pi core"], "group:skills": ["Skills", "Skills"],
        "group:umeko": ["Umeko Desktop", "Umeko Desktop"], "group:widgets": ["Widgets", "Widgets"],
        "group:workspace": ["项目指令文件", "Project instruction files"], "group:extensions": ["Pi 扩展", "Pi extensions"],
        "section:preamble": ["角色说明", "Role"], "section:tools": ["工具说明", "Tools"],
        "section:rules": ["工作规则", "Working rules"], "section:docs": ["Pi 文档指引", "Pi documentation"],
        "section:cwd": ["当前工作目录", "Working directory"], "section:addendum": ["附加说明", "Addendum"],
        "section:project_context": ["工作区指令", "Workspace instructions"], "section:skills": ["技能目录", "Skill catalog"],
        "skill:catalog": ["技能简介", "Skill summary"],
        "umeko:desktop-pi": ["Pi 操作说明", "Pi usage"], "umeko:desktop-control": ["桌面能力说明", "Desktop capabilities"],
        "umeko:language": ["回复语言", "Reply language"], "umeko:instructions": ["自定义指令", "Custom instructions"]
    })
    function label(node) {
        const known = node && node.labelKey ? labels[node.labelKey] : undefined
        return known ? t(known[0], known[1]) : node ? node.name : ""
    }
    function pathTo(nodes, identifier, trail) {
        for (const node of nodes) {
            const next = trail.concat([label(node)])
            if (node.id === identifier) return next
            if (node.children) {
                const match = pathTo(node.children, identifier, next)
                if (match.length) return match
            }
        }
        return []
    }
    function currentText(node) { return node.currentText === undefined ? node.effectiveText || "" : node.currentText }
    function findNode(nodes, identifier) {
        for (const node of nodes) {
            if (node.id === identifier) return node
            if (node.children) {
                const match = findNode(node.children, identifier)
                if (match) return match
            }
        }
        return null
    }
    function firstLeaf(nodes) {
        for (const node of nodes) {
            if (!node.children) return node.id
            const leaf = firstLeaf(node.children)
            if (leaf) return leaf
        }
        return ""
    }
    function changed(node) {
        if (node.modified) return true
        if (node.children) return node.children.some(child => changed(child))
        if ((node.effectiveText || "") !== (node.originalText || "")) return true
        return Object.prototype.hasOwnProperty.call(drafts, node.id) && drafts[node.id] !== currentText(node)
    }
    function flatten(nodes, depth) {
        let rows = []
        for (const node of nodes) {
            const folder = !!node.children
            const expanded = !collapsed[node.id]
            rows.push(Object.assign({}, node, {
                folder: folder, depth: depth, expanded: expanded, changed: changed(node), label: label(node),
                empty: folder && node.children.length === 0,
                checkState: node.checkState === undefined ? node.enabled ? 2 : 0 : node.checkState
            }))
            if (folder && expanded && node.children.length === 0)
                rows.push({id: node.id + ":empty", hint: true, depth: depth + 1, label: node.labelKey === "group:widgets"
                    ? t("当前没有 Widget 写入系统提示词，Widget 说明由模型在需要时通过工具读取", "No Widget adds text to the system prompt; the model reads Widget docs through tools when needed")
                    : t("此来源当前没有内容", "Nothing from this source")})
            else if (folder && expanded) rows = rows.concat(flatten(node.children, depth + 1))
        }
        return rows
    }
    function fold(identifier) {
        let next = Object.assign({}, collapsed)
        next[identifier] = !next[identifier]
        collapsed = next
    }
    function edit(value) {
        if (!selected) return
        let next = Object.assign({}, drafts)
        next[selectedId] = value
        drafts = next
    }
    function request(operation, args) {
        if (!sdk.active || working || (operation !== "systemPrompt.inspect" && sessionBusy)) return false
        const operations = sdk.hostCapabilities && sdk.hostCapabilities.operations
        if (operations && !operations[operation]) {
            notice = t("此操作需要更新版本的 Umeko。", "This operation needs a newer Umeko version.")
            return false
        }
        const identifier = sdk.requestHost(operation, args || {})
        if (!identifier) {
            notice = t("暂时无法读取，请稍后重试。", "Temporarily unavailable. Retry shortly.")
            return false
        }
        let next = Object.assign({}, pending)
        next[identifier] = {operation: operation, args: args || {}, draft: args && args.id ? drafts[args.id] : undefined}
        pending = next
        notice = ""
        return true
    }
    function reload() { request("systemPrompt.inspect", {}) }
    function initialize() {
        if (sdk.active && !initialized) { initialized = true; reload() }
    }
    function applySnapshot(value) {
        tree = value.tree || []
        originalCharacters = value.originalCharacters || 0
        effectiveCharacters = value.effectiveCharacters || 0
        const node = findNode(tree, selectedId)
        if (!node || node.children) selectedId = firstLeaf(tree)
    }
    function save() {
        if (available && dirty) request("systemPrompt.save", {id: selectedId, text: draftText})
    }
    function showRestore() { if (available && selected) restoreId = selectedId }
    function restore() {
        if (available && restoreId && request("systemPrompt.restore", {id: restoreId})) restoreId = ""
    }
    function complete(identifier, value) {
        const entry = pending[identifier]
        if (!entry) return
        let next = Object.assign({}, pending)
        delete next[identifier]
        pending = next
        if (!value || value.ok === false) {
            notice = t("操作失败。你的草稿仍保留，请刷新后重试。", "The operation failed. Your drafts are kept; refresh and retry.")
            return
        }
        if (value.tree) applySnapshot(value)
        if (entry.operation === "systemPrompt.save" || entry.operation === "systemPrompt.restore") {
            // Clear only the draft covered by this completed operation.
            // A refresh or an unrelated checkbox update never discards drafts.
            const id = entry.args.id
            if (drafts[id] === entry.draft) {
                let updated = Object.assign({}, drafts)
                delete updated[id]
                drafts = updated
            }
        }
        if (!value.tree && entry.operation !== "systemPrompt.inspect") reload()
    }
    Component.onCompleted: initialize()
    Keys.onEscapePressed: if (restoreId) restoreId = ""
    Rectangle { anchors.fill: parent; color: root.sdk.colors.surface; z: -1 }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12 * root.sdk.scale
        spacing: 8 * root.sdk.scale
        enabled: !root.restoreId
        RowLayout {
            Layout.fillWidth: true
            Image { source: "../assets/system-prompt.svg"; Layout.preferredWidth: 21 * root.sdk.scale; Layout.preferredHeight: 21 * root.sdk.scale }
            Text {
                Layout.fillWidth: true
                text: root.t("系统提示词", "System prompt")
                color: root.sdk.colors.ink
                elide: Text.ElideRight
                font.family: Umeko.Theme.fontFamily
                font.pixelSize: Umeko.Theme.font(16)
                font.bold: true
            }
            PromptButton { objectName: "systemPromptRefresh"; sdk: root.sdk; iconName: "refresh"; enabled: !root.working; onClicked: root.reload(); Accessible.name: root.t("刷新", "Refresh") }
        }
        Text {
            Layout.fillWidth: true
            objectName: "systemPromptTotals"
            text: root.t("当前注入 " + root.count(root.effectiveCharacters) + " 字 · 原文 " + root.count(root.originalCharacters) + " 字",
                         "Injected " + root.count(root.effectiveCharacters) + " chars · Original " + root.count(root.originalCharacters) + " chars")
            color: root.sdk.colors.muted
            font.family: Umeko.Theme.fontFamily
            font.pixelSize: Umeko.Theme.font(10)
        }
        Text {
            visible: root.sessionBusy || !!root.notice
            Layout.fillWidth: true
            text: root.notice || root.t("会话运行中，结束后可修改。", "The session is busy. Changes are available when it finishes.")
            wrapMode: Text.Wrap
            color: root.notice ? root.sdk.colors.danger : root.sdk.colors.muted
            font.family: Umeko.Theme.fontFamily
            font.pixelSize: Umeko.Theme.font(10)
        }
        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Vertical
            handle: Item {
                implicitHeight: 12 * (root.sdk ? root.sdk.scale : 1)
                Rectangle { anchors.centerIn: parent; width: 42 * (root.sdk ? root.sdk.scale : 1); height: 3 * (root.sdk ? root.sdk.scale : 1); radius: 2; color: !root.sdk ? "transparent" : SplitHandle.hovered || SplitHandle.pressed ? root.sdk.colors.accent : root.sdk.colors.line }
            }
            Item {
                objectName: "systemPromptTreePane"
                SplitView.preferredHeight: root.treeHeight
                SplitView.minimumHeight: 70 * root.sdk.scale
                ColumnLayout {
                    anchors.fill: parent
                    spacing: 5 * root.sdk.scale
                    RowLayout {
                        Layout.fillWidth: true
                        Text { Layout.fillWidth: true; text: root.t("来源", "Sources"); color: root.sdk.colors.muted; font.family: Umeko.Theme.fontFamily; font.pixelSize: Umeko.Theme.font(10); font.weight: Font.DemiBold }
                        Rectangle { width: 8 * root.sdk.scale; height: width; radius: 2 * root.sdk.scale; color: root.changedColor }
                        Text { text: root.t("与原文不同", "Differs from original"); color: root.sdk.colors.muted; font.family: Umeko.Theme.fontFamily; font.pixelSize: Umeko.Theme.font(10) }
                    }
                    PromptTree {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        sdk: root.sdk
                        entries: root.entries
                        selectedId: root.selectedId
                        available: root.available
                        changedColor: root.changedColor
                        changedBg: root.changedBg
                        dark: root.dark
                        onSelectedLeaf: identifier => root.selectedId = identifier
                        onFold: identifier => root.fold(identifier)
                        onToggled: (identifier, value) => root.request("systemPrompt.toggle", {id: identifier, enabled: value})
                    }
                    Text {
                        visible: !root.entries.length
                        text: root.working ? root.t("正在读取…", "Reading…") : root.t("暂无提示词来源", "No prompt sources")
                        color: root.sdk.colors.muted
                        font.family: Umeko.Theme.fontFamily
                        font.pixelSize: Umeko.Theme.font(11)
                    }
                }
            }
            PromptEditor {
                SplitView.fillHeight: true
                SplitView.minimumHeight: 190 * root.sdk.scale
                sdk: root.sdk
                selected: root.selected
                title: root.label(root.selected)
                breadcrumb: root.breadcrumb.slice(0, -1).join("  ›  ")
                changedColor: root.changedColor
                draft: root.draftText
                dirty: root.dirty
                available: root.available
                onEdited: value => root.edit(value)
                onSave: root.save()
                onRestore: root.showRestore()
            }
        }
    }
    RestoreConfirmation {
        anchors.fill: parent
        visible: !!root.restoreId
        sdk: root.sdk
        segmentName: root.label(root.findNode(root.tree, root.restoreId))
        available: root.available
        onCancelled: root.restoreId = ""
        onConfirmed: root.restore()
    }
    Connections {
        target: root.sdk
        ignoreUnknownSignals: true
        function onActiveChanged() { if (root.initialized && root.sdk.active) root.reload(); else root.initialize() }
        function onSessionChanged() { if (root.initialized && root.sdk.active && !root.working) root.reload() }
        function onHostResponse(identifier, value) { root.complete(identifier, value) }
    }
}
