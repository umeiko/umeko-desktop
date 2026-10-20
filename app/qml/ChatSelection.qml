import QtQuick
import "markdown.js" as Markdown

Item {
    id: root
    objectName: "chatSelection"
    property var view
    property var editors: []
    property var anchor: null
    property var cursor: null
    property bool dragging: false
    property double lastScrollTime: 0
    property point pointer: Qt.point(0, 0)
    readonly property bool hasSelection: anchor !== null && cursor !== null && compare(anchor, cursor) !== 0
    property var expandedDetails: ({})
    function compare(a, b) { return a.row - b.row || a.block - b.block || a.offset - b.offset }
    function attach(editor) { editors.push(editor); refreshSoon() }
    function detach(editor) { editors = editors.filter(item => item !== editor) }
    function refreshSoon() { refreshTimer.restart() }
    function hideDetails(row, first, count) {
        for (let i = 0; i < count; i++) expandedDetails[row + ":" + (first + i)] = false
        refreshSoon()
    }
    function clear() {
        dragging = false; anchor = null; cursor = null; expandedDetails = ({})
        for (const editor of editors) editor.deselect()
    }
    function refresh() {
        const start = hasSelection && compare(anchor, cursor) < 0 ? anchor : cursor
        const end = hasSelection && compare(anchor, cursor) < 0 ? cursor : anchor
        for (const editor of editors) {
            const key = editor.messageIndex + ":" + editor.blockIndex
            if (editor.conditionalSelection) expandedDetails[key] = editor.visible
            if (!hasSelection) { if (editor.selectionStart !== editor.selectionEnd) editor.deselect(); continue }
            const first = {row:editor.messageIndex, block:editor.blockIndex, offset:0}
            const last = {row:first.row, block:first.block, offset:editor.length}
            if (compare(last, start) <= 0 || compare(first, end) >= 0) { if (editor.selectionStart !== editor.selectionEnd) editor.deselect() }
            else {
                const from = Math.max(0, compare(first, start) < 0 ? start.offset : 0), to = Math.min(editor.length, compare(last, end) > 0 ? end.offset : editor.length)
                if (editor.selectionStart !== from || editor.selectionEnd !== to) editor.select(from, to)
            }
        }
    }
    function pick(x, y, nearest) {
        let best = null, distance = Infinity
        for (const editor of editors) {
            if (!editor.visible || editor.messageIndex < 0 || editor.height <= 0) continue
            const point = editor.mapToItem(root, 0, 0)
            if (point.y + editor.height < 0 || point.y > height) continue
            const inside = x >= point.x && x <= point.x + editor.width && y >= point.y && y <= point.y + editor.height
            if (!nearest && !inside) continue
            const gap = Math.max(point.y - y, 0, y - point.y - editor.height)
            if (gap < distance) { best = editor; distance = gap }
        }
        return best
    }
    function position(editor, x, y) {
        const p = root.mapToItem(editor, x, y)
        return {row:editor.messageIndex, block:editor.blockIndex, offset:editor.positionAt(Math.max(0, Math.min(editor.width, p.x)), Math.max(0, Math.min(editor.height - 1, p.y)))}
    }
    function extend() {
        const editor = pick(pointer.x, Math.max(0, Math.min(height - 1, pointer.y)), true)
        if (editor) { cursor = position(editor, pointer.x, Math.max(0, Math.min(height - 1, pointer.y))); refresh() }
    }
    function plain(text, markdown) {
        renderer.textFormat = markdown ? TextEdit.MarkdownText : TextEdit.PlainText
        renderer.text = text
        return renderer.getText(0, renderer.length)
    }
    function selectedText() {
        if (!hasSelection) return ""
        const start = compare(anchor, cursor) < 0 ? anchor : cursor
        const end = compare(anchor, cursor) < 0 ? cursor : anchor
        const rows = backend.displayMessages, pieces = []
        for (let row = start.row; row <= end.row && row < rows.length; row++) {
            const message = rows[row], segments = message.role === "user" ? [] : [{block:-100000,text:"umeko",markdown:false}]
            const activity = message.activity || []
            if (activity.length) {
                for (let stepIndex = 0; stepIndex < activity.length; stepIndex++) {
                    const step = activity[stepIndex]
                    if (step.kind === "text") {
                        Markdown.blocks(step.text || "", !step.error, stepIndex < activity.length - 1).forEach((block, index) => segments.push({block:step.blockOffset + index,text:block.text,markdown:!step.error && !block.code}))
                    } else if (step.kind === "thinking" && expandedDetails[row + ":" + step.blockOffset]) {
                        segments.push({block:step.blockOffset,text:step.text,markdown:false})
                    } else if (step.kind === "tools") {
                        step.tools.forEach((tool, index) => {
                            const key = step.blockOffset + index + 1
                            if (expandedDetails[row + ":" + key]) segments.push({block:key,text:JSON.stringify(tool.arguments || {}, null, 2) + (tool.result ? "\n\n" + tool.result : ""),markdown:false})
                        })
                    }
                }
            } else {
                const markdown = message.role === "assistant" && !message.error
                Markdown.blocks(message.text || "", markdown).forEach((block, index) => segments.push({block:index,text:block.text,markdown:markdown && !block.code}))
                if (message.role === "user") (message.attachments || []).forEach((item, index) => segments.push({block:10000 + index,text:item.name,markdown:false}))
            }
            for (const segment of segments) {
                const text = plain(segment.text, segment.markdown)
                const first = {row:row,block:segment.block,offset:0}, last = {row:row,block:segment.block,offset:text.length}
                if (compare(last, start) <= 0 || compare(first, end) >= 0) continue
                pieces.push(text.slice(compare(first, start) < 0 ? start.offset : 0, compare(last, end) > 0 ? end.offset : text.length))
            }
        }
        return pieces.join("\n\n").replace(/\u2029|\u2028/g, "\n")
    }
    function copy() { if (hasSelection) backend.copy(selectedText()) }
    function selectAll() {
        const rows = backend.displayMessages
        if (!rows.length) return
        anchor = {row:0,block:-100000,offset:0}
        cursor = {row:rows.length - 1,block:2147483647,offset:0}
        refresh(); forceActiveFocus()
    }
    Keys.onPressed: event => {
        if (event.key === Qt.Key_Escape) { clear(); event.accepted = true }
    }
    onVisibleChanged: if (!visible) clear()
    onDraggingChanged: lastScrollTime = Date.now()
    function autoScroll() {
        if (!dragging) return
        const now = Date.now(), elapsed = Math.min(100, Math.max(16, now - lastScrollTime))
        lastScrollTime = now
        const edge = 42
        const speed = pointer.y < edge ? -Math.min(28, (edge - pointer.y) * 0.55) : pointer.y > height - edge ? Math.min(28, (pointer.y - height + edge) * 0.55) : 0
        if (speed) { view.scrollBy(speed * elapsed / 16); Qt.callLater(root.extend) }
    }
    Connections {
        target: backend
        function onViewChanged() { root.clear() }
    }
    Timer { interval: 16; repeat: true; running: root.dragging; onTriggered: Qt.callLater(root.autoScroll) }
    Timer { id: refreshTimer; interval: 0; onTriggered: root.refresh() }
    TextEdit { id: renderer; visible: false; readOnly: true }
    MouseArea {
        anchors.fill: parent; anchors.rightMargin: 14
        acceptedButtons: Qt.LeftButton; preventStealing: true; hoverEnabled: true
        cursorShape: Qt.IBeamCursor
        onPressed: event => {
            const editor = root.pick(event.x, event.y, false)
            if (!editor) { root.clear(); event.accepted = false; return }
            if (!(event.modifiers & Qt.ShiftModifier) || !root.anchor) root.anchor = root.position(editor, event.x, event.y)
            root.cursor = root.position(editor, event.x, event.y)
            root.pointer = Qt.point(event.x, event.y); root.dragging = true
            root.view.beginBrowsing(); root.forceActiveFocus(); root.refresh()
        }
        onPositionChanged: event => { if (pressed && root.dragging) { root.pointer = Qt.point(event.x, event.y); Qt.callLater(root.extend) } }
        onReleased: { if (root.dragging) root.extend(); root.dragging = false }
        onCanceled: root.dragging = false
        onDoubleClicked: event => {
            const editor = root.pick(event.x, event.y, false)
            if (!editor) return
            editor.cursorPosition = root.position(editor, event.x, event.y).offset
            editor.selectWord()
            root.anchor = {row:editor.messageIndex,block:editor.blockIndex,offset:editor.selectionStart}
            root.cursor = {row:editor.messageIndex,block:editor.blockIndex,offset:editor.selectionEnd}
            root.refresh()
        }
        onWheel: event => {
            const delta = event.pixelDelta.y || event.angleDelta.y / 120 * 60
            if (delta) { root.view.scrollBy(-delta); if (root.dragging) root.extend() }
            event.accepted = true
        }
    }
}
